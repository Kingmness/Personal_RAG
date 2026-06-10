# -*- coding: utf-8 -*-
"""retrieval 模块单元测试"""
from retrieval import Retriever


class TestNormalizeScores:
    """测试 _normalize_scores 方法"""

    def test_empty_results(self):
        """空结果返回空字典"""
        assert Retriever._normalize_scores([]) == {}

    def test_single_result(self):
        """单条结果归一化为 1.0"""
        results = [{"chunk_id": 1, "score": 0.5}]
        assert Retriever._normalize_scores(results) == {1: 1.0}

    def test_multiple_results(self):
        """多条结果 min-max 归一化"""
        results = [
            {"chunk_id": 1, "score": 0.2},
            {"chunk_id": 2, "score": 0.8},
            {"chunk_id": 3, "score": 0.5},
        ]
        normalized = Retriever._normalize_scores(results)
        assert normalized[1] == 0.0
        assert normalized[2] == 1.0
        assert abs(normalized[3] - 0.5) < 0.01

    def test_equal_scores(self):
        """相同分数归一化为 1.0"""
        results = [
            {"chunk_id": 1, "score": 0.5},
            {"chunk_id": 2, "score": 0.5},
        ]
        normalized = Retriever._normalize_scores(results)
        assert normalized[1] == 1.0
        assert normalized[2] == 1.0


class TestBuildPages:
    """测试 _build_pages 方法"""

    def test_single_page(self):
        """单页多 chunk 拼接"""
        chunks = [
            {"page": 1, "text": "段落一"},
            {"page": 1, "text": "段落二"},
        ]
        pages = Retriever._build_pages(chunks)
        assert 1 in pages
        assert "段落一" in pages[1]
        assert "段落二" in pages[1]

    def test_multiple_pages(self):
        """多页分开"""
        chunks = [
            {"page": 1, "text": "第一页"},
            {"page": 2, "text": "第二页"},
            {"page": 3, "text": "第三页"},
        ]
        pages = Retriever._build_pages(chunks)
        assert len(pages) == 3
        assert pages[1] == "第一页"
        assert pages[2] == "第二页"
        assert pages[3] == "第三页"

    def test_empty_chunks(self):
        """空 chunk 列表"""
        pages = Retriever._build_pages([])
        assert pages == {}
