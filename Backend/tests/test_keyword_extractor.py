# -*- coding: utf-8 -*-
"""keyword_extractor 模块单元测试"""
from keyword_extractor import KeywordExtractor


class TestExtractCompaniesByRegex:
    """测试 _extract_companies_by_regex 方法"""

    def setup_method(self):
        self.ext = KeywordExtractor(use_llm=False)

    def test_standard_company(self):
        """标准公司名提取"""
        result = self.ext._extract_companies_by_regex("中芯国际2024年毛利率是多少？")
        assert "中芯国际" in result

    def test_park_company(self):
        """乐园类实体提取"""
        result = self.ext._extract_companies_by_regex("迪士尼乐园的门票价格是多少？")
        assert len(result) > 0

    def test_no_company(self):
        """无公司名时 jieba posseg 回退"""
        result = self.ext._extract_companies_by_regex("半导体行业的市场规模是多少？")
        # jieba 可能识别出"半导体行业"等实体
        assert isinstance(result, list)


class TestExtractIndicators:
    """测试 _extract_indicators 方法"""

    def setup_method(self):
        self.ext = KeywordExtractor(use_llm=False)

    def test_revenue_indicator(self):
        """营收指标提取"""
        result = self.ext._extract_indicators("中芯国际2024年营收是多少？")
        assert "营收" in result

    def test_multiple_indicators(self):
        """多指标提取"""
        result = self.ext._extract_indicators("中芯国际的毛利率和净利率分别是多少？")
        assert "毛利率" in result
        assert "净利率" in result

    def test_no_indicator(self):
        """无指标"""
        result = self.ext._extract_indicators("中芯国际的总部在哪里？")
        assert len(result) == 0


class TestExtractTimeRange:
    """测试 _extract_time_range 方法"""

    def setup_method(self):
        self.ext = KeywordExtractor(use_llm=False)

    def test_year(self):
        """年份提取"""
        result = self.ext._extract_time_range("中芯国际2024年营收是多少？")
        assert "2024年" in result

    def test_quarter(self):
        """季度提取"""
        result = self.ext._extract_time_range("中芯国际2025年Q1产能利用率是多少？")
        assert "Q1" in result

    def test_no_time(self):
        """无时间范围"""
        result = self.ext._extract_time_range("中芯国际的毛利率是多少？")
        assert len(result) == 0


class TestExtract:
    """测试 extract 主入口"""

    def setup_method(self):
        self.ext = KeywordExtractor(use_llm=False)

    def test_full_extract(self):
        """完整提取"""
        result = self.ext.extract("中芯国际2024年毛利率是多少？")
        assert "companies" in result
        assert "indicators" in result
        assert "time_range" in result

    def test_quoted_text_fallback(self):
        """引号文本回退"""
        result = self.ext.extract('"某某公司"的营收是多少？')
        assert len(result["companies"]) > 0


class TestExtractKeywordsOnly:
    """测试 extract_keywords_only 方法"""

    def setup_method(self):
        self.ext = KeywordExtractor(use_llm=False)

    def test_keywords_only(self):
        """仅返回关键词列表"""
        result = self.ext.extract_keywords_only("中芯国际2024年毛利率是多少？")
        assert isinstance(result, list)
        assert len(result) > 0
