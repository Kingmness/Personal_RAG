# -*- coding: utf-8 -*-
"""
全局依赖注入：共享状态和工具函数
各路由模块通过 FastAPI Depends 获取这些依赖
"""

import asyncio
import threading
from typing import Optional

from pipeline import Pipeline
from metadata import MetadataManager
from logger import setup_logger

_log = setup_logger(name="pra.api")

# Pipeline 单例（双重检查锁定，线程安全）
_pipeline_lock = threading.Lock()
_pipeline: Optional[Pipeline] = None

# 异步写锁，防止索引构建等操作并发冲突
_write_lock = asyncio.Lock()

# 元数据管理器单例
_metadata_manager = MetadataManager()


def get_pipeline() -> Pipeline:
    """获取 Pipeline 单例"""
    global _pipeline
    if _pipeline is None:
        with _pipeline_lock:
            if _pipeline is None:
                _pipeline = Pipeline()
    return _pipeline


def get_write_lock() -> asyncio.Lock:
    """获取异步写锁"""
    return _write_lock


def get_metadata_manager() -> MetadataManager:
    """获取元数据管理器"""
    return _metadata_manager


def get_logger():
    """获取 API 日志器"""
    return _log


def apply_config_to_pipeline(config_values: dict):
    """将配置值同步更新到运行中的 Pipeline，使配置立即生效"""
    pl = get_pipeline()
    if pl is None:
        return
    cfg = pl.config
    # key 到 RunConfig 属性名的映射
    key_to_attr = {
        "chunk_size": "chunk_size",
        "chunk_overlap": "chunk_overlap",
        "route_top_k": "route_top_k",
        "faiss_top_n": "faiss_top_n",
        "bm25_top_n": "bm25_top_n",
        "hybrid_top_n": "retrieve_top_n",
        "faiss_weight": "faiss_weight",
        "bm25_weight": "bm25_weight",
        "keyword_filter_enabled": "keyword_filter_enabled",
        "keyword_bonus_per_match": "keyword_bonus_per_match",
        "keyword_use_llm": "keyword_use_llm",
        "keyword_sample_chunks": "keyword_sample_chunks",
        "rerank_batch_size": "rerank_batch_size",
        "rerank_top_n": "rerank_top_n",
        "llm_weight": "llm_weight",
    }
    for key, attr in key_to_attr.items():
        if key in config_values:
            setattr(cfg, attr, config_values[key])
    # 非 Pipeline 配置：直接更新 config 模块全局变量
    import config as _cfg
    if "max_backups" in config_values:
        _cfg.MAX_BACKUPS = config_values["max_backups"]
    _log.info("运行中配置已更新: %s", config_values)
