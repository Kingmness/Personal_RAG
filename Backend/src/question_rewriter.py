# -*- coding: utf-8 -*-
"""
问题改写器
识别涉及多个实体（公司、产品、地点、指标等）对比的问题，
并将其拆解为多个独立子问题，每个子问题只涉及单一实体。

判断策略:
1. 正则快速路径：识别公司名后缀模式（国际/科技/半导体...），命中则直接判定
2. LLM 慢速路径：正则未命中但存在分隔词（和/与/、），调用 LLM 做语义判断

示例：
  "中芯国际和华虹半导体2024年毛利率谁更高？"
  -> [{"question": "中芯国际2024年毛利率是多少？", "company_name": "中芯国际"},
      {"question": "华虹半导体2024年毛利率是多少？", "company_name": "华虹半导体"}]

  "上海迪士尼乐园和香港迪士尼乐园哪个面积更大？"
  -> [{"question": "上海迪士尼乐园的面积是多少？", "company_name": "上海迪士尼乐园"},
      {"question": "香港迪士尼乐园的面积是多少？", "company_name": "香港迪士尼乐园"}]
"""

import json
import re
from typing import List, Dict

from openai import OpenAI
from json_repair import repair_json
from config import DASHSCOPE_API_KEY, LLM_MODEL
from logger import setup_logger

_log = setup_logger(name="pra.question_rewriter")

# 比较类问题的常见关键词（不含连接词"和""与""及"，连接词在 _SEPARATOR 中单独处理）
_COMPARISON_KEYWORDS = [
    "谁", "哪个", "哪家", "哪一", "更高", "更低", "更多", "更少",
    "更大", "更小", "对比", "比较", "相比", "差异", "区别",
    "高于", "低于", "超过", "不如", "胜过",
    "vs", "VS", "versus",
]

# 多实体分隔词
_SEPARATORS = ["和", "与", "及", "、", "同", ",", "，"]

# 公司名后缀
_COMPANY_SUFFIX = (
    r'(?:国际|科技|股份|集团|有限|控股|实业|电子|半导体|医药|汽车|'
    r'能源|金融|保险|证券|银行|地产|通信|网络|软件|硬件|传媒|教育|物流|'
    r'乐园|酒店|景区|度假|航空|旅游|餐饮|零售|服装|食品|钢铁|化工|'
    r'建筑|建材|机械|电力|环保|水务|交通|港口|机场|铁路)'
)

# 公司名匹配：2-6 个中文字符 + 后缀
# 使用 word boundary 思路：公司名前面不能是中文字符（排除连接词被误匹配）
_COMPANY_PATTERN = re.compile(
    r'(?<=[、和与及同，,\s，])'
    r'[\u4e00-\u9fff]{2,6}'
    + _COMPANY_SUFFIX
    + r'|^[\u4e00-\u9fff]{2,6}'
    + _COMPANY_SUFFIX
)


class QuestionRewriter:
    """比较类问题拆解器"""

    def __init__(self):
        if not DASHSCOPE_API_KEY:
            raise ValueError("未找到 DASHSCOPE_API_KEY，请在 .env 文件中配置")
        self._model = LLM_MODEL
        self.client = OpenAI(
            api_key=DASHSCOPE_API_KEY,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )

    @staticmethod
    def is_comparison_question(question: str) -> bool:
        """
        判断是否为比较类问题

        比较类问题通常涉及两个或以上实体的对比，
        例如 "A和B谁的营收更高？"、"A与B的毛利率对比"

        Args:
            question: 用户问题

        Returns:
            True 表示是比较类问题
        """
        companies = _COMPANY_PATTERN.findall(question)
        if len(companies) < 2:
            return False
        has_comparison_kw = any(kw in question for kw in _COMPARISON_KEYWORDS)
        has_separator = any(sep in question for sep in _SEPARATORS)
        return has_comparison_kw or has_separator

    def needs_rewrite(self, question: str) -> bool:
        """
        判断问题是否需要拆解（含 LLM 回退）

        判断逻辑:
        1. 正则快速判断（公司名后缀模式） -> 命中则直接返回 True
        2. 正则未命中但存在分隔词 -> 调用 LLM 做语义判断
        3. 无分隔词 -> 返回 False

        Args:
            question: 用户问题

        Returns:
            True 表示需要拆解
        """
        if QuestionRewriter.is_comparison_question(question):
            return True

        has_separator = any(sep in question for sep in _SEPARATORS)
        if not has_separator:
            return False

        try:
            return self._llm_is_comparison(question)
        except Exception as e:
            _log.warning("LLM 比较判断失败，回退到正则结果: %s", e)
            return False

    def _llm_is_comparison(self, question: str) -> bool:
        """
        LLM 轻量判断：问题是否涉及多个实体/概念的对比

        使用极短 prompt，仅返回 true/false，延迟约 200-500ms

        Args:
            question: 用户问题

        Returns:
            True 表示是比较类问题
        """
        system_prompt = (
            "判断用户问题是否涉及两个或以上不同实体（公司、产品、地点、指标等）的对比或比较。"
            '仅返回 JSON: {"is_comparison": true} 或 {"is_comparison": false}'
        )
        user_prompt = f'问题："{question}"'

        resp = self.client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )

        content = resp.choices[0].message.content
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = json.loads(repair_json(content))

        return bool(parsed.get("is_comparison", False))

    def rewrite(self, question: str) -> List[Dict]:
        """
        将比较类问题拆解为多个独立子问题

        Args:
            question: 比较类问题

        Returns:
            子问题列表，每个元素为:
            {"question": "针对单一公司的问题", "company_name": "公司名"}
        """
        system_prompt = """你是一个问题分析专家。
用户的问题涉及多个不同实体（公司、产品、地点、指标等）的比较，请将其拆解为多个独立子问题，每个子问题只涉及一个实体。

要求：
1. 每个子问题只涉及一个实体
2. 子问题保留原问题的核心指标和时间范围
3. 返回 JSON 格式，包含 sub_questions 数组

示例1 - 公司比较：
问题："中芯国际和华虹半导体2024年毛利率谁更高？"
返回：
{"sub_questions": [
  {"question": "中芯国际2024年毛利率是多少？", "company_name": "中芯国际"},
  {"question": "华虹半导体2024年毛利率是多少？", "company_name": "华虹半导体"}
]}

示例2 - 非公司实体比较：
问题："上海迪士尼乐园和香港迪士尼乐园哪个面积更大？"
返回：
{"sub_questions": [
  {"question": "上海迪士尼乐园的面积是多少？", "company_name": "上海迪士尼乐园"},
  {"question": "香港迪士尼乐园的面积是多少？", "company_name": "香港迪士尼乐园"}
]}

示例3 - 指标比较：
问题："毛利率和净利率哪个更能反映盈利能力？"
返回：
{"sub_questions": [
  {"question": "毛利率如何反映盈利能力？", "company_name": "毛利率"},
  {"question": "净利率如何反映盈利能力？", "company_name": "净利率"}
]}"""

        user_prompt = f'问题："{question}"\n\n请拆解为独立子问题，返回 JSON 数组。'

        resp = self.client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )

        content = resp.choices[0].message.content
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = json.loads(repair_json(content))

        if isinstance(parsed, dict):
            sub_questions = parsed.get("sub_questions", parsed.get("results", []))
        elif isinstance(parsed, list):
            sub_questions = parsed
        else:
            _log.warning("LLM 返回格式异常，回退到正则拆解: %s", content)
            return self._rewrite_by_regex(question)

        if not sub_questions:
            _log.warning("LLM 拆解结果为空，回退到正则拆解")
            return self._rewrite_by_regex(question)

        result = []
        for sq in sub_questions:
            if isinstance(sq, dict) and "question" in sq and "company_name" in sq:
                result.append(sq)

        if not result:
            _log.warning("LLM 拆解结果缺少必要字段，回退到正则拆解")
            return self._rewrite_by_regex(question)

        _log.info("比较类问题拆解: '%s' -> %d 个子问题", question[:40], len(result))
        return result

    def _rewrite_by_regex(self, question: str) -> List[Dict]:
        """
        正则回退拆解：当 LLM 不可用或返回异常时使用

        Args:
            question: 比较类问题

        Returns:
            子问题列表
        """
        companies = _COMPANY_PATTERN.findall(question)
        # 清洗公司名：去掉可能残留的分隔词前缀
        cleaned_companies = []
        for c in companies:
            c = c.lstrip("".join(_SEPARATORS))
            if c:
                cleaned_companies.append(c)
        companies = cleaned_companies

        if len(companies) < 2:
            return [{"question": question, "company_name": companies[0] if companies else ""}]

        # 提取指标部分：去掉所有公司名后，用正则提取时间+指标组合
        indicator_part = question
        for company in companies:
            indicator_part = indicator_part.replace(company, "___")

        # 去掉分隔词
        for sep in _SEPARATORS:
            indicator_part = indicator_part.replace(sep, "")

        # 去掉比较关键词
        for kw in _COMPARISON_KEYWORDS:
            indicator_part = indicator_part.replace(kw, "")

        # 清理多余空白和占位符
        indicator_part = re.sub(r'(___\s*)+', '', indicator_part)
        indicator_part = re.sub(r'\s+', '', indicator_part)

        # 用正则提取时间+指标组合，避免暴力删除导致指标丢失
        # 匹配模式：年份+可选季度/上下半年 + 指标词
        _INDICATOR_PATTERN = re.compile(
            r'(\d{4}年(?:第[一二三四]季度|Q[1-4]|上?下半年)?)?'
            r'([\u4e00-\u9fff]*(?:率|额|量|价|比|度|收入|利润|支出|费用|资产|负债|现金流|面积|人数|产能|营收|毛利|净利)[\u4e00-\u9fff]*)'
        )
        indicator_match = _INDICATOR_PATTERN.search(indicator_part)
        if indicator_match:
            indicator_part = indicator_match.group(0)

        # 去掉疑问尾词和标点
        indicator_part = indicator_part.rstrip("？?的与和及比相对")
        # 去掉句首残留
        indicator_part = indicator_part.lstrip("的与和及比相对")

        result = []
        for company in companies:
            sub_q = f"{company}{indicator_part}是多少？"
            result.append({"question": sub_q, "company_name": company})

        _log.info("正则回退拆解: '%s' -> %d 个子问题", question[:40], len(result))
        return result
