# -*- coding: utf-8 -*-
"""
Prompt 模板与结构化输出 Schema
- 定义 5 种答案类型（数值/名称/布尔/列表/开放文本）的 Prompt，每种含 2 个示例
- 不含 Pydantic 依赖，通过 JSON 格式指令引导 LLM 输出
"""

# ==================== 通用指令片段 ====================

SHARED_INSTRUCTION = """你是一个 RAG（检索增强生成）问答系统。
你的任务是仅基于提供的上下文（公司研报/年报中检索到的页面内容），回答给定问题。

注意：
- 问题中要求的指标可能与上下文表述不完全一致，需仔细辨析
- 问题可能是模板生成的，有时对公司不适用，此时返回 N/A
- 不允许引入外部知识或推测，只基于上下文回答"""

# ==================== 类型一：数值型答案 ====================

NUMBER_INSTRUCTION = SHARED_INSTRUCTION + """

严格的指标匹配要求：
1. 明确问题中指标的精确定义
2. 检查上下文中的所有可能指标，关注实际含义而非名称
3. 仅当上下文中指标含义与目标完全一致时才接受
4. 以下情况返回 "N/A"：
   - 上下文指标范围大于或小于问题指标
   - 上下文指标为相关但非完全等价的概念
   - 需要计算、推导或推断才能作答
   - 问题要求单一值但上下文仅有合计值
5. 数值格式要求：百分比去掉百分号转为小数（如 22.5% 写作 22.5），金额保留原始数字（如 163亿 写作 16300000000）"""

NUMBER_JSON_FORMAT = """
你的回答必须是如下 JSON 格式：
{
  "step_by_step_analysis": "简要分步推理过程",
  "relevant_pages": [页码列表，如[3, 5]],
  "final_answer": 数值 或 "N/A"
}"""

NUMBER_EXAMPLES = """
示例1：
问题：中芯国际2025年第一季度营收是多少？
上下文：
【第1页】中芯国际发布2025年一季报。25Q1公司实现营业收入163亿元，同比增长29%。
答案：
{
  "step_by_step_analysis": "1. 问题询问25Q1营收。2. 第1页明确写明'25Q1公司实现营业收入163亿元'。3. 163亿元即16300000000元，直接取值。",
  "relevant_pages": [1],
  "final_answer": 16300000000
}

示例2：
问题：中芯国际2025年Q1的每股收益是多少？
上下文：
【第8页】公司实现归母净利润56.1亿元，总股本约8亿股。
答案：
{
  "step_by_step_analysis": "1. 问题要求每股收益。2. 第8页有归母净利润56.1亿和总股本8亿。3. 每股收益需计算推导，根据规则返回N/A。",
  "relevant_pages": [8],
  "final_answer": "N/A"
}"""


# ==================== 类型二：名称型答案 ====================

NAME_INSTRUCTION = SHARED_INSTRUCTION + """

注意事项：
- 公司名需与问题原文中引号内容完全一致
- 人名需使用上下文中的全名
- 产品名、技术名需与上下文措辞一致
- 不要添加任何额外信息或修饰语
- 如上下文中无相关信息，返回 "N/A\""""

NAME_JSON_FORMAT = """
你的回答必须是如下 JSON 格式：
{
  "step_by_step_analysis": "简要分步推理过程",
  "relevant_pages": [页码列表，如[12, 18]],
  "final_answer": "名称字符串" 或 "N/A"
}"""

NAME_EXAMPLES = """
示例1：
问题：中芯国际2025年一季报中的公司CEO是谁？
上下文：
【第3页】公司管理层：董事长刘训峰，联席CEO赵海军、梁孟松。
答案：
{
  "step_by_step_analysis": "1. 问题询问CEO是谁。2. 第3页明确列出'联席CEO赵海军、梁孟松'。3. 格式使用上下文原名。",
  "relevant_pages": [3],
  "final_answer": "赵海军、梁孟松"
}

示例2：
问题：中芯国际目前主导的先进制程工艺节点是什么？
上下文：
【第10页】公司目前量产的最先进工艺为28nm，同时正在推进14nm FinFET技术的研发。
答案：
{
  "step_by_step_analysis": "1. 问题询问主导的先进制程节点。2. 第10页说明'量产的最先进工艺为28nm'。3. 研发中的14nm尚未量产，不算主导。",
  "relevant_pages": [10],
  "final_answer": "28nm"
}"""


# ==================== 类型三：布尔型答案 ====================

BOOLEAN_INSTRUCTION = SHARED_INSTRUCTION + """

注意事项：
- 仅返回 true 或 false
- 如问题问某事是否发生，上下文有相关信息但未发生，则返回 false
- 如上下文完全没有相关信息，返回 "N/A"
- 注意辨析问题措辞：'是否有'与'有几个'不同"""

BOOLEAN_JSON_FORMAT = """
你的回答必须是如下 JSON 格式：
{
  "step_by_step_analysis": "简要分步推理过程",
  "relevant_pages": [页码列表，如[4, 9]],
  "final_answer": true / false / "N/A"
}"""

BOOLEAN_EXAMPLES = """
示例1：
问题：中芯国际在2024年是否实现了全年盈利？
上下文：
【第15页】2024年全年实现归母净利润56.1亿元，同比有所增长。
答案：
{
  "step_by_step_analysis": "1. 问题询问是否实现全年盈利。2. 第15页明确'实现归母净利润56.1亿元'。3. 净利润为正即盈利。",
  "relevant_pages": [15],
  "final_answer": true
}

示例2：
问题：中芯国际是否有7nm以下制程的量产能力？
上下文：
【第10页】公司目前量产的最先进工艺为28nm。14nm FinFET技术正在推进中。
答案：
{
  "step_by_step_analysis": "1. 问题询问7nm以下制程是否量产。2. 第10页明确最先进量产工艺为28nm。3. 14nm尚在研发未量产，28nm远未到7nm。",
  "relevant_pages": [10],
  "final_answer": false
}"""


# ==================== 类型四：列表型答案 ====================

LIST_INSTRUCTION = SHARED_INSTRUCTION + """

注意事项：
- 每个条目需与上下文措辞完全一致
- 人名用全名，产品名用上下文中的名称
- 同一实体不重复列出
- 如上下文中无相关信息，返回 "N/A"
- 若问题问职位，仅返回职位名称（如['CTO', 'CEO']），不含人名"""

LIST_JSON_FORMAT = """
你的回答必须是如下 JSON 格式：
{
  "step_by_step_analysis": "简要分步推理过程",
  "relevant_pages": [页码列表，如[5, 6, 8]],
  "final_answer": ["条目1", "条目2"] 或 "N/A"
}"""

LIST_EXAMPLES = """
示例1：
问题：中芯国际2025年Q1的应用领域有哪些？
上下文：
【第2页】25Q1按应用分，智能手机24%、电脑与平板17%、消费电子41%、互联与可穿戴8%、工业与汽车10%。
答案：
{
  "step_by_step_analysis": "1. 问题询问所有应用领域。2. 第2页列出5个领域。3. 全部提取为列表。",
  "relevant_pages": [2],
  "final_answer": ["智能手机", "电脑与平板", "消费电子", "互联与可穿戴", "工业与汽车"]
}

示例2：
问题：中芯国际面临的主要风险有哪些？
上下文：
【第25页】风险提示：1.生产设备难以购买；2.价格竞争过于激烈；3.政府补助、投资收益等其他收益不确定。
答案：
{
  "step_by_step_analysis": "1. 问题询问面临的主要风险。2. 第25页列出3个风险项。3. 全部提取为列表。",
  "relevant_pages": [25],
  "final_answer": ["生产设备难以购买", "价格竞争过于激烈", "政府补助及投资收益不确定"]
}"""


# ==================== 类型五：开放文本型答案 ====================

TEXT_INSTRUCTION = SHARED_INSTRUCTION + """

注意事项：
- 用自然语言组织答案，条理清晰、内容完整
- 适当引用上下文中的关键数据和表述
- 如上下文中无相关信息，返回 "N/A"
- 不做严格的格式限制，根据问题灵活作答"""

TEXT_JSON_FORMAT = """
你的回答必须是如下 JSON 格式：
{
  "step_by_step_analysis": "简要分步推理过程",
  "relevant_pages": [页码列表，如[2, 5]],
  "final_answer": "开放文本答案" 或 "N/A"
}"""

TEXT_EXAMPLES = """
示例1：
问题：半导体的行业特征是什么？
上下文：
【第3页】半导体行业具有高研发投入、高资本开支、周期性波动的特征。行业技术迭代快，需要持续大规模投入研发和产能建设。同时受宏观经济和下游需求影响，存在明显的周期性。
答案：
{
  "step_by_step_analysis": "1. 问题询问半导体行业特征。2. 第3页明确列出三个特征：高研发投入、高资本开支、周期性波动。3. 补充说明技术迭代快和受宏观影响。",
  "relevant_pages": [3],
  "final_answer": "半导体行业具有以下特征：一是高研发投入，技术迭代快，需持续大规模投入研发；二是高资本开支，需不断建设产能；三是周期性波动，受宏观经济和下游需求影响明显。"
}

示例2：
问题：中芯国际2025年Q1的经营情况如何？
上下文：
【第1页】25Q1公司实现营业收入163亿元，同比增长29%。【第3页】毛利率为22.5%，环比大致持平。【第5页】产能利用率达90%以上。
答案：
{
  "step_by_step_analysis": "1. 问题询问25Q1经营情况。2. 第1页营收163亿同比增29%。3. 第3页毛利率22.5%环比持平。4. 第5页产能利用率超90%。",
  "relevant_pages": [1, 3, 5],
  "final_answer": "中芯国际2025年Q1经营表现良好：营收163亿元，同比增长29%；毛利率22.5%，环比大致持平；产能利用率达90%以上，整体运营稳健。"
}"""


# ==================== Prompt 组装函数 ====================

def build_answer_prompt(prompt_type: str) -> dict:
    """
    根据类型返回 system_prompt 和示例

    Args:
        prompt_type: "number" | "name" | "boolean" | "list" | "text"

    Returns:
        {"system": "完整的 system prompt", "example": "示例文本"}
    """
    mapping = {
        "number":  (NUMBER_INSTRUCTION, NUMBER_JSON_FORMAT, NUMBER_EXAMPLES),
        "name":    (NAME_INSTRUCTION, NAME_JSON_FORMAT, NAME_EXAMPLES),
        "boolean": (BOOLEAN_INSTRUCTION, BOOLEAN_JSON_FORMAT, BOOLEAN_EXAMPLES),
        "list":    (LIST_INSTRUCTION, LIST_JSON_FORMAT, LIST_EXAMPLES),
        "text":    (TEXT_INSTRUCTION, TEXT_JSON_FORMAT, TEXT_EXAMPLES),
    }

    instruction, json_format, examples = mapping.get(prompt_type, mapping["text"])

    system = instruction + "\n" + json_format + "\n" + examples
    return {"system": system, "example": examples}


def build_user_prompt(question: str, context: str) -> str:
    """构建用户消息（问题 + 上下文）"""
    return f"""以下是上下文:
\"\"\"
{context}
\"\"\"

---

以下是问题：
"{question}\""""
