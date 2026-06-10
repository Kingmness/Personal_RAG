# -*- coding: utf-8 -*-
"""
问题处理器
- 串联 retrieval -> reranking -> LLM 生成答案
- 支持 4 种答案类型：number / name / boolean / list
- 自动校验 LLM 引用的页码是否在检索结果中
"""

from pathlib import Path
from typing import List, Dict, Optional
import json
import time
import logging
from json_repair import repair_json

from retrieval import Retriever
from reranking import Reranker
from api_requests import LLMClient
from config import EMBEDDING_MODEL, LLM_MODEL, FAISS_TOP_N, BM25_TOP_N, CHUNKED_JSON_DIR, FAISS_INDEX_DIR, BM25_INDEX_DIR
from logger import setup_logger
import prompts

_log = setup_logger(name="pra.question_processor")


class QuestionProcessor:
    """RAG 问答处理器，串联检索、重排序、LLM 生成全流程"""

    def __init__(
        self,
        chunked_json_dir: Optional[Path] = None,
        faiss_dir: Optional[Path] = None,
        bm25_dir: Optional[Path] = None,
        embedding_model: str = EMBEDDING_MODEL,
        llm_model: str = LLM_MODEL,
        faiss_top_n: int = FAISS_TOP_N,
        bm25_top_n: int = BM25_TOP_N,
    ):
        self.faiss_top_n = faiss_top_n
        self.bm25_top_n = bm25_top_n

        self.retriever = Retriever(
            chunked_json_dir=chunked_json_dir or CHUNKED_JSON_DIR,
            faiss_dir=faiss_dir or FAISS_INDEX_DIR,
            bm25_dir=bm25_dir or BM25_INDEX_DIR,
            embedding_model=embedding_model,
        )
        self.reranker = Reranker(model=llm_model)
        self.llm = LLMClient(model=llm_model)

    # ==================== 关键词提取与上下文截取 ====================

    _STOP_WORDS = frozenset([
        "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一", "一个",
        "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好",
        "自己", "这", "他", "她", "它", "们", "那", "些", "什么", "哪些", "如何", "怎么",
        "怎样", "多少", "几", "第", "个", "等", "及", "与", "或", "被", "把", "从", "对",
        "为", "以", "于", "其", "该", "此", "每", "各", "所", "之", "而", "则",
        "吗", "呢", "吧", "啊", "呀", "嗯", "哦", "么", "能", "可以", "是否", "有没有",
        "情况", "方面", "关于", "对于", "通过", "进行", "以及", "还是", "已经", "目前",
        "以下", "以上", "之间", "之后", "之前", "今年", "去年",
    ])

    @classmethod
    def _extract_keywords(cls, question: str) -> List[str]:
        """
        从问题中提取关键词（去掉停用词，保留实词）
        对连续中文字符生成 2-gram 和 3-gram 组合，优先使用长词

        注意：此方法用于上下文截取（_extract_snippets），与 keyword_extractor.py
        中的 KeywordExtractor 用途不同。KeywordExtractor 基于正则+领域词典提取
        结构化关键词（公司名、指标等），用于检索路由；本方法基于 n-gram 提取通用
        关键词，用于在长文本中定位关键片段。

        Args:
            question: 用户问题

        Returns:
            关键词列表，如 ["半导体", "行业", "特征"]
        """
        import re
        # 提取连续中文字符段和英文/数字段
        segments = re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z0-9]+', question)
        keywords = []
        for seg in segments:
            if seg.isascii():
                # 英文/数字直接作为关键词
                if seg.lower() not in cls._STOP_WORDS and len(seg) > 0:
                    keywords.append(seg)
            else:
                # 中文：生成 3-gram 和 2-gram
                ngrams = []
                # 3-gram
                for i in range(len(seg) - 2):
                    ngrams.append(seg[i:i+3])
                # 2-gram
                for i in range(len(seg) - 1):
                    ngrams.append(seg[i:i+2])

                # 过滤：去掉包含停用字的 n-gram，去重，保持顺序
                seen = set()
                for w in ngrams:
                    if w in seen:
                        continue
                    # 跳过包含停用字的 n-gram
                    if any(c in cls._STOP_WORDS for c in w):
                        continue
                    seen.add(w)
                    keywords.append(w)

        _log.info("[上下文截取] 问题='%s' → 关键词=%s", question, keywords)
        return keywords

    @staticmethod
    def _extract_snippets(text: str, keywords: List[str], window: int = 100) -> str:
        """
        在文本中定位关键词，截取关键词前后各 window 个字符，合并重叠片段
        优先匹配长关键词，短关键词仅在未匹配到长关键词时生效

        Args:
            text:     文档原文
            keywords: 关键词列表
            window:   关键词前后截取的字符数

        Returns:
            截取并合并后的文本片段；找不到关键词时返回原文
        """
        if not keywords or not text:
            return text

        # 按长度降序排列，优先匹配长关键词
        sorted_kws = sorted(keywords, key=len, reverse=True)

        # 收集所有关键词匹配位置，记录已被长关键词覆盖的字符区间
        covered = set()
        positions = []

        for kw in sorted_kws:
            start = 0
            while True:
                idx = text.find(kw, start)
                if idx == -1:
                    break
                kw_range = set(range(idx, idx + len(kw)))
                # 长关键词直接匹配；短关键词（单字）仅匹配未被覆盖的位置
                if len(kw) > 1 or not kw_range & covered:
                    positions.append((max(0, idx - window), min(len(text), idx + len(kw) + window)))
                    covered |= kw_range
                start = idx + 1

        if not positions:
            _log.info("[上下文截取] 未匹配到任何关键词，使用原文")
            return text

        # 按起始位置排序
        positions.sort(key=lambda x: x[0])

        # 合并重叠或相邻的片段
        merged = [positions[0]]
        for start, end in positions[1:]:
            prev_start, prev_end = merged[-1]
            if start <= prev_end + 50:
                merged[-1] = (prev_start, max(prev_end, end))
            else:
                merged.append((start, end))

        # 向外扩展到句子边界（句号、换行符）
        sentence_ends = set("。！？\n；")
        refined = []
        for start, end in merged:
            # 向左扩展到句子边界
            expanded_start = start
            for i in range(start - 1, max(start - 50, -1), -1):
                if text[i] in sentence_ends:
                    expanded_start = i + 1
                    break
            # 向右扩展到句子边界
            expanded_end = end
            for i in range(end, min(end + 50, len(text))):
                if text[i] in sentence_ends:
                    expanded_end = i + 1
                    break
            refined.append((expanded_start, expanded_end))

        # 拼接片段
        snippets = []
        for start, end in refined:
            snippet = text[start:end].strip()
            if snippet:
                snippets.append(snippet)

        result = "...".join(snippets)
        _log.info("[上下文截取] 原文长度=%d, 截取后长度=%d, 片段数=%d",
                  len(text), len(result), len(snippets))
        return result

    # ==================== 上下文构建 ====================

    @classmethod
    def _format_context(cls, documents: List[Dict], question: str = "", window: int = 100) -> str:
        """
        将检索/重排结果格式化为 RAG 上下文字符串
        基于问题关键词对文档内容进行截取，减少送入 LLM 的 token 量

        Args:
            documents: [{"source": str, "page": int, "text": str, "score": float}, ...]
            question:  用户问题，用于提取关键词进行上下文截取
            window:    关键词前后截取的字符数

        Returns:
            格式化后的上下文字符串
        """
        if not documents:
            return ""

        keywords = cls._extract_keywords(question) if question else []

        parts = []
        for doc in documents:
            original_len = len(doc['text'])
            if keywords:
                truncated = cls._extract_snippets(doc['text'], keywords, window=window)
            else:
                truncated = doc['text']
            _log.info("[上下文截取] 第%d页: 原文=%d字符, 截取后=%d字符, 缩减=%.1f%%",
                      doc['page'], original_len, len(truncated),
                      (1 - len(truncated)/original_len)*100 if original_len > 0 else 0)
            parts.append(f"【第{doc['page']}页】（来源：{doc['source']}）\n{truncated}")

        return "\n\n---\n\n".join(parts)

    # ==================== 页码校验 ====================

    @staticmethod
    def _validate_pages(
        claimed_pages: Optional[List[int]],
        retrieved_docs: List[Dict],
        min_pages: int = 1,
    ) -> List[int]:
        """
        校验 LLM 引用的页码是否在检索结果中真实存在

        Args:
            claimed_pages:  LLM 声称的引用页码
            retrieved_docs: 检索到的文档列表
            min_pages:      最少需要引用的页数

        Returns:
            校验后的有效页码列表
        """
        if claimed_pages is None:
            claimed_pages = []

        retrieved_pages = {doc["page"] for doc in retrieved_docs}

        # 过滤掉不存在的页码
        valid = [p for p in claimed_pages if p in retrieved_pages]

        if len(valid) < len(claimed_pages):
            removed = set(claimed_pages) - set(valid)
            _log.info("已移除 %d 个幻觉页码: %s", len(removed), removed)

        # 页数不足时用检索 Top 页补充
        if len(valid) < min_pages and retrieved_docs:
            existing = set(valid)
            for doc in retrieved_docs:
                if doc["page"] not in existing:
                    valid.append(doc["page"])
                    existing.add(doc["page"])
                    if len(valid) >= min_pages:
                        break

        return valid

    # ==================== 主入口 ====================

    def answer(
        self,
        question: str,
        prompt_type: str = "number",
        route_top_k: int = 3,
        retrieve_top_n: int = 10,
        rerank_batch_size: int = 4,
        rerank_top_n: int = 10,
        llm_weight: float = 0.7,
    ) -> Dict:
        """
        对用户问题执行完整的 RAG 问答流程

        流程：
        1. 检索：路由 + FAISS/BM25 混合检索，返回整页文本
        2. 重排：LLM 相关性评分 + 检索分数加权融合
        3. 上下文构建：将重排结果拼接为 Prompt
        4. LLM 生成：调用通义千问生成结构化答案
        5. 页码校验：过滤 LLM 幻觉页码

        Args:
            question:        用户问题
            prompt_type:     答案类型 number/name/boolean/list
            route_top_k:     路由匹配的数据库数
            retrieve_top_n:  检索返回数量
            rerank_batch_size: 重排批次大小
            rerank_top_n:    重排后保留数量
            llm_weight:      LLM 重排权重

        Returns:
            {
                "question": str,
                "final_answer": any,
                "step_by_step_analysis": str,
                "reasoning_summary": str,
                "relevant_pages": [int, ...],
                "context_docs": [{"source": str, "page": int, "text": str, "score": float}, ...],
            }
        """
        _log.info("=" * 60)
        _log.info("[QA] 问题: %s", question)
        _log.info("[QA] 类型: %s", prompt_type)

        # Step 1: 检索
        _log.info("[QA] Step1: 检索开始, question=%s", question)
        _t0 = time.time()
        retrieved = self.retriever.retrieve(
            query=question,
            route_top_k=route_top_k,
            faiss_top_n=self.faiss_top_n,
            bm25_top_n=self.bm25_top_n,
            hybrid_top_n=retrieve_top_n,
        )
        _s1 = time.time() - _t0
        _log.info("[QA] Step1: 检索完成, 返回%d页, 耗时=%.2fs", len(retrieved), _s1)
        if _s1 > 5.0:
            _log.warning("[QA告警] Step1 检索 耗时=%.2fs > 阈值=5.0s, 可能存在索引加载或网络延迟", _s1)
        _log.info("[QA] 检索到 %d 条结果", len(retrieved))

        # Step 2: 重排序
        _log.info("[QA] Step2: 重排开始, 输入%d条", len(retrieved))
        _t0 = time.time()
        reranked = self.reranker.rerank(
            query=question,
            documents=retrieved,
            batch_size=rerank_batch_size,
            llm_weight=llm_weight,
            top_n=rerank_top_n,
        )
        _s2 = time.time() - _t0
        _log.info("[QA] Step2: 重排完成, 保留%d条, 耗时=%.2fs", len(reranked), _s2)
        if _s2 > 15.0:
            _log.warning("[QA告警] Step2 重排序 耗时=%.2fs > 阈值=15.0s, 可能存在API限流或batch过大", _s2)
        _log.info("[QA] 重排保留 %d 条", len(reranked))

        # Step 3: 构建上下文
        _t0 = time.time()
        context = self._format_context(reranked, question=question)
        _s3 = time.time() - _t0
        _log.info("[QA] Step3: 上下文构建完成, 长度=%d字符, 耗时=%.2fs", len(context), _s3)
        if _s3 > 2.0:
            _log.warning("[QA告警] Step3 上下文构建 耗时=%.2fs > 阈值=2.0s, 文档数量或长度可能异常", _s3)
        for d in reranked:
            _log.info("  - %s 第%d页  score=%.4f", d['source'][:40], d['page'], d['score'])

        # Step 4: LLM 生成答案
        step4_start = time.time()
        _log.info("[QA] Step4: LLM生成答案开始")
        llm_result = self.llm.answer_with_context(
            question=question,
            context=context,
            prompt_type=prompt_type,
        )
        _s4 = time.time() - step4_start
        _log.info("[QA] Step4: LLM生成答案完成, 耗时=%.2fs", _s4)
        if _s4 > 30.0:
            _log.warning("[QA告警] Step4 LLM生成 耗时=%.2fs > 阈值=30.0s, 上下文可能过长或API响应慢", _s4)

        # Step 5: 页码校验
        raw_pages = llm_result.get("relevant_pages", [])
        validated_pages = self._validate_pages(raw_pages, reranked)

        return {
            "question": question,
            "final_answer": llm_result.get("final_answer"),
            "step_by_step_analysis": llm_result.get("step_by_step_analysis", ""),
            "reasoning_summary": llm_result.get("reasoning_summary", ""),
            "relevant_pages": validated_pages,
            "context_docs": [
                {
                    "source": d["source"],
                    "page": d["page"],
                    "text": d["text"],
                    "score": d["score"],
                    "relevance_score": d.get("relevance_score"),
                    "reasoning": d.get("reasoning"),
                    "combined_score": d.get("combined_score"),
                }
                for d in reranked
            ],
        }

    def answer_stream(
        self,
        question: str,
        prompt_type: str = "number",
        route_top_k: int = 3,
        retrieve_top_n: int = 10,
        rerank_batch_size: int = 4,
        rerank_top_n: int = 10,
        llm_weight: float = 0.7,
    ):
        """
        流式 RAG 问答流程，逐步 yield 进度事件和 LLM 流式输出

        Yields:
            dict: 每个事件包含 type 和对应数据
                - {"type": "step", "step": 1, "name": "检索", "status": "start"}
                - {"type": "step", "step": 1, "name": "检索", "status": "done", "elapsed": 2.3}
                - {"type": "step", "step": 4, "name": "LLM生成", "status": "streaming"}
                - {"type": "token", "content": "..."}
                - {"type": "result", "data": {...}}
        """
        import time

        # 各步骤耗时告警阈值（秒）
        _STEP_THRESHOLDS = {
            1: (5.0, "检索耗时超过5秒，可能存在索引加载或网络延迟"),
            2: (15.0, "重排序耗时超过15秒，可能存在API限流或batch过大"),
            3: (2.0, "上下文构建耗时超过2秒，文档数量或长度可能异常"),
            4: (30.0, "LLM生成耗时超过30秒，上下文可能过长或API响应慢"),
        }

        _STEP_NAMES = {1: "检索", 2: "重排序", 3: "上下文构建", 4: "LLM生成"}

        def _check_step_alert(step: int, elapsed: float):
            threshold, msg = _STEP_THRESHOLDS.get(step, (999, ""))
            if elapsed > threshold:
                _log.warning("[QA告警] Step%d %s 耗时=%.2fs > 阈值=%.1fs, %s",
                             step, _STEP_NAMES.get(step, ""), elapsed, threshold, msg)

        total_start = time.time()

        # Step 1: 检索
        t0 = time.time()
        yield {"type": "step", "step": 1, "name": "检索", "status": "start"}
        retrieved = self.retriever.retrieve(
            query=question,
            route_top_k=route_top_k,
            faiss_top_n=self.faiss_top_n,
            bm25_top_n=self.bm25_top_n,
            hybrid_top_n=retrieve_top_n,
        )
        s1_elapsed = round(time.time() - t0, 2)
        _check_step_alert(1, s1_elapsed)
        yield {"type": "step", "step": 1, "name": "检索", "status": "done",
               "elapsed": s1_elapsed, "count": len(retrieved)}

        # Step 2: 重排序
        t0 = time.time()
        yield {"type": "step", "step": 2, "name": "重排序", "status": "start"}
        reranked = self.reranker.rerank(
            query=question,
            documents=retrieved,
            batch_size=rerank_batch_size,
            llm_weight=llm_weight,
            top_n=rerank_top_n,
        )
        s2_elapsed = round(time.time() - t0, 2)
        _check_step_alert(2, s2_elapsed)
        yield {"type": "step", "step": 2, "name": "重排序", "status": "done",
               "elapsed": s2_elapsed, "count": len(reranked)}

        # Step 3: 构建上下文
        t0 = time.time()
        yield {"type": "step", "step": 3, "name": "上下文构建", "status": "start"}
        context = self._format_context(reranked, question=question)
        s3_elapsed = round(time.time() - t0, 2)
        _check_step_alert(3, s3_elapsed)
        yield {"type": "step", "step": 3, "name": "上下文构建", "status": "done",
               "elapsed": s3_elapsed, "context_len": len(context)}

        # Step 4: LLM 流式生成
        t0 = time.time()
        yield {"type": "step", "step": 4, "name": "LLM生成", "status": "start"}
        prompt_config = prompts.build_answer_prompt(prompt_type)
        system_content = prompt_config["system"]
        user_content = prompts.build_user_prompt(question, context)

        full_text = ""
        for token in self.llm.chat_stream(system_content, user_content):
            full_text += token
            yield {"type": "token", "content": token}

        s4_elapsed = round(time.time() - t0, 2)
        _check_step_alert(4, s4_elapsed)
        yield {"type": "step", "step": 4, "name": "LLM生成", "status": "done",
               "elapsed": s4_elapsed}

        # 解析 JSON 结果
        try:
            llm_result = json.loads(full_text)
        except json.JSONDecodeError:
            llm_result = json.loads(repair_json(full_text))

        # Step 5: 页码校验
        raw_pages = llm_result.get("relevant_pages", [])
        validated_pages = self._validate_pages(raw_pages, reranked)

        result = {
            "question": question,
            "final_answer": llm_result.get("final_answer"),
            "step_by_step_analysis": llm_result.get("step_by_step_analysis", ""),
            "relevant_pages": validated_pages,
            "context_docs": [
                {
                    "source": d["source"],
                    "page": d["page"],
                    "text": d["text"],
                    "score": d["score"],
                    "relevance_score": d.get("relevance_score"),
                    "reasoning": d.get("reasoning"),
                    "combined_score": d.get("combined_score"),
                }
                for d in reranked
            ],
            "elapsed": round(time.time() - total_start, 2),
            "step_elapsed": {
                "检索": s1_elapsed,
                "重排序": s2_elapsed,
                "上下文构建": s3_elapsed,
                "LLM生成": s4_elapsed,
            },
        }

        yield {"type": "result", "data": result}

