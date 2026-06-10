# -*- coding: utf-8 -*-
"""question_rewriter 模块单元测试"""
from question_rewriter import QuestionRewriter, _COMPANY_PATTERN


class TestIsComparisonQuestion:
    """测试 is_comparison_question 方法"""

    def test_company_comparison(self):
        """公司比较类问题"""
        assert QuestionRewriter.is_comparison_question(
            "中芯国际和华虹半导体2024年毛利率谁更高？"
        )

    def test_non_comparison(self):
        """非比较类问题"""
        assert not QuestionRewriter.is_comparison_question(
            "中芯国际2024年毛利率是多少？"
        )

    def test_single_company(self):
        """单公司非比较"""
        assert not QuestionRewriter.is_comparison_question(
            "中芯国际的营收增长了吗？"
        )


class TestCompanyPattern:
    """测试公司名正则匹配"""

    def test_standard_suffix(self):
        """标准后缀匹配"""
        matches = _COMPANY_PATTERN.findall("中芯国际和华虹半导体")
        assert "中芯国际" in matches
        assert "华虹半导体" in matches

    def test_park_suffix(self):
        """乐园后缀匹配"""
        matches = _COMPANY_PATTERN.findall("上海迪士尼乐园和香港迪士尼乐园")
        assert len(matches) >= 2

    def test_no_match(self):
        """无匹配"""
        matches = _COMPANY_PATTERN.findall("今天天气怎么样")
        assert len(matches) == 0


class TestRewriteByRegex:
    """测试 _rewrite_by_regex 方法"""

    def _make_rewriter(self):
        """创建不需要 API Key 的 rewriter 实例"""
        rw = object.__new__(QuestionRewriter)
        return rw

    def test_basic_rewrite(self):
        """基本拆解"""
        rw = self._make_rewriter()
        result = rw._rewrite_by_regex("中芯国际和华虹半导体2024年毛利率谁更高？")
        assert len(result) == 2
        assert result[0]["company_name"] == "中芯国际"
        assert result[1]["company_name"] == "华虹半导体"
        # 指标应保留
        assert "毛利率" in result[0]["question"]
        assert "毛利率" in result[1]["question"]

    def test_single_company_fallback(self):
        """单公司回退"""
        rw = self._make_rewriter()
        result = rw._rewrite_by_regex("中芯国际的毛利率是多少？")
        assert len(result) == 1
        assert result[0]["company_name"] == "中芯国际"

    def test_indicator_preserved(self):
        """指标在拆解后保留"""
        rw = self._make_rewriter()
        result = rw._rewrite_by_regex("中芯国际和华虹半导体2024年营收谁更高？")
        for r in result:
            assert "营收" in r["question"]
