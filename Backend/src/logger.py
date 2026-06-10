# -*- coding: utf-8 -*-
"""
日志系统
提供统一的日志配置，替代各模块中的 print 调用。
支持控制台输出和文件日志（带轮转）。
支持全链路追踪：通过 contextvars 在日志中携带 trace_id。

架构：根 logger 统一配置 handler 和 filter，子 logger 通过 propagate 传播到根 logger，
避免每个子 logger 独立配置导致日志丢失或重复。
"""

import sys
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional
from contextvars import ContextVar

from config import LOGS_DIR, LOG_LEVEL

# 将 LOG_LEVEL 字符串转为 logging 级别常量
_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}
DEFAULT_LOG_LEVEL = _LEVEL_MAP.get(LOG_LEVEL, logging.INFO)

# 全链路追踪：当前请求的 trace_id
_trace_id: ContextVar[str] = ContextVar("trace_id", default="-")


def set_trace_id(tid: str) -> None:
    """设置当前请求的 trace_id"""
    _trace_id.set(tid)


def get_trace_id() -> str:
    """获取当前请求的 trace_id"""
    return _trace_id.get()


class TraceFilter(logging.Filter):
    """日志过滤器，在每条日志中注入 trace_id"""
    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = _trace_id.get()
        return True


def _clean_old_logs(log_dir: Path, max_age_days: int = 7):
    """清理超过 max_age_days 天的旧日志文件（含轮转备份）"""
    if not log_dir.exists():
        return
    import time
    now = time.time()
    for f in log_dir.iterdir():
        if not f.is_file():
            continue
        if not (f.suffix == ".log" or f.name.startswith("pra.log")):
            continue
        if (now - f.stat().st_mtime) > max_age_days * 86400:
            try:
                f.unlink()
            except OSError:
                pass


# 全局标记：根 logger 是否已初始化
_root_initialized = False


def _init_root_logger(log_dir: Optional[Path] = None, level: Optional[int] = None):
    """初始化根 logger，统一配置 handler 和 filter（只执行一次）"""
    global _root_initialized
    if _root_initialized:
        return
    _root_initialized = True

    if level is None:
        level = DEFAULT_LOG_LEVEL

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)  # 根 logger 设为最低，由 handler 控制级别

    # 注入 trace_id
    root.addFilter(TraceFilter())

    # 日志格式（含 trace_id）
    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(trace_id)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台输出
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(fmt)
    console_handler.addFilter(TraceFilter())
    root.addHandler(console_handler)

    # 文件输出（轮转）
    if log_dir is None:
        log_dir = LOGS_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    _clean_old_logs(log_dir, max_age_days=7)

    log_file = log_dir / "pra.log"
    file_handler = RotatingFileHandler(
        str(log_file),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    file_handler.addFilter(TraceFilter())
    root.addHandler(file_handler)

    # 第三方库日志级别设为 WARNING，避免 openai/httpcore/dashscope 等刷屏
    _THIRD_PARTY_LOGGERS = [
        "openai", "httpx", "httpcore", "urllib3", "dashscope",
        "multipart", "watchfiles", "anyio", "hpack",
    ]
    for name in _THIRD_PARTY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def setup_logger(
    name: str = "src",
    log_dir: Optional[Path] = None,
    level: Optional[int] = None,
    log_to_file: bool = True,
) -> logging.Logger:
    """
    创建并配置一个 logger 实例

    子 logger 不再添加独立 handler，而是通过 propagate 传播到根 logger。
    根 logger 统一管理 handler、filter 和格式。

    Args:
        name:        logger 名称
        log_dir:     日志文件输出目录（仅首次初始化根 logger 时使用）
        level:       日志级别（仅首次初始化根 logger 时使用）
        log_to_file: 是否同时输出到文件（仅首次初始化根 logger 时使用）

    Returns:
        配置好的 Logger 实例
    """
    # 确保根 logger 已初始化
    _init_root_logger(log_dir=log_dir, level=level)

    logger = logging.getLogger(name)

    # 子 logger 不添加独立 handler，通过 propagate 传播到根 logger
    logger.propagate = True
    # 子 logger 不设独立级别，继承根 logger
    logger.setLevel(logging.DEBUG)

    return logger


# 默认全局 logger
_log = setup_logger(name="src")


def set_log_level(level_name: str) -> str:
    """
    运行时动态调整所有已注册 logger 的日志级别

    Args:
        level_name: 日志级别名称 (DEBUG/INFO/WARNING/ERROR/CRITICAL)

    Returns:
        设置后的级别名称
    """
    level_name = level_name.upper()
    level = _LEVEL_MAP.get(level_name)
    if level is None:
        raise ValueError(f"无效的日志级别: {level_name}，可选: {list(_LEVEL_MAP.keys())}")

    # 调整根 logger 的控制台 handler 级别
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, RotatingFileHandler):
            continue  # 文件 handler 保持 DEBUG
        handler.setLevel(level)

    _log.info("[日志] 日志级别已调整为: %s", level_name)
    return level_name


def get_log_level() -> str:
    """获取当前日志级别名称"""
    # 从根 logger 的控制台 handler 获取实际生效的级别
    root = logging.getLogger()
    for handler in root.handlers:
        if not isinstance(handler, RotatingFileHandler):
            level = handler.level
            for name, val in _LEVEL_MAP.items():
                if val == level:
                    return name
    return "UNKNOWN"
