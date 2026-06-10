# -*- coding: utf-8 -*-
"""
LLM 重排序模块
- 使用 DashScope 通义千问对检索结果进行相关性重排
- 输入：retrieval.py 的输出（带 score 的文档列表）
- 输出：LLM 相关性评分 + 检索分数加权融合后的排序结果
"""

import json
from pathlib import Path
from typing import List, Dict
import logging
import contextvars

from openai import OpenAI
from json_repair import repair_json
from config import DASHSCOPE_API_KEY, LLM_MODEL
from logger import setup_logger

_log = setup_logger(name="pra.reranking")

SYSTEM_PROMPT = """你是一个RAG检索重排专家。
你将收到一个查询和若干检索到的文本块，请分别对每个块进行相关性评分。

评分标准（0-1，步长0.1）：
  0 = 完全无关
  0.5 = 一般相关
  0.8 = 很相关
  1 = 完全匹配

严格要求：
1. 基于文本块与查询的实际内容关系客观评分，不做假设
2. 按对应顺序输出 JSON 数组，每个元素包含 block_index（从1开始）、reasoning（不超过15字）、relevance_score
3. 只输出 JSON，不要有其他文字
4. 对于列举类问题（如"有几种"、"有哪些"），如果文本块中包含与问题相关的关键信息（如列表项、要点描述、相关事实），即使不是完整的回答，也应当给至少 0.6 的分数
5. 若查询涉及多个并列要点，只要文本块中提及其中任一条，即视为"相关"，不要轻易打低分"""

class Reranker:
    """基于 DashScope 通义千问的 LLM 重排序器"""

    def __init__(self, model: str = LLM_MODEL):
        if not DASHSCOPE_API_KEY:
            raise ValueError("未找到 DASHSCOPE_API_KEY，请在 .env 文件中配置")
        self.model = model
        self.client = OpenAI(
            api_key=DASHSCOPE_API_KEY,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )

    def _score_batch(self, query: str, documents: List[Dict]) -> List[Dict]:
        """
        调用 LLM 对一批文档进行相关性评分

        Args:
            query: 用户问题
            documents: 文档列表 [{"text": "...", ...}, ...]

        Returns:
            [{"relevance_score": float, "reasoning": str}, ...]  与输入顺序一一对应
        """
        blocks_text = "\n\n---\n\n".join(
            f"Block {i+1}:\n\"\"\"\n{doc['text'][:2000]}\n\"\"\""
            for i, doc in enumerate(documents)
        )
        user_prompt = (
            f"查询：\"{query}\"\n\n"
            f"以下是检索到的 {len(documents)} 个文本块，请逐一评分：\n\n"
            f"{blocks_text}"
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        _log.info("[重排_LLM] 请求 batch, block_num=%d, model=%s",
                  len(documents), self.model)
        _log.info("[重排_LLM] 输入预览: %s", user_prompt[:500].replace('\n', ' '))

        resp = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0,
            extra_body={"enable_thinking": False},
        )

        content = resp.choices[0].message.content
        _log.info("[重排_LLM] 原始输出: %s", content[:1000].replace('\n', ' '))

        # 解析 JSON
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = json.loads(repair_json(content))

        # 兼容LLM返回 {"results": [...]} 格式
        if isinstance(parsed, dict):
            for key in ("results", "blocks", "scores", "data"):
                if key in parsed and isinstance(parsed[key], list):
                    parsed = parsed[key]
                    break
            else:
                parsed = []

        _log.info("[重排_LLM] 解析结果: %d 条", len(parsed))
        for i, p in enumerate(parsed):
            score = p.get("relevance_score", 0.0)
            reasoning = p.get("reasoning", "")
            _log.info("  [%d] score=%.2f  %s", i + 1, score, reasoning[:80])

        # 确保返回数量与输入一致
        results = []
        for i in range(len(documents)):
            if i < len(parsed):
                results.append({
                    "relevance_score": float(parsed[i].get("relevance_score", 0.0)),
                    "reasoning": parsed[i].get("reasoning", ""),
                })
            else:
                results.append({"relevance_score": 0.0, "reasoning": "LLM 未返回该块的评分"})

        return results

    @staticmethod
    def _normalize_scores(values: List[float]) -> List[float]:
        """min-max 归一化到 [0, 1]"""
        if not values:
            return []
        min_v, max_v = min(values), max(values)
        if max_v == min_v:
            return [0.5] * len(values)
        return [(v - min_v) / (max_v - min_v) for v in values]

    def rerank(
        self,
        query: str,
        documents: List[Dict],
        batch_size: int = 4,
        llm_weight: float = 0.7,
        top_n: int = 5,
    ) -> List[Dict]:
        """
        对检索结果进行 LLM 重排序

        流程：
        1. 将文档分批，每批调用 LLM 评分
        2. 检索分数与 LLM 相关性分数加权融合
        3. 按融合分数降序取 top_n

        Args:
            query:      用户问题
            documents:  检索结果列表，每个元素需包含 text、score 字段
            batch_size: 每批送入 LLM 的文档数
            llm_weight: LLM 评分权重（0~1），剩余为检索分数权重
            top_n:      最终返回数量

        Returns:
            重排后的文档列表，增加 relevance_score、combined_score 字段
        """
        if not documents:
            return []

        _log.info("[重排] 开始重排, doc_num=%d, batch_size=%d, llm_weight=%.2f, top_n=%d",
                  len(documents), batch_size, llm_weight, top_n)

        _log.info("[重排] 重排前的文档列表:")
        for i, doc in enumerate(documents):
            text_preview = doc['text'][:150].replace('\n', ' ')
            _log.info("  [%d] %s 第%d页  retrieval_score=%.4f  %s...",
                      i + 1, doc['source'][:40], doc['page'], doc['score'], text_preview)

        retrieval_weight = 1 - llm_weight

        # 分批并行调用 LLM 评分
        batches = [documents[i:i + batch_size] for i in range(0, len(documents), batch_size)]
        _log.info("[重排] 分为 %d 个 batch", len(batches))

        from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError

        RERANK_TIMEOUT = 20  # 秒

        all_llm_scores = [None] * len(batches)

        # 捕获当前上下文（含 trace_id），每个子线程复制独立副本避免重入
        parent_ctx = contextvars.copy_context()

        def _run_batch(query, batch):
            # 每个子线程使用独立的上下文副本，避免 "is already entered" 错误
            child_ctx = parent_ctx.copy()
            return child_ctx.run(self._score_batch, query, batch)

        with ThreadPoolExecutor(max_workers=min(len(batches), 4)) as executor:
            future_to_idx = {
                executor.submit(_run_batch, query, batch): idx
                for idx, batch in enumerate(batches)
            }
            try:
                for future in as_completed(future_to_idx, timeout=RERANK_TIMEOUT):
                    idx = future_to_idx[future]
                    _log.info("[重排] batch %d 完成", idx + 1)
                    all_llm_scores[idx] = future.result()
            except FuturesTimeoutError:
                _log.warning("[重排] 部分批次超时（%ds），将降级为检索分数", RERANK_TIMEOUT)

        # 超时降级：未完成的 batch 使用默认分数
        for i, scores in enumerate(all_llm_scores):
            if scores is None:
                _log.warning("[重排] batch %d 超时，降级为检索分数", i + 1)
                all_llm_scores[i] = [
                    {"relevance_score": 0.5, "reasoning": "LLM 评分超时，降级"}
                    for _ in batches[i]
                ]

        # 展平为一维列表
        all_llm_scores = [score for batch_scores in all_llm_scores for score in batch_scores]

        # 检索分数归一化
        retrieval_scores = [doc["score"] for doc in documents]
        norm_retrieval = self._normalize_scores(retrieval_scores)

        # 加权融合
        _log.info("[重排] 融合前各文档分数:")
        for i, doc in enumerate(documents):
            _log.info("  [%d] 检索分=%.4f  LLM分=%.2f  检索归一化=%.4f",
                      i + 1, retrieval_scores[i], all_llm_scores[i]["relevance_score"],
                      norm_retrieval[i])

        for i, doc in enumerate(documents):
            doc["relevance_score"] = all_llm_scores[i]["relevance_score"]
            doc["reasoning"] = all_llm_scores[i]["reasoning"]
            doc["combined_score"] = round(
                llm_weight * all_llm_scores[i]["relevance_score"]
                + retrieval_weight * norm_retrieval[i],
                4,
            )

        _log.info("[重排] 融合后:")
        for i, doc in enumerate(documents):
            _log.info("  [%d] combined=%.4f  relevance=%.2f 检索分=%.4f  %s",
                      i + 1, doc["combined_score"], doc["relevance_score"],
                      retrieval_scores[i], doc.get("reasoning", "")[:80])

        # 按融合分数降序
        documents.sort(key=lambda x: x["combined_score"], reverse=True)
        _log.info("[重排] 排序后保留 top%d", top_n)
        for i, doc in enumerate(documents[:top_n]):
            _log.info("  [%d] %s 第%d页  combined=%.4f  %s",
                      i + 1, doc['source'][:30], doc['page'],
                      doc['combined_score'], doc.get('reasoning', '')[:60])
        return documents[:top_n]

