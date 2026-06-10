# -*- coding: utf-8 -*-
"""
统一配置管理
集中管理所有常量、模型名、分块参数、检索参数等。
支持 .env 环境变量 + 类属性三级覆盖机制。
"""

import os
import json
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Dict, Any, List

from dotenv import load_dotenv, dotenv_values

_PROJECT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_DIR / ".env")


# ==================== 项目路径 ====================

PROJECT_ROOT = _PROJECT_DIR

# 数据目录
PDF_DATA_DIR = PROJECT_ROOT / "data" / "pdf_data"
PARSED_MD_DIR = PROJECT_ROOT / "data" / "parsed_md"
CHUNKED_JSON_DIR = PROJECT_ROOT / "data" / "chunked_json"
FAISS_INDEX_DIR = PROJECT_ROOT / "data" / "faiss_index"
BM25_INDEX_DIR = PROJECT_ROOT / "data" / "bm25_index"
LOGS_DIR = PROJECT_ROOT / "logs"
METADATA_FILE = PROJECT_ROOT / "metadata.csv"
METADATA_DB = Path(__file__).resolve().parent / "metadata.db"
CONFIG_OVERRIDES_FILE = PROJECT_ROOT / "data" / "config_overrides.json"

# 加载配置覆盖（最高优先级）
_config_overrides: Dict[str, Any] = {}
if CONFIG_OVERRIDES_FILE.exists():
    try:
        with open(CONFIG_OVERRIDES_FILE, "r", encoding="utf-8") as f:
            _config_overrides = json.load(f)
    except Exception as e:
        # 加载失败时忽略，使用默认值
        pass


# ==================== 可配置项 Schema ====================

@dataclass
class ConfigItem:
    """配置项定义"""
    key: str
    label: str
    type: str
    default: Any
    min: Optional[float] = None
    max: Optional[float] = None
    description: str = ""


# 可配置项定义（默认值单一来源，_get_config 和 config_manager 都从这里取）
CONFIG_SCHEMA: List[ConfigItem] = [
    # 分块参数
    ConfigItem("chunk_size", "分块大小", "int", 300, 100, 2000, "单个文本块的 token 数"),
    ConfigItem("chunk_overlap", "分块重叠", "int", 50, 0, 500, "相邻文本块的重叠 token 数"),
    # 检索参数
    ConfigItem("route_top_k", "路由匹配数量", "int", 3, 1, 10, "关键字匹配的文档库数量"),
    ConfigItem("faiss_top_n", "FAISS 检索数量", "int", 30, 5, 100, "向量检索返回的块数量"),
    ConfigItem("bm25_top_n", "BM25 检索数量", "int", 30, 5, 100, "关键词检索返回的块数量"),
    ConfigItem("hybrid_top_n", "混合检索数量", "int", 8, 1, 30, "混合检索后保留的块数量"),
    ConfigItem("faiss_weight", "FAISS 权重", "float", 0.6, 0, 1, "向量检索结果的权重"),
    ConfigItem("bm25_weight", "BM25 权重", "float", 0.4, 0, 1, "关键词检索结果的权重"),
    # 关键字过滤
    ConfigItem("keyword_filter_enabled", "启用关键字过滤", "bool", True, description="是否启用关键字+向量混合路由"),
    ConfigItem("keyword_bonus_per_match", "关键字加分系数", "float", 0.1, 0, 2, "每个匹配关键字的加分"),
    ConfigItem("keyword_use_llm", "LLM 提取关键字", "bool", True, description="索引构建时是否使用 LLM 提取文档关键字"),
    ConfigItem("keyword_sample_chunks", "关键字采样块数", "int", 3, 1, 10, "文档关键字提取时使用的 chunk 数量"),
    # 重排参数
    ConfigItem("rerank_batch_size", "重排批次大小", "int", 8, 1, 32, "一次重排处理的块数量"),
    ConfigItem("rerank_top_n", "重排保留数量", "int", 5, 1, 20, "重排后保留的块数量"),
    ConfigItem("llm_weight", "LLM 重排权重", "float", 0.7, 0, 1, "LLM 重排结果的权重（0-1）"),
    # 系统配置
    ConfigItem("max_backups", "配置备份保留数", "int", 5, 1, 20, "配置修改历史最多保留的备份数量"),
]

# key -> ConfigItem 快速查找
CONFIG_ITEM_MAP: Dict[str, ConfigItem] = {item.key: item for item in CONFIG_SCHEMA}


# 辅助函数：获取覆盖值，无则从 CONFIG_SCHEMA 取默认值
def _get_config(key: str, default: Any = None) -> Any:
    if key in _config_overrides:
        return _config_overrides[key]
    # 从 schema 取默认值
    item = CONFIG_ITEM_MAP.get(key)
    if item is not None:
        return item.default
    # 兜底：使用传入的 default
    return default


# ==================== API 配置 ====================

# 通义千问 Embedding 模型
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "tongyi-embedding-vision-flash-2026-03-06")

# LLM 对话模型
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3.6-plus-2026-04-02")

# API Key 只从 .env 文件读取，不读取系统环境变量
_dotenv_vals = dotenv_values(_PROJECT_DIR / ".env")

# DashScope API Key
DASHSCOPE_API_KEY = _dotenv_vals.get("DASHSCOPE_API_KEY")

# MinerU API Key
MINERU_KEY = _dotenv_vals.get("MINERU_KEY")

# MinerU 轮询配置
MINERU_POLL_INTERVAL = int(os.getenv("MINERU_POLL_INTERVAL", "5"))
MINERU_POLL_MAX_RETRIES = int(os.getenv("MINERU_POLL_MAX_RETRIES", "200"))

# CORS 允许的前端域名（逗号分隔）
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000,http://localhost:4000").split(",")

# API 认证密钥（为空则不启用认证）
API_AUTH_KEY = os.getenv("API_AUTH_KEY", "")

# 日志级别（DEBUG/INFO/WARNING/ERROR/CRITICAL）
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


# ==================== API 重试配置 ====================

# 最大重试次数
MAX_RETRIES = 3

# 重试基础等待时间（秒），指数退避：1s / 2s / 4s
RETRY_BASE_DELAY = 1.0

# 可重试的 HTTP 状态码
RETRYABLE_STATUS_CODES = {429, 500, 502, 503}


# ==================== 分块参数 ====================

CHUNK_SIZE = _get_config("chunk_size")
CHUNK_OVERLAP = _get_config("chunk_overlap")


# ==================== 检索参数 ====================

# 路由：匹配的数据库数量
ROUTE_TOP_K = _get_config("route_top_k")

# 检索返回数量
FAISS_TOP_N = _get_config("faiss_top_n")
BM25_TOP_N = _get_config("bm25_top_n")
HYBRID_TOP_N = _get_config("hybrid_top_n")

# 融合权重
FAISS_WEIGHT = _get_config("faiss_weight")
BM25_WEIGHT = _get_config("bm25_weight")

# ==================== 关键字过滤配置 ====================

KEYWORD_FILTER_ENABLED = _get_config("keyword_filter_enabled")
KEYWORD_BONUS_PER_MATCH = _get_config("keyword_bonus_per_match")
KEYWORD_USE_LLM = _get_config("keyword_use_llm")
KEYWORD_SAMPLE_CHUNKS = _get_config("keyword_sample_chunks")

# ==================== 重排参数 ====================

# 重排批次大小
RERANK_BATCH_SIZE = _get_config("rerank_batch_size")

# 重排后保留数量
RERANK_TOP_N = _get_config("rerank_top_n")

# LLM 重排权重（0~1）
RERANK_LLM_WEIGHT = _get_config("llm_weight")

# 配置备份保留数量
MAX_BACKUPS = _get_config("max_backups")


# ==================== 关键词配置 ====================

# 常见指标关键词
INDICATOR_KEYWORDS = [
    "营收", "收入", "净利润", "毛利", "毛利率", "净利率",
    "产能利用率", "产能", "出货量", "市占率", "市场份额",
    "每股收益", "EPS", "ROE", "ROA", "PE", "PB",
    "研发费用", "研发投入", "资本支出", "现金流",
    "资产负债率", "流动比率", "速动比率",
    "同比增长", "环比增长", "增长率",
]

# 常见维度关键词
DIMENSION_KEYWORDS = [
    "季度", "年度", "Q1", "Q2", "Q3", "Q4",
    "上半年", "下半年", "一季度", "二季度", "三季度", "四季度",
    "2024", "2025", "2026",
    "产能", "产能利用率", "毛利率",
    "汽车电子", "消费电子", "智能手机", "物联网", "AI",
]


# ==================== Pipeline 运行配置 ====================

@dataclass
class RunConfig:
    """Pipeline 运行参数配置，可被命令行参数覆盖"""
    # 检索配置
    route_top_k: int = ROUTE_TOP_K
    retrieve_top_n: int = HYBRID_TOP_N
    faiss_top_n: int = FAISS_TOP_N
    bm25_top_n: int = BM25_TOP_N
    faiss_weight: float = FAISS_WEIGHT
    bm25_weight: float = BM25_WEIGHT

    # 关键字过滤配置
    keyword_filter_enabled: bool = KEYWORD_FILTER_ENABLED
    keyword_bonus_per_match: float = KEYWORD_BONUS_PER_MATCH
    keyword_use_llm: bool = KEYWORD_USE_LLM
    keyword_sample_chunks: int = KEYWORD_SAMPLE_CHUNKS

    # 重排配置
    rerank_batch_size: int = RERANK_BATCH_SIZE
    rerank_top_n: int = RERANK_TOP_N
    llm_weight: float = RERANK_LLM_WEIGHT

    # LLM 配置
    llm_model: str = LLM_MODEL

    # 嵌入配置
    embedding_model: str = EMBEDDING_MODEL

    # 分块配置
    chunk_size: int = CHUNK_SIZE
    chunk_overlap: int = CHUNK_OVERLAP

    # 输出配置
    answers_file: Optional[str] = None  # 批量答案输出文件

    # 问题文件路径
    questions_file: Optional[str] = None  # 批量问题 JSON 文件路径


@dataclass
class PipelinePaths:
    """Pipeline 路径配置"""
    project_root: Path = PROJECT_ROOT
    pdf_data: Path = PDF_DATA_DIR
    parsed_md: Path = PARSED_MD_DIR
    chunked_json: Path = CHUNKED_JSON_DIR
    faiss_index: Path = FAISS_INDEX_DIR
    bm25_index: Path = BM25_INDEX_DIR

    def ensure_dirs(self):
        """确保所有必需的目录存在"""
        for dir_path in [self.parsed_md, self.chunked_json, self.faiss_index, self.bm25_index]:
            dir_path.mkdir(parents=True, exist_ok=True)