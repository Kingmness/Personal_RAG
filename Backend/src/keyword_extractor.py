# -*- coding: utf-8 -*-
"""
问题关键字提取器
从用户问题或文档文本中提取核心关键字（实体、概念、指标等），
用于辅助检索路由的精准匹配。
支持 LLM 模式（主力）和正则模式（回退）。
"""

import json
import re
from typing import List, Dict, Optional

import jieba.posseg as pseg
from openai import OpenAI
from json_repair import repair_json
from config import DASHSCOPE_API_KEY, LLM_MODEL, INDICATOR_KEYWORDS, DIMENSION_KEYWORDS


class KeywordExtractor:
    """从文本中提取结构化关键字，支持 LLM 和正则两种模式"""

    # 正则模式：匹配中文实体名（公司、乐园、交易所、银行等）
    ENTITY_PATTERN = re.compile(
        r'(?:[\u4e00-\u9fff]{2,8}(?:国际|科技|股份|集团|有限|控股|实业|电子|半导体|医药|汽车|'
        r'能源|金融|保险|证券|银行|地产|通信|网络|软件|硬件|传媒|教育|物流|'
        r'乐园|酒店|景区|度假村|度假|航空|旅游|餐饮|零售|服装|食品|钢铁|化工|'
        r'建筑|建材|机械|电力|环保|水务|交通|港口|机场|铁路|交易所))'
    )

    # 知名实体词典（正则无法匹配的无后缀品牌/机构名）
    KNOWN_ENTITIES = [
        "迪士尼", "中芯国际", "浦发银行", "华泰证券", "东方证券",
        "光大证券", "中原证券", "国信证券", "兴证国际", "上海证券",
        "腾讯", "阿里", "百度", "华为", "小米", "苹果", "谷歌",
        "港股", "A股", "美股", "深股", "沪股",
    ]

    # 常见指标关键词（从 config 集中管理）
    INDICATOR_KEYWORDS = INDICATOR_KEYWORDS

    # 常见维度关键词（从 config 集中管理）
    DIMENSION_KEYWORDS = DIMENSION_KEYWORDS

    # 概念关键词（正则回退时使用）
    CONCEPT_KEYWORDS = [
        "交易规则", "流媒体", "考核办法", "AI编程", "股票交易",
        "期货", "证券", "订阅", "旅游攻略", "深度研究",
        "季报点评", "业绩点评", "年报", "调研纪要",
        "晶圆制造", "芯片", "代工", "产能利用率",
        "客户经理", "个金", "考核指标",
        "主题乐园", "游乐园",
    ]

    def __init__(self, use_llm: bool = False):
        """
        初始化关键字提取器

        Args:
            use_llm: 是否使用 LLM 辅助提取（更准确但更慢）
        """
        self.use_llm = use_llm
        self._model = LLM_MODEL

        if use_llm:
            if not DASHSCOPE_API_KEY:
                raise ValueError("未找到 DASHSCOPE_API_KEY")
            self.client = OpenAI(
                api_key=DASHSCOPE_API_KEY,
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            )

    # ==================== 正则提取模式（回退） ====================

    def _extract_entities_by_regex(self, text: str) -> List[str]:
        """使用正则+知名实体词典提取文本中的具名实体，正则未命中时回退到 jieba posseg"""
        matches = self.ENTITY_PATTERN.findall(text)
        seen = set()
        result = []
        for m in matches:
            if m not in seen:
                seen.add(m)
                result.append(m)

        # 补充知名实体词典匹配
        for entity in self.KNOWN_ENTITIES:
            if entity in text and entity not in seen:
                seen.add(entity)
                result.append(entity)

        if not result:
            result = self._extract_entities_by_posseg(text)

        return result

    @staticmethod
    def _extract_entities_by_posseg(text: str) -> List[str]:
        """使用 jieba posseg 提取机构名(nt)和其他专名(nz)"""
        result = []
        seen = set()
        for word, flag in pseg.cut(text):
            if flag in ("nt", "nz") and len(word) >= 2 and word not in seen:
                seen.add(word)
                result.append(word)
        return result

    def _extract_concepts_by_regex(self, text: str) -> List[str]:
        """使用概念词典提取文本中的概念关键词"""
        found = []
        for kw in self.CONCEPT_KEYWORDS:
            if kw in text:
                found.append(kw)
        return found

    def _extract_indicators(self, text: str) -> List[str]:
        """提取文本中的指标关键词"""
        found = []
        for kw in self.INDICATOR_KEYWORDS:
            if kw in text:
                found.append(kw)
        return found

    def _extract_dimensions(self, text: str) -> List[str]:
        """提取文本中的维度关键词"""
        found = []
        for kw in self.DIMENSION_KEYWORDS:
            if kw in text:
                found.append(kw)
        return found

    def _extract_quoted_text(self, text: str) -> List[str]:
        """提取文本中被引号包裹的文本"""
        return re.findall(r'"([^"]*)"', text) or re.findall(r'\u201c([^\u201d]*)\u201d', text)

    def _extract_time_range(self, text: str) -> List[str]:
        """提取文本中的时间范围"""
        patterns = [
            r'\d{4}年',
            r'\d{4}-\d{4}',
            r'Q[1-4]',
            r'\d{4}年Q[1-4]',
            r'\d{4}年第[一二三四]季度',
            r'第[一二三四]季度',
            r'\d{4}年(上|下)半年',
            r'(上|下)半年',
        ]
        results = []
        for pat in patterns:
            matches = re.findall(pat, text)
            results.extend(matches)
        return list(set(results))

    # ==================== LLM 提取模式（主力） ====================

    def _extract_by_llm(self, text: str, is_document: bool = False) -> dict:
        """
        使用 LLM 提取结构化关键字

        Args:
            text:        输入文本（用户问题或文档摘要）
            is_document: 是否为文档摘要（True 时提取文档标签，False 时提取问题关键字）
        """
        if is_document:
            system_prompt = self._DOCUMENT_PROMPT
        else:
            system_prompt = self._QUESTION_PROMPT

        resp = self.client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f'文本："{text}"\n\n请提取结构化关键字。'},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )

        content = resp.choices[0].message.content
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return json.loads(repair_json(content))

    _QUESTION_PROMPT = """你是一个问题分析专家。
请从用户问题中提取结构化关键字，返回 JSON 格式。

提取维度：
- entities: 问题中涉及的具名实体列表（公司、乐园、交易所、银行、证券机构、产品名等任何具名对象）
- concepts: 问题中涉及的抽象概念/主题列表（交易规则、流媒体、考核办法、AI编程、股票交易等）
- indicators: 问题中涉及的量化指标列表（营收、毛利率、产能利用率等）
- time_range: 时间范围（如2025年Q1、2024年下半年等，字符串）
- question_type: 答案类型（number/name/boolean/list/text）

示例1：
问题："港股交易规则中买入股票的最小单位是多少？"
返回：{"entities": ["港股"], "concepts": ["交易规则", "股票交易"], "indicators": [], "time_range": "", "question_type": "number"}

示例2：
问题："迪士尼流媒体有哪些方案？"
返回：{"entities": ["迪士尼"], "concepts": ["流媒体", "订阅方案"], "indicators": [], "time_range": "", "question_type": "list"}

示例3：
问题："中芯国际2025年Q1产能利用率是多少？"
返回：{"entities": ["中芯国际"], "concepts": [], "indicators": ["产能利用率"], "time_range": "2025年Q1", "question_type": "number"}

示例4：
问题："浦发银行客户经理考核办法中，个金客户经理的考核指标有哪些？"
返回：{"entities": ["浦发银行"], "concepts": ["考核办法", "客户经理"], "indicators": [], "time_range": "", "question_type": "list"}"""

    _DOCUMENT_PROMPT = """你是一个文档元信息提取专家。
请从文档的文件名和内容摘要中提取元信息和关键字标签，返回 JSON 格式。

提取维度：
- company_name: 文档主要研究的公司或机构名称（如"中芯国际"、"迪士尼"、"浦发银行"；若非公司文档则填"无"）
- report_type: 文档类型，从以下选项中选择：研报、年报、调研纪要、规则制度、攻略指南、介绍说明、其他
- report_year: 文档涉及的年份（如"2025"、"2024"；无法判断则填空字符串）
- entities: 文档涉及的具名实体列表（公司、乐园、交易所、银行、证券机构等）
- concepts: 文档涉及的抽象概念/主题列表（交易规则、流媒体、考核办法、晶圆制造等）
- indicators: 文档涉及的量化指标列表（营收、毛利率、产能利用率等）

要求：
1. entities 和 concepts 尽量精炼，每个关键词不超过6个字，不要返回句子片段
2. 指标仅提取文档中重点讨论的量化指标
3. 不要遗漏文件名中包含的实体和概念
4. company_name 应为最核心的一个实体，不要返回列表

示例1：
文本："【上海证券】中芯国际深度研究报告：晶圆制造龙头，领航国产芯片新征程\n增收增利能力稳定向好..."
返回：{"company_name": "中芯国际", "report_type": "研报", "report_year": "", "entities": ["中芯国际", "上海证券"], "concepts": ["深度研究", "晶圆制造", "芯片"], "indicators": []}

示例2：
文本："港股交易规则介绍\n交易账户 交易时间 交易标的..."
返回：{"company_name": "无", "report_type": "规则制度", "report_year": "", "entities": ["港股"], "concepts": ["交易规则", "股票交易"], "indicators": []}

示例3：
文本："迪士尼乐园流媒体介绍包括不同方案的价格、功能差异..."
返回：{"company_name": "迪士尼", "report_type": "介绍说明", "report_year": "", "entities": ["迪士尼"], "concepts": ["流媒体", "订阅方案"], "indicators": []}

示例4：
文本："浦发上海浦东发展银行西安分行个金客户经理考核办法..."
返回：{"company_name": "浦发银行", "report_type": "规则制度", "report_year": "", "entities": ["浦发银行"], "concepts": ["考核办法", "客户经理"], "indicators": []}

示例5：
文本："香港迪士尼乐园旅游攻略..."
返回：{"company_name": "迪士尼", "report_type": "攻略指南", "report_year": "", "entities": ["香港迪士尼乐园"], "concepts": ["旅游攻略"], "indicators": []}"""

    # ==================== 主入口 ====================

    def extract(self, question: str) -> Dict:
        """
        提取问题的结构化关键字

        Args:
            question: 用户问题文本

        Returns:
            {
                "entities": ["中芯国际"],
                "concepts": ["深度研究"],
                "indicators": ["产能利用率", "毛利率"],
                "time_range": ["2025年Q1"],
                "question_type": "number",
            }
        """
        if self.use_llm:
            result = self._extract_by_llm(question, is_document=False)
        else:
            result = {
                "entities": self._extract_entities_by_regex(question),
                "concepts": self._extract_concepts_by_regex(question),
                "indicators": self._extract_indicators(question),
                "time_range": self._extract_time_range(question),
            }

        if not result.get("entities"):
            quoted = self._extract_quoted_text(question)
            if quoted:
                result["entities"] = quoted

        return result

    def extract_document_keywords(self, file_name: str, content_sample: str) -> Dict:
        """
        提取文档的关键字标签和元信息（用于索引构建时写入 metadata）

        Args:
            file_name:      文档文件名
            content_sample: 文档内容摘要（前几个 chunk 的文本）

        Returns:
            {"company_name": "中芯国际", "report_type": "研报", "report_year": "2025",
             "entities": [...], "concepts": [...], "indicators": [...]}
        """
        combined_text = f"{file_name}\n{content_sample}"

        if self.use_llm:
            result = self._extract_by_llm(combined_text, is_document=True)
            # 确保 LLM 返回了元信息字段
            result.setdefault("company_name", "")
            result.setdefault("report_type", "")
            result.setdefault("report_year", "")
            return result
        else:
            # 正则回退模式：从文件名推断元信息
            company_name = self._infer_company_name(file_name)
            report_type = self._infer_report_type(file_name)
            report_year = self._infer_report_year(file_name)
            return {
                "company_name": company_name,
                "report_type": report_type,
                "report_year": report_year,
                "entities": self._extract_entities_by_regex(combined_text),
                "concepts": self._extract_concepts_by_regex(combined_text),
                "indicators": self._extract_indicators(combined_text),
            }

    @staticmethod
    def _infer_company_name(file_name: str) -> str:
        """从文件名推断公司名"""
        # 匹配【xxx证券】等前缀中的证券机构名
        import re as _re
        m = _re.search(r'【(.+?)】', file_name)
        if m:
            prefix = m.group(1)
            # 如果前缀是"财报"，继续看后面
            if prefix == "财报":
                rest = file_name.split("】", 1)[-1]
                # 尝试匹配冒号前的公司名
                if "：" in rest:
                    return rest.split("：")[0].strip()
                elif ":" in rest:
                    return rest.split(":")[0].strip()

        # 匹配常见公司名
        companies = ["中芯国际", "浦发银行", "迪士尼", "华泰证券", "东方证券",
                     "光大证券", "中原证券", "国信证券", "兴证国际", "上海证券"]
        for c in companies:
            if c in file_name:
                return c
        return ""

    @staticmethod
    def _infer_report_type(file_name: str) -> str:
        """从文件名推断报告类型"""
        if "财报" in file_name or "年报" in file_name or "年度报告" in file_name:
            return "年报"
        elif "调研" in file_name or "纪要" in file_name:
            return "调研纪要"
        elif "交易规则" in file_name or "考核办法" in file_name:
            return "规则制度"
        elif "攻略" in file_name:
            return "攻略指南"
        elif "介绍" in file_name or "方案" in file_name:
            return "介绍说明"
        elif "研报" in file_name or "研究" in file_name or "点评" in file_name:
            return "研报"
        return "其他"

    @staticmethod
    def _infer_report_year(file_name: str) -> str:
        """从文件名推断报告年份"""
        import re as _re
        m = _re.search(r'(20\d{2})', file_name)
        return m.group(1) if m else ""

    def extract_keywords_only(self, question: str) -> List[str]:
        """
        仅提取用于检索路由的关键词列表（不含分类）

        Args:
            question: 用户问题文本

        Returns:
            关键词列表
        """
        result = self.extract(question)

        keywords = []
        for key in ["entities", "concepts", "indicators", "time_range"]:
            items = result.get(key, [])
            if isinstance(items, list):
                keywords.extend(items)
            elif isinstance(items, str) and items:
                keywords.append(items)

        return list(set(keywords))

    def document_keywords_to_string(self, result: Dict) -> str:
        """
        将文档关键字提取结果转为逗号分隔字符串（用于写入 metadata.csv）

        Args:
            result: extract_document_keywords() 的返回值

        Returns:
            逗号分隔的关键字字符串
        """
        all_kws = []
        for key in ["entities", "concepts", "indicators"]:
            items = result.get(key, [])
            if isinstance(items, list):
                all_kws.extend(items)
        return ",".join(all_kws)
