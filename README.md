# PRA-RAG 企业知识库

基于 RAG（检索增强生成）技术的企业知识库问答系统，支持 PDF 文档上传、智能解析、混合检索和流式问答。

## 项目架构

```
RAG-PRA/
├── Backend/                    # 后端服务 (FastAPI)
│   ├── src/                    # 核心源码
│   │   ├── server.py           # FastAPI 服务入口
│   │   ├── main.py             # CLI 命令行入口
│   │   ├── pipeline.py         # RAG 流水线
│   │   ├── pdf_mineru_parser.py # MinerU PDF 解析
│   │   ├── text_chunker.py     # 文本分块
│   │   ├── ingestion.py        # 索引构建 (BM25 + FAISS)
│   │   ├── retrieval.py        # 混合检索 (FAISS + BM25)
│   │   ├── reranking.py        # LLM 重排
│   │   ├── questions_processing.py  # 问答处理
│   │   ├── keyword_extractor.py     # 关键词提取
│   │   ├── question_rewriter.py     # 比较类问题拆解
│   │   ├── metadata.py         # 元信息管理
│   │   ├── config.py           # 统一配置
│   │   ├── api_requests.py     # LLM API 客户端
│   │   ├── prompts.py          # Prompt 模板
│   │   ├── retry_utils.py      # 重试工具
│   │   ├── history_store.py    # 历史记录存储
│   │   ├── config_manager.py   # 配置管理器
│   │   ├── dependencies.py     # 依赖注入
│   │   ├── logger.py           # 日志系统
│   │   └── routers/            # API 路由模块
│   │       ├── admin.py        # 管理接口
│   │       ├── documents.py    # 文档管理接口
│   │       ├── health.py       # 健康检查接口
│   │       ├── history.py      # 历史记录接口
│   │       └── query.py        # 问答接口
│   ├── tests/                  # 单元测试
│   ├── data/                   # 数据目录 (gitignore)
│   ├── design/                 # 设计文档
│   ├── .env.example            # 环境变量模板
│   └── requirements.txt        # Python 依赖
├── frontend/                   # 前端服务 (React + TypeScript + TailwindCSS)
│   ├── src/
│   │   ├── components/         # UI 组件
│   │   ├── pages/              # 页面
│   │   ├── api/                # API 客户端
│   │   ├── types/              # 类型定义
│   │   └── utils/              # 工具函数
│   ├── package.json
│   ├── vite.config.ts
│   └── tailwind.config.js
├── test_questions/             # 评测脚本与结果
│   ├── test_0_link_connectivity.py
│   ├── test_1_retrieval.py
│   ├── test_2_reranking.py
│   ├── test_3_e2e_answer.py
│   ├── test_4_full_batch.py
│   ├── test_utils.py
│   └── results/                # 评测结果 (gitignore)
├── start.sh                    # 启动脚本
├── stop.sh                     # 停止脚本
└── restart.sh                  # 重启脚本
```

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | FastAPI + Uvicorn |
| 前端框架 | React 18 + TypeScript + TailwindCSS |
| LLM | 通义千问 (qwen3.6-35b-a3b) |
| Embedding | 通义千问多模态 Embedding |
| PDF 解析 | MinerU 云 API |
| 向量检索 | FAISS |
| 关键词检索 | rank_bm25 |
| 文本分块 | LangChain RecursiveCharacterTextSplitter + tiktoken |
| 分词 | jieba |

## 核心流程

```
PDF 上传 -> MinerU 解析 -> 文本分块 -> 索引构建 (FAISS + BM25)
                                                |
用户提问 -> 关键词提取 -> 问题改写 -> 混合检索 -> LLM 重排 -> 上下文截取 -> 流式回答
```

## 快速开始

### 1. 环境要求

- Python 3.10+
- Node.js 18+
- pip3

### 2. 配置环境变量

```bash
cd Backend
cp .env.example .env
# 编辑 .env 填入你的 API Key
```

### 3. 安装后端依赖

```bash
cd Backend
pip3 install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 4. 安装前端依赖

```bash
cd frontend
npm install
```

### 5. 启动服务

```bash
# 一键启动
./start.sh

# 或分别启动
# 后端
cd Backend && python3 -m uvicorn src.server:app --host 0.0.0.0 --port 4000

# 前端
cd frontend && npx vite --port 3000
```

启动后访问：
- 前端：http://localhost:3000
- 后端：http://localhost:4000
- 健康检查：http://localhost:4000/health

### 6. 停止/重启服务

```bash
./stop.sh      # 停止
./restart.sh   # 重启（含自动检测）
```

## 运行测试

```bash
# 单元测试
cd Backend
python3 -m pytest tests/ -v

# 评测脚本
cd test_questions
python3 test_0_link_connectivity.py
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /health | 健康检查 |
| GET | /api/companies | 获取公司列表 |
| GET | /api/documents | 获取文档列表 |
| POST | /api/upload | 上传 PDF 文档 |
| POST | /api/answer/stream | 流式问答 (SSE) |
| POST | /api/answer | 完整问答 |
| POST | /api/retrieve | 检索文档片段 |
| DELETE | /api/documents/{filename} | 删除文档 |
| GET | /api/validate | 一致性校验 |

## 项目结构说明

- `Backend/data/` - 存储 PDF、解析结果、索引等数据文件，不纳入版本控制
- `Backend/design/` - 项目设计文档和分析报告
- `Backend/tests/` - pytest 单元测试
- `test_questions/` - RAG 评测脚本与结果
- `.env` - 环境变量（含 API Key），不纳入版本控制

## License

MIT
