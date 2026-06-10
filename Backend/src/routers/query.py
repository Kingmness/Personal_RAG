# -*- coding: utf-8 -*-
"""
查询路由：检索、问答、流式问答
"""

import json
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from dependencies import get_pipeline, get_logger

router = APIRouter()
_log = get_logger()


# ==================== 请求模型 ====================

class RetrieveRequest(BaseModel):
    question: str = Field(..., min_length=1)
    company: str = ""
    top_n: int = Field(default=5, ge=1, le=50)


class AnswerRequest(BaseModel):
    question: str = Field(..., min_length=1)
    type: str = "number"
    company: str = ""
    use_rerank: bool = True
    top_n: int = Field(default=5, ge=1, le=50)


# ==================== 端点 ====================

@router.post("/api/retrieve")
def retrieve(request: Request, body: RetrieveRequest):
    """检索文档片段"""
    start_time = time.time()
    try:
        pl = get_pipeline()
        processor = pl.question_processor

        docs = processor.retriever.retrieve(body.question, hybrid_top_n=body.top_n)
        elapsed = time.time() - start_time
        return {"chunks": docs, "elapsed": elapsed}
    except Exception as e:
        _log.error("检索失败: %s", e)
        raise HTTPException(status_code=500, detail="检索失败，请稍后重试")


@router.post("/api/answer")
def answer(request: Request, body: AnswerRequest):
    """完整问答流程"""
    start_time = time.time()
    try:
        pl = get_pipeline()

        result = pl.answer_question(
            question=body.question,
            prompt_type=body.type
        )

        elapsed = time.time() - start_time
        return {
            "answer": str(result.get("final_answer", "")),
            "pages": result.get("relevant_pages", []),
            "sources": list(set(doc["source"] for doc in result.get("context_docs", []))),
            "chunks": result.get("context_docs", []),
            "elapsed": elapsed
        }
    except Exception as e:
        _log.error("问答失败: %s", e)
        raise HTTPException(status_code=500, detail="问答失败，请稍后重试")


@router.post("/api/answer/stream")
async def answer_stream(request: Request, body: AnswerRequest):
    """流式问答接口，使用 SSE 逐步推送进度和 LLM 输出"""
    start_time = time.time()

    # 在主线程中获取 trace_id，供子线程闭包使用
    from logger import get_trace_id as _get_tid
    current_tid = _get_tid()

    def event_generator():
        # StreamingResponse 在线程池中执行，需要手动传播 trace_id
        from logger import set_trace_id as _set_tid
        _set_tid(current_tid)
        try:
            pl = get_pipeline()
            processor = pl.question_processor

            for event in processor.answer_stream(
                question=body.question,
                prompt_type=body.type,
                route_top_k=pl.config.route_top_k,
                retrieve_top_n=pl.config.retrieve_top_n,
                rerank_batch_size=pl.config.rerank_batch_size,
                rerank_top_n=pl.config.rerank_top_n,
                llm_weight=pl.config.llm_weight,
            ):
                if event["type"] == "result":
                    event["data"]["elapsed"] = round(time.time() - start_time, 2)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        except Exception as e:
            _log.error("流式问答失败: %s", e)
            error_msg = str(e)
            if "403" in error_msg or "AllocationQuota" in error_msg:
                friendly_msg = "LLM API 额度不足，请联系管理员"
            elif "429" in error_msg:
                friendly_msg = "请求过于频繁，请稍后重试"
            else:
                friendly_msg = "问答服务暂时不可用"
            error_event = {"type": "error", "message": friendly_msg}
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
