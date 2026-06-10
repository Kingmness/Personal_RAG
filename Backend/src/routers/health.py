# -*- coding: utf-8 -*-
"""
健康检查与链路追踪路由
"""

from fastapi import APIRouter, HTTPException

from config import LOGS_DIR
from dependencies import get_logger

router = APIRouter()
_log = get_logger()


@router.get("/health")
def health_check():
    """健康检查端点"""
    return {"status": "ok"}


@router.get("/api/trace/{trace_id}")
def get_trace_logs(trace_id: str, limit: int = 200):
    """按 trace_id 检索完整请求链路日志"""
    log_file = LOGS_DIR / "pra.log"
    if not log_file.exists():
        return {"trace_id": trace_id, "logs": []}

    matched = []
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                if f"[{trace_id}]" in line:
                    matched.append(line.rstrip())
                    if len(matched) >= limit:
                        break
    except Exception as e:
        _log.error("读取日志文件失败: %s", e)
        raise HTTPException(status_code=500, detail="读取日志文件失败")

    return {"trace_id": trace_id, "count": len(matched), "logs": matched}
