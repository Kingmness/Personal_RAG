# -*- coding: utf-8 -*-
"""
路由模块包
"""

from .health import router as health_router
from .documents import router as documents_router
from .query import router as query_router
from .history import router as history_router
from .admin import router as admin_router

__all__ = [
    "health_router",
    "documents_router",
    "query_router",
    "history_router",
    "admin_router",
]
