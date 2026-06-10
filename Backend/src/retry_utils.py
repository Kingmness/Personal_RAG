# -*- coding: utf-8 -*-
"""
API 重试工具
提供带指数退避的 API 调用重试，替代各模块中重复的重试逻辑。
"""

import time
from typing import Callable, TypeVar, Set

from dashscope import MultiModalEmbedding

from config import MAX_RETRIES, RETRY_BASE_DELAY, RETRYABLE_STATUS_CODES
from logger import setup_logger

_log = setup_logger(name="pra.retry")

T = TypeVar("T")


def retry_embedding_call(
    call_fn: Callable[[], MultiModalEmbedding],
    max_retries: int = MAX_RETRIES,
    base_delay: float = RETRY_BASE_DELAY,
    retryable_codes: Set[int] = RETRYABLE_STATUS_CODES,
) -> MultiModalEmbedding:
    """
    带指数退避的 DashScope Embedding API 调用重试

    Args:
        call_fn:        调用 DashScope API 的无参函数，返回响应对象
        max_retries:    最大重试次数
        base_delay:     重试基础等待时间（秒），指数退避
        retryable_codes: 可重试的 HTTP 状态码集合

    Returns:
        成功的 API 响应对象

    Raises:
        RuntimeError: 重试次数耗尽或遇到不可重试错误
    """
    last_error = None
    for attempt in range(max_retries + 1):
        resp = call_fn()
        if resp.status_code == 200:
            return resp

        last_error = resp
        if resp.status_code not in retryable_codes:
            raise RuntimeError(
                f"嵌入 API 返回不可重试错误 (status={resp.status_code}): {resp.message}"
            )
        if attempt < max_retries:
            delay = base_delay * (2 ** attempt)
            _log.warning("[重试] 嵌入 API 返回 %s, 第 %d/%d 次重试, 等待 %.0fs...",
                         resp.status_code, attempt + 1, max_retries, delay)
            time.sleep(delay)
        else:
            raise RuntimeError(
                f"嵌入 API 重试 {max_retries} 次后仍失败 (status={resp.status_code}): {resp.message}"
            )

    if last_error and resp.status_code != 200:
        raise RuntimeError(f"嵌入失败: {last_error.message}")
    return resp
