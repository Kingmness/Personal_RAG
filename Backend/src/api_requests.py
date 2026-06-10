# -*- coding: utf-8 -*-
"""
LLM API 客户端
- 使用 DashScope 通义千问，通过 OpenAI 兼容接口调用
- 提供 chat、chat_json、chat_stream 和 answer_with_context 四个核心方法
"""

import json
from typing import Optional, Dict, Generator

from openai import OpenAI
from json_repair import repair_json

import prompts
from config import DASHSCOPE_API_KEY, LLM_MODEL


class LLMClient:
    """封装 DashScope 通义千问的 LLM 调用"""

    def __init__(self, model: str = LLM_MODEL):
        if not DASHSCOPE_API_KEY:
            raise ValueError("未找到 DASHSCOPE_API_KEY，请在 .env 文件中配置")
        self.model = model
        self.client = OpenAI(
            api_key=DASHSCOPE_API_KEY,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )

    def chat(
        self,
        system_content: str,
        user_content: str,
        temperature: float = 0,
    ) -> str:
        """
        发送对话消息，返回 LLM 回复文本

        Args:
            system_content: 系统 Prompt
            user_content:   用户消息
            temperature:    采样温度

        Returns:
            LLM 回复的完整文本
        """
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
            ],
            temperature=temperature,
            extra_body={"enable_thinking": False},
        )
        return resp.choices[0].message.content

    def chat_json(
        self,
        system_content: str,
        user_content: str,
        temperature: float = 0,
    ) -> str:
        """
        发送对话消息并强制 JSON 输出

        Args:
            system_content: 系统 Prompt
            user_content:   用户消息
            temperature:    采样温度

        Returns:
            LLM 回复的 JSON 字符串
        """
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
            ],
            temperature=temperature,
            response_format={"type": "json_object"},
            extra_body={"enable_thinking": False},
        )
        return resp.choices[0].message.content

    def chat_stream(
        self,
        system_content: str,
        user_content: str,
        temperature: float = 0,
    ) -> Generator[str, None, None]:
        """
        流式发送对话消息，逐 token 返回 LLM 回复

        Args:
            system_content: 系统 Prompt
            user_content:   用户消息
            temperature:    采样温度

        Yields:
            LLM 回复的文本片段（逐 token）
        """
        stream = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
            ],
            temperature=temperature,
            stream=True,
            extra_body={"enable_thinking": False},
        )
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content

    def answer_with_context(
        self,
        question: str,
        context: str,
        prompt_type: str = "number",
    ) -> Dict:
        """
        基于检索上下文回答问题

        Args:
            question:    用户问题
            context:     检索到的 RAG 上下文字符串
            prompt_type: 答案类型：number/name/boolean/list

        Returns:
            {
                "step_by_step_analysis": str,
                "reasoning_summary": str,
                "relevant_pages": list[int],
                "final_answer": any,
            }
        """
        prompt_config = prompts.build_answer_prompt(prompt_type)
        system_content = prompt_config["system"]
        user_content = prompts.build_user_prompt(question, context)

        raw = self.chat_json(system_content, user_content)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = json.loads(repair_json(raw))

        return parsed