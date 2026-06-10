# -*- coding: utf-8 -*-
"""
索引构建工具
从 chunked_json 读取分块数据，为每个源文档分别构建 BM25 索引和 FAISS 向量库。
- BM25 索引：基于 rank_bm25，保存为 .pkl 文件
- FAISS 向量库：基于通义千问多模态向量模型，保存为 .faiss 文件
"""

import os
import json
import pickle
from pathlib import Path
from typing import List, Optional

import numpy as np
import faiss
from rank_bm25 import BM25Okapi
from dashscope import MultiModalEmbedding
import jieba
from config import DASHSCOPE_API_KEY, EMBEDDING_MODEL, KEYWORD_USE_LLM, KEYWORD_SAMPLE_CHUNKS
from logger import setup_logger
from retry_utils import retry_embedding_call

_log = setup_logger(name="pra.ingestion")

# 批量调用 API 时每批最大文本数
MAX_BATCH_SIZE = 10


class BM25Ingestor:
    """为每个源文档构建并保存 BM25 索引"""

    def __init__(self):
        pass

    @staticmethod
    def _build_index(texts: List[str]) -> BM25Okapi:
        """对文本列表分词后构建 BM25 索引（使用 jieba 中文分词）"""
        tokenized = [jieba.lcut(text) for text in texts]
        return BM25Okapi(tokenized)

    def process_all(self, input_dir: Path, output_dir: Path):
        """
        批量处理 chunked_json 下所有 JSON 文件

        Args:
            input_dir:  存放分块 JSON 的目录
            output_dir: BM25 索引输出目录
        """
        json_files = sorted(input_dir.glob("*.json"))
        if not json_files:
            _log.warning("目录下未找到 JSON 文件: %s", input_dir)
            return

        output_dir.mkdir(parents=True, exist_ok=True)

        for json_path in json_files:
            self.process_single(json_path, output_dir)

        _log.info("BM25 索引构建完成，共处理 %d 个文件", len(json_files))

    def process_single(self, json_path: Path, output_dir: Path):
        """
        单个 JSON 文件构建 BM25 索引

        Args:
            json_path:  单个分块 JSON 文件路径
            output_dir: BM25 索引输出目录
        """
        if not json_path.exists():
            _log.warning("文件不存在: %s", json_path)
            return

        output_dir.mkdir(parents=True, exist_ok=True)

        _log.info("构建 BM25 索引: %s", json_path.name)
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        texts = [chunk["text"] for chunk in data["chunks"]]
        index = self._build_index(texts)

        output_path = output_dir / f"{json_path.stem}.pkl"
        with open(output_path, "wb") as f:
            pickle.dump(index, f)

        _log.info("BM25 索引构建完成: %s", output_path.name)


class VectorDBIngestor:
    """为每个源文档构建并保存 FAISS 向量库"""

    def __init__(self, embedding_model: str = EMBEDDING_MODEL):
        if not DASHSCOPE_API_KEY:
            raise ValueError("未在 .env 文件中找到 DASHSCOPE_API_KEY，请在 Backend/.env 中配置")
        os.environ["DASHSCOPE_API_KEY"] = DASHSCOPE_API_KEY
        self.embedding_model = embedding_model

    def _get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """
        调用通义千问多模态向量模型，分批获取文本嵌入向量

        Args:
            texts: 待嵌入的文本列表

        Returns:
            嵌入向量列表，每个向量为 float 列表
        """
        # 过滤空文本
        texts = [t for t in texts if t.strip()]
        if not texts:
            return []

        all_embeddings = []

        for i in range(0, len(texts), MAX_BATCH_SIZE):
            batch = texts[i:i + MAX_BATCH_SIZE]
            # 多模态模型输入格式：[{"text": "..."}, ...]
            batch_input = [{"text": t} for t in batch]

            resp = retry_embedding_call(
                call_fn=lambda bi=batch_input: MultiModalEmbedding.call(
                    model=self.embedding_model,
                    input=bi,
                )
            )

            # output.embeddings 是列表，每个元素含 embedding, index, type
            embeddings_list = resp.output.get("embeddings", [])
            if not embeddings_list:
                raise RuntimeError("DashScope 返回的 embeddings 为空")

            # 按 index 排序确保顺序一致
            embeddings_list.sort(key=lambda x: x.get("index", 0))
            for emb in embeddings_list:
                vec = emb.get("embedding", [])
                if not vec:
                    raise RuntimeError("DashScope 返回的 embedding 为空")
                all_embeddings.append(vec)

        return all_embeddings

    @staticmethod
    def _build_index(embeddings: List[List[float]]) -> faiss.IndexFlatIP:
        """基于嵌入向量构建 FAISS IndexFlatIP（内积，等价于余弦相似度）"""
        arr = np.array(embeddings, dtype=np.float32)
        # L2 归一化，使内积等价于余弦相似度
        faiss.normalize_L2(arr)
        dim = arr.shape[1]
        index = faiss.IndexFlatIP(dim)
        index.add(arr)
        return index

    def process_all(self, input_dir: Path, output_dir: Path):
        """
        批量处理 chunked_json 下所有 JSON 文件

        Args:
            input_dir:  存放分块 JSON 的目录
            output_dir: FAISS 索引输出目录
        """
        json_files = sorted(input_dir.glob("*.json"))
        if not json_files:
            _log.warning("目录下未找到 JSON 文件: %s", input_dir)
            return

        output_dir.mkdir(parents=True, exist_ok=True)

        for json_path in json_files:
            self.process_single(json_path, output_dir)

        _log.info("FAISS 向量库构建完成，共处理 %d 个文件", len(json_files))

    def process_single(self, json_path: Path, output_dir: Path):
        """
        单个 JSON 文件构建 FAISS 向量库

        Args:
            json_path:  单个分块 JSON 文件路径
            output_dir: FAISS 索引输出目录
        """
        if not json_path.exists():
            _log.warning("文件不存在: %s", json_path)
            return

        output_dir.mkdir(parents=True, exist_ok=True)

        _log.info("构建 FAISS 向量库: %s", json_path.name)
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        texts = [chunk["text"] for chunk in data["chunks"]]
        _log.info("  -> 正在获取 %d 个文本块的嵌入向量...", len(texts))
        embeddings = self._get_embeddings(texts)

        index = self._build_index(embeddings)

        output_path = output_dir / f"{json_path.stem}.faiss"
        faiss.write_index(index, str(output_path))
        _log.info("  -> 已保存 (%d 条向量, 维度 %d)", index.ntotal, index.d)


class KeywordIngestor:
    """为每个源文档提取关键字标签并更新 metadata.csv"""

    def __init__(self, use_llm: Optional[bool] = None):
        """
        初始化关键字提取器

        Args:
            use_llm: 是否使用 LLM 辅助提取，None 时读取配置
        """
        from keyword_extractor import KeywordExtractor
        from metadata import MetadataManager

        _use_llm = use_llm if use_llm is not None else KEYWORD_USE_LLM
        self.extractor = KeywordExtractor(use_llm=_use_llm)
        self.metadata_mgr = MetadataManager()

    def process_single(self, json_path: Path):
        """
        单个文档提取关键字并更新 metadata

        Args:
            json_path: 分块 JSON 文件路径
        """
        if not json_path.exists():
            _log.warning("文件不存在: %s", json_path)
            return

        _log.info("提取文档关键字: %s", json_path.name)

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        chunks = data.get("chunks", [])
        if not chunks:
            _log.warning("文档无 chunk 数据: %s", json_path.name)
            return

        # 取前几个 chunk 的文本作为内容摘要
        sample_texts = [c["text"] for c in chunks[:KEYWORD_SAMPLE_CHUNKS]]
        content_sample = "\n".join(sample_texts)

        # 提取关键字和元信息
        file_name = data.get("source_file", json_path.name)
        result = self.extractor.extract_document_keywords(file_name, content_sample)
        keywords_str = self.extractor.document_keywords_to_string(result)

        company_name = result.get("company_name", "")
        report_type = result.get("report_type", "")
        report_year = result.get("report_year", "")

        _log.info("  -> 公司: %s, 类型: %s, 年份: %s", company_name, report_type, report_year)
        _log.info("  -> 关键字: %s", keywords_str)

        # 更新 metadata（用 stem 匹配，因为 metadata 中 file_name 可能是 PDF 名）
        stem = json_path.stem
        # 尝试直接匹配文件名
        record = self.metadata_mgr.get_by_file_name(file_name)
        if record is None:
            # 尝试按 stem 匹配（PDF 文件名 = stem + .pdf）
            record = self.metadata_mgr.get_by_file_name(f"{stem}.pdf")
        if record is not None:
            self.metadata_mgr.update_metadata(
                record["file_name"],
                company_name=company_name,
                report_type=report_type,
                report_year=report_year,
                keywords=keywords_str,
            )
        else:
            _log.warning("  -> metadata 中未找到文档 %s，跳过关键字更新", json_path.name)

    def process_all(self, input_dir: Path):
        """
        批量处理目录下所有 JSON 文件

        Args:
            input_dir: 存放分块 JSON 的目录
        """
        json_files = sorted(input_dir.glob("*.json"))
        if not json_files:
            _log.warning("目录下未找到 JSON 文件: %s", input_dir)
            return

        for json_path in json_files:
            self.process_single(json_path)

        _log.info("文档关键字提取完成，共处理 %d 个文件", len(json_files))