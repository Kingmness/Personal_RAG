# -*- coding: utf-8 -*-
"""questions_processing 模块单元测试"""
from questions_processing import QuestionProcessor


class TestExtractKeywords:
    """测试 _extract_keywords 方法"""

    def test_chinese_question(self):
        """中文问题提取关键词"""
        keywords = QuestionProcessor._extract_keywords("中芯国际2024年毛利率是多少？")
        assert len(keywords) > 0
        # 应包含有意义的词组
        has_meaningful = any(len(k) >= 2 for k in keywords)
        assert has_meaningful

    def test_empty_question(self):
        """空问题返回空列表"""
        keywords = QuestionProcessor._extract_keywords("")
        assert keywords == []

    def test_stop_words_filtered(self):
        """停用词被过滤"""
        keywords = QuestionProcessor._extract_keywords("的是什么")
        # 停用词应被过滤掉
        assert "的" not in keywords
        assert "是" not in keywords

    def test_english_keywords(self):
        """英文关键词提取"""
        keywords = QuestionProcessor._extract_keywords("中芯国际EPS是多少？")
        assert "EPS" in keywords


class TestExtractSnippets:
    """测试 _extract_snippets 方法"""

    def test_keyword_found(self):
        """关键词在文本中存在时截取"""
        text = "前缀内容。" * 50 + "毛利率为30%。" + "后缀内容。" * 50
        result = QuestionProcessor._extract_snippets(text, ["毛利率"])
        assert "毛利率" in result
        assert len(result) < len(text)

    def test_keyword_not_found(self):
        """关键词不存在时返回原文"""
        text = "这是一段没有关键词的文本。"
        result = QuestionProcessor._extract_snippets(text, ["不存在的关键词"])
        assert result == text

    def test_empty_keywords(self):
        """空关键词列表返回原文"""
        text = "这是一段文本。"
        result = QuestionProcessor._extract_snippets(text, [])
        assert result == text

    def test_empty_text(self):
        """空文本返回空"""
        result = QuestionProcessor._extract_snippets("", ["关键词"])
        assert result == ""

    def test_multiple_keywords(self):
        """多个关键词截取"""
        text = "营收增长20%。" + "填充内容。" * 30 + "毛利率为30%。"
        result = QuestionProcessor._extract_snippets(text, ["营收", "毛利率"])
        assert "营收" in result
        assert "毛利率" in result


class TestValidatePages:
    """测试 _validate_pages 方法"""

    def test_valid_pages(self):
        """有效页码保留"""
        claimed = [1, 2, 3]
        docs = [{"page": 1}, {"page": 2}, {"page": 3}, {"page": 4}]
        result = QuestionProcessor._validate_pages(claimed, docs)
        assert set(result) == {1, 2, 3}

    def test_hallucinated_pages_removed(self):
        """幻觉页码被移除"""
        claimed = [1, 2, 99]
        docs = [{"page": 1}, {"page": 2}, {"page": 3}]
        result = QuestionProcessor._validate_pages(claimed, docs)
        assert 99 not in result
        assert 1 in result
        assert 2 in result

    def test_none_pages(self):
        """None 页码处理"""
        docs = [{"page": 1}, {"page": 2}]
        result = QuestionProcessor._validate_pages(None, docs)
        assert isinstance(result, list)

    def test_empty_claimed_pages(self):
        """空声称页码补充"""
        docs = [{"page": 1}, {"page": 2}]
        result = QuestionProcessor._validate_pages([], docs, min_pages=1)
        assert len(result) >= 1


class TestFormatContext:
    """测试 _format_context 方法"""

    def test_basic_format(self):
        """基本格式化"""
        docs = [
            {"source": "test.pdf", "page": 1, "text": "测试内容", "score": 0.9},
        ]
        result = QuestionProcessor._format_context(docs, question="测试")
        assert "第1页" in result
        assert "test.pdf" in result

    def test_empty_documents(self):
        """空文档列表"""
        result = QuestionProcessor._format_context([])
        assert result == ""

    def test_context_truncation(self):
        """上下文截取生效"""
        long_text = "营收增长20%。" + "无关内容。" * 100
        docs = [
            {"source": "test.pdf", "page": 1, "text": long_text, "score": 0.9},
        ]
        result = QuestionProcessor._format_context(docs, question="营收增长")
        # 截取后长度应小于原文
        assert len(result) < len(long_text) + 50
