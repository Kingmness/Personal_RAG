# -*- coding: utf-8 -*-
"""
FastAPI 后端服务入口
路由已拆分到 routers/ 目录，本文件仅负责应用初始化、中间件注册和路由挂载
"""

import sys
import time
import uuid
import faulthandler
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

faulthandler.enable()

# 添加 pra 包目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import CORS_ORIGINS, API_AUTH_KEY
from logger import setup_logger
from history_store import get_history_store

_log = setup_logger(name="pra.api")


def _thread_excepthook(args):
    """线程未处理异常钩子，防止线程异常导致进程退出"""
    _log.error(
        "线程未处理异常: thread=%s, exception=%s\n%s",
        args.thread.name if args.thread else "unknown",
        args.exc_value,
        ''.join(args.exc_traceback) if args.exc_traceback else "",
    )


threading.excepthook = _thread_excepthook

from contextlib import asynccontextmanager


@asynccontextmanager
async def _lifespan(app):
    """应用生命周期：启动时安全检查"""
    if not API_AUTH_KEY:
        _log.warning("=" * 60)
        _log.warning("[安全警告] API_AUTH_KEY 未设置，所有接口无需认证！")
        _log.warning("[安全警告] 生产环境请务必在 .env 中设置 API_AUTH_KEY")
        _log.warning("=" * 60)
    yield


# ==================== 应用实例 ====================

app = FastAPI(title="PRA-RAG API", version="1.0.0", lifespan=_lifespan)

# 限流器
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== 中间件 ====================

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """API Key 认证中间件，API_AUTH_KEY 为空时不启用"""
    if API_AUTH_KEY:
        key = request.headers.get("X-API-Key", "")
        if key != API_AUTH_KEY:
            raise HTTPException(status_code=401, detail="无效或缺失 API Key")
    return await call_next(request)


@app.middleware("http")
async def trace_middleware(request: Request, call_next):
    """全链路追踪中间件：为每个请求分配 trace_id，注入日志上下文"""
    from logger import set_trace_id

    tid = request.headers.get("X-Trace-ID") or uuid.uuid4().hex[:12]
    set_trace_id(tid)

    start = time.time()
    response = await call_next(request)
    elapsed = time.time() - start

    response.headers["X-Trace-ID"] = tid

    # 低频/慢请求才输出 trace 日志，轮询和健康检查静默
    _skip_paths = {"/health", "/api/document/status", "/api/log-level", "/api/config"}
    if request.url.path not in _skip_paths or elapsed > 1.0:
        _log.info("[trace] %s %s status=%d elapsed=%.2fs trace_id=%s",
                  request.method, request.url.path, response.status_code, elapsed, tid)
    return response


# ==================== 注册路由 ====================

from routers import health_router, documents_router, query_router, history_router, admin_router

app.include_router(health_router)
app.include_router(documents_router)
app.include_router(query_router)
app.include_router(history_router)
app.include_router(admin_router)


# ==================== 服务启动 ====================

if __name__ == "__main__":
    import uvicorn
    _log.info("启动 PRA-RAG API 服务...")
    # 启动时清理一次旧记录
    try:
        store = get_history_store()
        cleanup_count = store.cleanup_old_records(days=3)
        if cleanup_count > 0:
            _log.info("启动时清理了 %d 条旧历史记录", cleanup_count)
    except Exception as e:
        _log.warning("启动时清理旧记录失败: %s", e)
    uvicorn.run(app, host="0.0.0.0", port=4000)
