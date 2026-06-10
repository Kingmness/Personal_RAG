# -*- coding: utf-8 -*-
"""
PRA RAG 企业知识库问答系统 - 安装配置
支持 pip install -e . 安装
"""

from pathlib import Path
from setuptools import setup, find_packages

# 依赖列表（若项目根目录有 requirements.txt 则从中读取，否则使用内置列表）
_requirements_path = Path(__file__).resolve().parent / "requirements.txt"
if _requirements_path.exists():
    with open(_requirements_path, "r", encoding="utf-8") as f:
        requirements = [line.strip() for line in f if line.strip() and not line.startswith("#")]
else:
    requirements = [
        "aiohttp>=3.10",
        "tiktoken>=0.8",
        "python-dotenv>=1.0",
        "openai>=1.50",
        "requests>=2.32",
        "tqdm>=4.66",
        "rank-bm25>=0.2",
        "PyPDF2>=3.0",
        "faiss-cpu>=1.9",
        "json_repair>=0.35",
        "click>=8.1",
        "langchain>=0.3",
        "dashscope>=1.20",
        "jieba>=0.42.1",
        "slowapi>=0.1.9",
    ]

setup(
    name="pra-rag",
    version="1.0.0",
    description="PRA RAG 企业知识库问答系统",
    author="PRA Team",
    python_requires=">=3.10",
    packages=find_packages(),
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "pra-rag=src.main:cli",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
)