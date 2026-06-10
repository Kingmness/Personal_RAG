# -*- coding: utf-8 -*-
"""
Markdown 文本分块工具
从 parsed_md 中读取带页码标记（<!-- 第N页 -->）的 Markdown 文件，
按页面切分后，每页按 300 token 进行分块，输出为 JSON 格式。
"""

import json
import re
import tiktoken
from pathlib import Path
from typing import List, Dict
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import CHUNK_SIZE, CHUNK_OVERLAP
from logger import setup_logger

_log = setup_logger(name="pra.text_chunker")

# 页码标记正则：匹配 <!-- 第N页 -->
PAGE_MARKER_RE = re.compile(r'<!--\s*第(\d+)页\s*-->')


class TextChunker:
    """基于页码标记对 Markdown 文件进行分块"""

    _encoding_cache = None
    _splitter_cache = None
    _cache_key = None

    def __init__(self, chunk_size: int = CHUNK_SIZE, chunk_overlap: int = CHUNK_OVERLAP):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        cache_key = (chunk_size, chunk_overlap)
        if TextChunker._cache_key == cache_key and TextChunker._encoding_cache is not None:
            self._splitter = TextChunker._splitter_cache
            self._encoding = TextChunker._encoding_cache
        else:
            self._splitter = self._init_splitter(chunk_size, chunk_overlap)
            self._encoding = self._init_encoding()
            TextChunker._splitter_cache = self._splitter
            TextChunker._encoding_cache = self._encoding
            TextChunker._cache_key = cache_key

    @staticmethod
    def _init_splitter(chunk_size, chunk_overlap):
        try:
            return RecursiveCharacterTextSplitter.from_tiktoken_encoder(
                model_name="gpt-4o",
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
        except Exception:
            return RecursiveCharacterTextSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""],
            )

    @staticmethod
    def _init_encoding():
        try:
            return tiktoken.encoding_for_model("gpt-4o")
        except Exception:
            try:
                return tiktoken.get_encoding("cl100k_base")
            except Exception:
                return None

    def count_tokens(self, text: str) -> int:
        """计算文本的 token 数"""
        if self._encoding is not None:
            return len(self._encoding.encode(text))
        return len(text)

    def _split_by_page(self, content: str) -> List[Dict]:
        """
        按 <!-- 第N页 --> 标记将 Markdown 内容拆分为页面列表

        Returns:
            [{"page": 1, "text": "..."}, {"page": 2, "text": "..."}, ...]
        """
        # 找到所有页码标记的位置
        markers = list(PAGE_MARKER_RE.finditer(content))
        if not markers:
            # 没有页码标记，整篇作为一个"页面"，page 设为 1
            return [{"page": 1, "text": content.strip()}]

        pages = []
        # 第一个标记之前的内容视为第 1 页（如果存在且非空）
        first_marker_start = markers[0].start()
        before_first = content[:first_marker_start].strip()
        first_page_num = int(markers[0].group(1))

        # 如果第一个标记前有内容且页码不连续（比如文件开头有前言），归入第一页
        if before_first:
            pages.append({"page": first_page_num, "text": before_first})

        # 处理每个标记后的内容
        for i, match in enumerate(markers):
            page_num = int(match.group(1))
            start = match.end()
            end = markers[i + 1].start() if i + 1 < len(markers) else len(content)
            page_text = content[start:end].strip()
            if page_text:
                pages.append({"page": page_num, "text": page_text})

        return pages

    def chunk_file(self, md_path: Path) -> List[Dict]:
        """
        对单个 Markdown 文件进行分块

        Args:
            md_path: Markdown 文件路径

        Returns:
            分块列表，每项包含 id, page, length_tokens, text
        """
        content = md_path.read_text(encoding="utf-8")
        pages = self._split_by_page(content)
        all_chunks = []
        chunk_id = 0

        for page_info in pages:
            page_num = page_info["page"]
            page_text = page_info["text"]

            if not page_text.strip():
                continue

            # 对当前页文本进行分块
            text_chunks = self._splitter.split_text(page_text)
            for chunk_text in text_chunks:
                all_chunks.append({
                    "id": chunk_id,
                    "page": page_num,
                    "length_tokens": self.count_tokens(chunk_text),
                    "text": chunk_text,
                })
                chunk_id += 1

        return all_chunks

    def chunk_all(self, input_dir: Path, output_dir: Path):
        """
        批量处理目录下所有 Markdown 文件

        Args:
            input_dir:  存放 Markdown 文件的目录
            output_dir: 分块后 JSON 文件的输出目录
        """
        md_files = sorted(input_dir.glob("*.md"))
        if not md_files:
            _log.info("目录下未找到 .md 文件: %s", input_dir)
            return

        output_dir.mkdir(parents=True, exist_ok=True)

        for md_path in md_files:
            _log.info("处理: %s", md_path.name)
            chunks = self.chunk_file(md_path)

            result = {
                "source_file": md_path.name,
                "chunk_count": len(chunks),
                "chunks": chunks,
            }

            output_path = output_dir / f"{md_path.stem}.json"
            output_path.write_text(
                json.dumps(result, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            _log.info("  -> %s (%d 个 chunk)", output_path.name, len(chunks))

        _log.info("完成，共处理 %d 个文件", len(md_files))