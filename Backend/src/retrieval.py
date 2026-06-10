# -*- coding: utf-8 -*-
"""
检索引擎
- 路由：对用户问题嵌入后在所有 FAISS 数据库中匹配，筛选相关数据库
- FAISS 检索：向量相似度检索
- BM25 检索：关键词检索
- 混合检索：FAISS + BM25 加权融合
- 父页面返回：根据匹配 chunk 的原始页码，返回整页数据
"""

import json
import pickle
import threading
from collections import OrderedDict
from pathlib import Path
from typing import List, Dict

import numpy as np
import faiss
from dashscope import MultiModalEmbedding
import jieba
from config import EMBEDDING_MODEL, KEYWORD_FILTER_ENABLED, KEYWORD_BONUS_PER_MATCH
from logger import setup_logger
from retry_utils import retry_embedding_call

_log = setup_logger(name="pra.retrieval")


class _SafeUnpickler(pickle.Unpickler):
    """仅允许反序列化安全类型的 Unpickler，防止恶意 pkl 文件执行任意代码"""
    SAFE_CLASSES = {
        'rank_bm25': {'BM25Okapi'},
        'collections': {'Counter', 'defaultdict', 'OrderedDict'},
    }

    def find_class(self, module, name):
        if module in self.SAFE_CLASSES and name in self.SAFE_CLASSES[module]:
            return super().find_class(module, name)
        if module == 'builtins' and name in ('list', 'dict', 'tuple', 'set', 'int', 'float', 'str', 'bool', 'bytes', 'NoneType'):
            return super().find_class(module, name)
        raise pickle.UnpicklingError(f"不允许反序列化: {module}.{name}")


class Retriever:
    """
    混合检索引擎（懒加载 + LRU 缓存）
    流程：嵌入问题 -> 路由筛选数据库 -> FAISS/BM25 并行检索 -> 加权融合 -> 父页面返回

    启动时仅扫描索引目录，不加载内容；首次检索时按需加载对应数据库的索引；
    内置 LRU 缓存，超过容量时自动卸载最久未访问的数据库。
    """

    # LRU 缓存最大保留的数据库数量
    LRU_MAX_SIZE = 10

    def __init__(
        self,
        chunked_json_dir: Path,
        faiss_dir: Path,
        bm25_dir: Path,
        embedding_model: str = EMBEDDING_MODEL,
    ):
        self.chunked_json_dir = chunked_json_dir
        self.faiss_dir = faiss_dir
        self.bm25_dir = bm25_dir
        self.embedding_model = embedding_model

        # 懒加载：仅扫描目录，记录可用的 stem 列表
        self._available_stems: List[str] = []
        # 已加载的数据库缓存：{stem: {faiss, bm25, chunks, pages}}
        self._db_cache: OrderedDict = OrderedDict()
        self._cache_lock = threading.Lock()

        # 扫描可用索引
        self._scan_available()

        # 加载文档关键字映射（stem -> keywords 逗号分隔字符串）
        self._keywords_map: Dict[str, str] = self._load_keywords_map()

        # 初始化关键字提取器（正则模式，检索路径优先速度）
        from keyword_extractor import KeywordExtractor
        self._keyword_extractor = KeywordExtractor(use_llm=False)

    # ==================== 扫描与懒加载 ====================

    def _scan_available(self):
        """扫描索引目录，记录可用的 stem 列表（不加载内容）"""
        json_files = sorted(self.chunked_json_dir.glob("*.json"))
        self._available_stems = [f.stem for f in json_files]

        if not self._available_stems:
            raise RuntimeError("未找到任何可用的索引数据库，请先运行索引构建")

        _log.info("[扫描] 发现 %d 个可用数据库: %s", len(self._available_stems),
                  self._available_stems[:5] if len(self._available_stems) > 5 else self._available_stems)

    def _load_single(self, stem: str) -> dict:
        """按需加载单个数据库的索引（chunked_json + FAISS + BM25）"""
        # 加载 chunked JSON
        json_path = self.chunked_json_dir / f"{stem}.json"
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        chunks = data["chunks"]
        pages = self._build_pages(chunks)

        # 加载 FAISS 索引
        faiss_index = None
        faiss_path = self.faiss_dir / f"{stem}.faiss"
        if faiss_path.exists():
            try:
                faiss_index = faiss.read_index(str(faiss_path))
                _log.info("  [懒加载] %s: FAISS 索引加载成功 (%d 条向量)", stem, faiss_index.ntotal)
            except Exception as e:
                _log.warning("  [懒加载] %s: FAISS 索引加载失败: %s", stem, e)

        # 加载 BM25 索引
        bm25_index = None
        bm25_path = self.bm25_dir / f"{stem}.pkl"
        if bm25_path.exists():
            try:
                with open(bm25_path, "rb") as f:
                    bm25_index = _SafeUnpickler(f).load()
                _log.info("  [懒加载] %s: BM25 索引加载成功", stem)
            except Exception as e:
                _log.warning("  [懒加载] %s: BM25 索引加载失败: %s", stem, e)

        return {
            "source_file": data.get("source_file", stem),
            "chunks": chunks,
            "pages": pages,
            "faiss": faiss_index,
            "bm25": bm25_index,
        }

    def _get_db(self, stem: str) -> dict:
        """获取数据库（LRU 缓存，未命中则按需加载）"""
        with self._cache_lock:
            if stem in self._db_cache:
                # 命中缓存，移到末尾（最近访问）
                self._db_cache.move_to_end(stem)
                return self._db_cache[stem]

        # 缓存未命中，加载
        _log.info("[懒加载] 加载数据库: %s", stem)
        db = self._load_single(stem)

        with self._cache_lock:
            self._db_cache[stem] = db
            self._db_cache.move_to_end(stem)

            # LRU 淘汰：超过容量时移除最久未访问的
            while len(self._db_cache) > self.LRU_MAX_SIZE:
                evicted_stem, _ = self._db_cache.popitem(last=False)
                _log.info("[懒加载] LRU 淘汰数据库: %s", evicted_stem)

        return db

    @property
    def databases(self) -> Dict[str, dict]:
        """兼容属性：返回当前缓存中的所有数据库（用于路由等场景）"""
        # 路由需要遍历所有数据库的 FAISS，所以需要确保路由所需的数据库已加载
        return dict(self._db_cache)

    @staticmethod
    def _build_pages(chunks: List[dict]) -> Dict[int, str]:
        """将同属一页的 chunk 拼接为完整页面文本"""
        pages: Dict[int, List[str]] = {}
        for chunk in chunks:
            page_num = chunk["page"]
            if page_num not in pages:
                pages[page_num] = []
            pages[page_num].append(chunk["text"])
        return {p: "\n".join(texts) for p, texts in pages.items()}

    def _load_keywords_map(self) -> Dict[str, str]:
        """从 metadata.csv 加载文档关键字映射"""
        try:
            from metadata import MetadataManager
            mgr = MetadataManager()
            kw_map = mgr.get_keywords_map()
            _log.info("已加载 %d 个文档的关键字映射", len(kw_map))
            for stem, kws in kw_map.items():
                if kws:
                    _log.info("  %s: %s", stem, kws[:80])
            return kw_map
        except Exception as e:
            _log.warning("加载关键字映射失败，将跳过关键字过滤: %s", e)
            return {}

    def _keyword_filter(self, query: str) -> Dict[str, int]:
        """
        从用户问题中提取关键字，与文档关键字匹配，返回匹配的数据库及匹配数

        Args:
            query: 用户问题

        Returns:
            {stem: match_count} 匹配数 > 0 的数据库
        """
        if not self._keywords_map:
            return {}

        # 提取问题关键字
        query_keywords = self._keyword_extractor.extract_keywords_only(query)
        if not query_keywords:
            _log.info("[关键字过滤] 问题未提取到关键字，跳过过滤")
            return {}

        _log.info("[关键字过滤] 问题关键字: %s", query_keywords)

        matched = {}
        for stem, doc_keywords_str in self._keywords_map.items():
            if not doc_keywords_str:
                continue
            # 将文档关键字字符串拆分为集合
            doc_kws = set(kw.strip() for kw in doc_keywords_str.split(",") if kw.strip())
            # 计算匹配数：问题关键字中出现在文档关键字中的数量
            match_count = sum(1 for qk in query_keywords if qk in doc_kws)
            if match_count > 0:
                matched[stem] = match_count
                _log.info("[关键字过滤] %s 匹配 %d 个关键字", stem, match_count)

        if matched:
            _log.info("[关键字过滤] 命中 %d 个数据库: %s", len(matched), list(matched.keys()))
        else:
            _log.info("[关键字过滤] 无关键字匹配，将使用纯向量路由")

        return matched

    # ==================== 嵌入 ====================

    def _embed_query(self, query: str) -> np.ndarray:
        """将用户问题转为嵌入向量（含指数退避重试）"""
        resp = retry_embedding_call(
            call_fn=lambda: MultiModalEmbedding.call(
                model=self.embedding_model,
                input=[{"text": query}],
            )
        )
        vec = resp.output["embeddings"][0]["embedding"]
        arr = np.array(vec, dtype=np.float32).reshape(1, -1)
        faiss.normalize_L2(arr)
        return arr

    # ==================== 路由 ====================

    def _route(self, query_embedding: np.ndarray, route_top_k: int = 5, query: str = "") -> List[str]:
        """
        在所有 FAISS 数据库中进行路由匹配，返回匹配到的数据库名称列表

        策略：
        1. 先用关键字过滤缩小候选范围
        2. 在候选数据库中进行向量路由排序
        3. 若关键字匹配数不足 route_top_k，用向量路由补充
        """
        # Step 1: 关键字过滤
        kw_matched = self._keyword_filter(query) if (query and KEYWORD_FILTER_ENABLED) else {}

        # Step 2: 向量路由（按需加载所有数据库的 FAISS 索引）
        db_scores = []

        for stem in self._available_stems:
            db = self._get_db(stem)
            faiss_index = db["faiss"]
            if faiss_index is None:
                continue
            k = min(3, faiss_index.ntotal)
            if k == 0:
                continue
            distances, _ = faiss_index.search(query_embedding, k)
            avg_score = float(np.mean(distances[0]))
            # 关键字匹配加分：匹配数越多加分越高
            kw_bonus = kw_matched.get(stem, 0) * KEYWORD_BONUS_PER_MATCH
            db_scores.append((stem, avg_score, kw_bonus))

        # 按综合分数降序排列（向量相似度 + 关键字加分）
        db_scores.sort(key=lambda x: x[1] + x[2], reverse=True)
        
        _log.info("[路由] 全部数据库评分 (向量相似度 + 关键字加分):")
        for i, (stem, score, kw_bonus) in enumerate(db_scores):
            marker = " <<=" if i < route_top_k else ""
            kw_info = f" +kw={kw_bonus:.1f}" if kw_bonus > 0 else ""
            _log.info("  %d. %s : vec=%.6f%s%s", i + 1, stem, score, kw_info, marker)
        
        matched = [name for name, _, _ in db_scores[:route_top_k]]
        _log.info("[路由] 选中 %d 个数据库: %s", len(matched), matched)
        return matched

    # ==================== FAISS 检索 ====================

    def _faiss_search(
        self, query_embedding: np.ndarray, db_name: str, top_n: int
    ) -> List[dict]:
        """
        在指定数据库中进行 FAISS 向量检索
        返回: [{"chunk_id": int, "page": int, "text": str, "score": float}, ...]
        """
        db = self._get_db(db_name)
        faiss_index = db["faiss"]
        if faiss_index is None:
            return []

        k = min(top_n, faiss_index.ntotal)
        distances, indices = faiss_index.search(query_embedding, k)

        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < 0 or idx >= len(db["chunks"]):
                _log.warning("  [FAISS] %s: 跳过无效索引 idx=%d", db_name, idx)
                continue
            chunk = db["chunks"][idx]
            results.append({
                "chunk_id": chunk["id"],
                "page": chunk["page"],
                "text": chunk["text"],
                "score": round(float(dist), 4),
            })

        _log.info("  [FAISS] %s: 返回 %d 条 (k=%d, total=%d)",
                  db_name, len(results), k, faiss_index.ntotal)
        for r in results:
            preview = r["text"][:100].replace('\n', ' ')
            _log.info("    chunk_id=%d  page=%d  dist=%.4f  %s",
                      r["chunk_id"], r["page"], r["score"], preview)

        return results

    # ==================== BM25 检索 ====================

    def _bm25_search(self, query: str, db_name: str, top_n: int) -> List[dict]:
        """
        在指定数据库中进行 BM25 检索
        返回: [{"chunk_id": int, "page": int, "text": str, "score": float}, ...]
        """
        db = self._get_db(db_name)
        bm25_index = db["bm25"]
        if bm25_index is None:
            return []

        chunks = db["chunks"]
        tokenized_query = jieba.lcut(query)
        scores = bm25_index.get_scores(tokenized_query)

        k = min(top_n, len(scores))
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]

        results = []
        for idx in top_indices:
            chunk = chunks[idx]
            results.append({
                "chunk_id": chunk["id"],
                "page": chunk["page"],
                "text": chunk["text"],
                "score": round(float(scores[idx]), 4),
            })

        _log.info("  [BM25] %s: 返回 %d 条 (total_chunks=%d)",
                  db_name, len(results), len(scores))
        for r in results:
            preview = r["text"][:100].replace('\n', ' ')
            _log.info("    chunk_id=%d  page=%d  score=%.4f  %s",
                      r["chunk_id"], r["page"], r["score"], preview)

        return results

    # ==================== 混合检索 ====================

    def _hybrid_fusion(
        self,
        faiss_results: List[dict],
        bm25_results: List[dict],
        top_n: int,
        faiss_weight: float = 0.6,
        bm25_weight: float = 0.4,
    ) -> List[dict]:
        """
        FAISS + BM25 加权融合

        策略：
        1. 对 FAISS 和 BM25 各自的结果分数做 min-max 归一化
        2. 按 chunk_id 合并：同一 chunk 的分数 = faiss_weight * norm_faiss + bm25_weight * norm_bm25
        3. 对只在单侧出现的 chunk，缺失侧分数计为 0.3（而非 0），避免被完全淘汰
        4. 按融合分数降序取 top_n
        """
        # 构建 chunk_id -> 归一化分数的映射
        faiss_map = self._normalize_scores(faiss_results)
        bm25_map = self._normalize_scores(bm25_results)

        # 合并所有 chunk_id
        all_ids = set(faiss_map.keys()) | set(bm25_map.keys())

        fused = []
        for cid in all_ids:
            f_score = faiss_map.get(cid, 0.3)
            b_score = bm25_map.get(cid, 0.3)
            combined = faiss_weight * f_score + bm25_weight * b_score
            fused.append((cid, combined, faiss_map.get(cid, -1), bm25_map.get(cid, -1)))

        # 按融合分数降序
        fused.sort(key=lambda x: x[1], reverse=True)

        # 还原原始 chunk 信息（提前建立查找表，用于日志打印）
        chunk_lookup = {}
        for r in faiss_results + bm25_results:
            if r["chunk_id"] not in chunk_lookup:
                chunk_lookup[r["chunk_id"]] = r

        _log.info("  [融合] faiss=%d, bm25=%d, 共%d个chunk_id, 取top%d",
                  len(faiss_results), len(bm25_results), len(all_ids), top_n)
        _log.info("  [融合] 融合前全部 %d 个 chunk_id 的排序:", len(fused))
        for rank, (cid, combined_score, f_score, b_score) in enumerate(fused):
            info = chunk_lookup.get(cid, {})
            text_preview = info.get("text", "")[:80].replace('\n', ' ')
            marker = " <-- topN" if rank < top_n else ""
            _log.info("    [%d] chunk_id=%d  page=%d  combined=%.4f  faiss=%.4f  bm25=%.4f  %s%s",
                      rank + 1, cid, info.get("page", '?'),
                      combined_score, f_score, b_score, text_preview, marker)

        top = fused[:top_n]

        results = []
        for cid, combined_score, f_score, b_score in top:
            info = chunk_lookup[cid]
            results.append({
                "chunk_id": info["chunk_id"],
                "page": info["page"],
                "text": info["text"],
                "score": round(combined_score, 4),
                "faiss_score": round(f_score, 4),
                "bm25_score": round(b_score, 4),
            })

        _log.info("  [融合] faiss=%d, bm25=%d, 共%d个chunk_id, 取top%d",
                  len(faiss_results), len(bm25_results), len(all_ids), top_n)
        for r in results:
            preview = r["text"][:120].replace('\n', ' ')
            _log.info("    chunk_id=%d  page=%d  combined=%.4f  faiss=%.4f  bm25=%.4f  %s",
                      r["chunk_id"], r["page"], r["score"], r["faiss_score"], r["bm25_score"], preview)

        return results

    @staticmethod
    def _normalize_scores(results: List[dict]) -> Dict[int, float]:
        """对检索结果分数做 min-max 归一化到 [0, 1]"""
        if not results:
            return {}
        scores = [r["score"] for r in results]
        min_s, max_s = min(scores), max(scores)
        if max_s == min_s:
            return {r["chunk_id"]: 1.0 for r in results}
        return {
            r["chunk_id"]: round((r["score"] - min_s) / (max_s - min_s), 4)
            for r in results
        }

    # ==================== 父页面返回 ====================

    def _to_parent_pages(self, fused_results: List[dict], db_name: str) -> List[dict]:
        """
        根据融合结果的页码，返回对应数据库中的整页文本
        去重：返回唯一页码列表，按融合分数中的顺序排列
        """
        db = self._get_db(db_name)
        pages = db["pages"]

        seen = set()
        page_results = []
        for r in fused_results:
            page_num = r["page"]
            if page_num in seen:
                continue
            seen.add(page_num)
            page_text = pages.get(page_num, "")
            page_results.append({
                "page": page_num,
                "text": page_text.strip(),
                "score": r["score"],
            })

        _log.info("  [父页面] %s: %d 个融合 chunk -> %d 个唯一页码 -> 返回 %d 页",
                  db_name, len(fused_results), len(seen), len(page_results))

        return page_results

    # ==================== 主检索入口 ====================

    def retrieve(
        self,
        query: str,
        route_top_k: int = 3,
        faiss_top_n: int = 10,
        bm25_top_n: int = 10,
        hybrid_top_n: int = 5,
        faiss_weight: float = 0.6,
        bm25_weight: float = 0.4,
    ) -> List[dict]:
        """
        主检索入口

        流程：
        1. 嵌入问题
        2. 路由：在所有数据库中找到最相关的
        3. 对匹配到的每个数据库并行 FAISS + BM25 检索
        4. 加权融合，取 hybrid_top_n
        5. 返回整页文本

        Args:
            query:           用户问题
            route_top_k:     路由时匹配的数据库数量
            faiss_top_n:     FAISS 检索返回数量
            bm25_top_n:      BM25 检索返回数量
            hybrid_top_n:    混合融合后返回数量
            faiss_weight:    FAISS 权重（0~1）
            bm25_weight:     BM25 权重（0~1）

        Returns:
            [{"source": "数据库名", "page": 页码, "text": "整页文本", "score": 融合分数}, ...]
        """
        _log.info("[检索] 问题: %s", query)
        _log.info("[检索] 开始检索, route_top_k=%d, faiss_top_n=%d, bm25_top_n=%d, hybrid_top_n=%d",
                  route_top_k, faiss_top_n, bm25_top_n, hybrid_top_n)

        # Step 1: 嵌入
        query_emb = self._embed_query(query)

        # Step 2: 路由 — 关键字过滤 + 向量路由筛选相关数据库
        matched_dbs = self._route(query_emb, route_top_k=route_top_k, query=query)
        _log.info("[检索] 匹配到的数据库: %s", matched_dbs)

        all_page_results = []

        for db_name in matched_dbs:
            _log.info("[检索] 处理数据库: %s", db_name)
            # Step 3: FAISS 检索
            faiss_results = self._faiss_search(query_emb, db_name, faiss_top_n)
            # Step 4: BM25 检索
            bm25_results = self._bm25_search(query, db_name, bm25_top_n)

            if not faiss_results and not bm25_results:
                _log.info("[检索] %s: 无结果，跳过", db_name)
                continue

            # Step 5: 混合融合
            fused = self._hybrid_fusion(
                faiss_results, bm25_results,
                top_n=hybrid_top_n,
                faiss_weight=faiss_weight,
                bm25_weight=bm25_weight,
            )

            # Step 6: 父页面返回
            page_results = self._to_parent_pages(fused, db_name)
            for pr in page_results:
                pr["source"] = db_name
                all_page_results.append(pr)

        # 按分数降序排列所有跨数据库结果
        all_page_results.sort(key=lambda x: x["score"], reverse=True)

        _log.info("[检索] 全部数据库合并后共 %d 页, 取top%d",
                  len(all_page_results), hybrid_top_n)
        for r in all_page_results:
            _log.info("  -> %s 第%d页  score=%.4f  %s...",
                      r["source"][:40], r["page"], r["score"], r["text"][:100].replace('\n', ' '))

        return all_page_results[:hybrid_top_n]

