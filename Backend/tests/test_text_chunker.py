# -*- coding: utf-8 -*-
"""text_chunker 模块单元测试"""
import json
import tempfile
from pathlib import Path

from text_chunker import TextChunker


class TestSplitByPage:
    """测试 _split_by_page 方法"""

    def setup_method(self):
        self.chunker = TextChunker(chunk_size=300, chunk_overlap=50)

    def test_no_page_markers(self):
        """无页码标记时，整篇作为 page=1"""
        content = "这是一段没有页码标记的文本。"
        result = self.chunker._split_by_page(content)
        assert len(result) == 1
        assert result[0]["page"] == 1
        assert result[0]["text"] == "这是一段没有页码标记的文本。"

    def test_single_page_marker(self):
        """单个页码标记"""
        content = "<!-- 第1页 -->\n第一页内容"
        result = self.chunker._split_by_page(content)
        assert len(result) == 1
        assert result[0]["page"] == 1
        assert "第一页内容" in result[0]["text"]

    def test_multiple_page_markers(self):
        """多个页码标记"""
        content = "<!-- 第1页 -->\n第一页\n<!-- 第2页 -->\n第二页\n<!-- 第3页 -->\n第三页"
        result = self.chunker._split_by_page(content)
        assert len(result) == 3
        assert result[0]["page"] == 1
        assert result[1]["page"] == 2
        assert result[2]["page"] == 3

    def test_content_before_first_marker(self):
        """第一个标记前有内容"""
        content = "前言内容\n<!-- 第1页 -->\n第一页内容"
        result = self.chunker._split_by_page(content)
        assert len(result) == 2
        assert "前言内容" in result[0]["text"]
        assert "第一页内容" in result[1]["text"]

    def test_empty_page_skipped(self):
        """空页面被跳过"""
        content = "<!-- 第1页 -->\n第一页\n<!-- 第2页 -->\n\n<!-- 第3页 -->\n第三页"
        result = self.chunker._split_by_page(content)
        assert len(result) == 2
        assert result[0]["page"] == 1
        assert result[1]["page"] == 3


class TestChunkFile:
    """测试 chunk_file 方法"""

    def setup_method(self):
        self.chunker = TextChunker(chunk_size=300, chunk_overlap=50)

    def test_chunk_file_basic(self):
        """基本分块功能"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write("<!-- 第1页 -->\n" + "这是一段测试文本。" * 50)
            f.flush()
            md_path = Path(f.name)

        try:
            chunks = self.chunker.chunk_file(md_path)
            assert len(chunks) > 0
            assert all("id" in c for c in chunks)
            assert all("page" in c for c in chunks)
            assert all("text" in c for c in chunks)
            assert all("length_tokens" in c for c in chunks)
        finally:
            md_path.unlink()

    def test_chunk_file_empty(self):
        """空文件分块"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write("")
            f.flush()
            md_path = Path(f.name)

        try:
            chunks = self.chunker.chunk_file(md_path)
            assert len(chunks) == 0
        finally:
            md_path.unlink()


class TestChunkAll:
    """测试 chunk_all 方法"""

    def setup_method(self):
        self.chunker = TextChunker(chunk_size=300, chunk_overlap=50)

    def test_chunk_all_no_md_files(self):
        """目录下无 md 文件时不报错"""
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = Path(tmp) / "input"
            output_dir = Path(tmp) / "output"
            input_dir.mkdir()
            self.chunker.chunk_all(input_dir, output_dir)
            assert not output_dir.exists()

    def test_chunk_all_with_files(self):
        """批量分块生成 JSON"""
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = Path(tmp) / "input"
            output_dir = Path(tmp) / "output"
            input_dir.mkdir()

            (input_dir / "test1.md").write_text(
                "<!-- 第1页 -->\n" + "测试内容一。" * 30, encoding="utf-8"
            )
            (input_dir / "test2.md").write_text(
                "<!-- 第1页 -->\n" + "测试内容二。" * 30, encoding="utf-8"
            )

            self.chunker.chunk_all(input_dir, output_dir)

            assert (output_dir / "test1.json").exists()
            assert (output_dir / "test2.json").exists()

            data1 = json.loads((output_dir / "test1.json").read_text(encoding="utf-8"))
            assert data1["source_file"] == "test1.md"
            assert data1["chunk_count"] > 0
