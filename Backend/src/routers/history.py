# -*- coding: utf-8 -*-
"""
历史记录路由：查询、保存、删除、清空、清理
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from typing import List

from history_store import get_history_store, QueryHistory
from dependencies import get_logger

router = APIRouter()
_log = get_logger()


# ==================== 请求模型 ====================

class SaveHistoryRequest(BaseModel):
    question: str = Field(..., min_length=1)
    answer_type: str = "text"
    answer: str = ""
    sources: List[str] = Field(default_factory=list)
    elapsed: float = 0.0


# ==================== 端点 ====================

@router.get("/api/history")
def get_history(limit: int = 100, offset: int = 0):
    """获取查询历史记录"""
    try:
        store = get_history_store()
        records = store.get_records(limit=limit, offset=offset)
        return {"records": [store.to_dict(r) for r in records]}
    except Exception as e:
        _log.error("获取历史记录失败: %s", e)
        raise HTTPException(status_code=500, detail="获取历史记录失败")


@router.post("/api/history")
def save_history(request: Request, body: SaveHistoryRequest):
    """保存查询历史记录"""
    try:
        store = get_history_store()
        record = QueryHistory(
            question=body.question,
            answer_type=body.answer_type,
            answer=body.answer,
            sources=body.sources or [],
            elapsed=body.elapsed
        )
        record_id = store.add_record(record)
        return {"id": record_id, "message": "保存成功"}
    except Exception as e:
        _log.error("保存历史记录失败: %s", e)
        raise HTTPException(status_code=500, detail="保存历史记录失败")


@router.delete("/api/history/{record_id}")
def delete_history(request: Request, record_id: int):
    """删除一条历史记录"""
    try:
        store = get_history_store()
        success = store.delete_record(record_id)
        if not success:
            raise HTTPException(status_code=404, detail="记录不存在")
        return {"message": "删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        _log.error("删除历史记录失败: %s", e)
        raise HTTPException(status_code=500, detail="删除历史记录失败")


@router.delete("/api/history")
def clear_all_history(request: Request):
    """清空所有历史记录"""
    try:
        store = get_history_store()
        count = store.clear_all()
        return {"message": f"清空成功，删除了 {count} 条记录"}
    except Exception as e:
        _log.error("清空历史记录失败: %s", e)
        raise HTTPException(status_code=500, detail="清空历史记录失败")


@router.post("/api/history/cleanup")
def cleanup_old_history(request: Request, days: int = 3):
    """清理旧的历史记录"""
    try:
        store = get_history_store()
        count = store.cleanup_old_records(days=days)
        return {"message": f"清理成功，删除了 {count} 条记录"}
    except Exception as e:
        _log.error("清理旧记录失败: %s", e)
        raise HTTPException(status_code=500, detail="清理旧记录失败")
