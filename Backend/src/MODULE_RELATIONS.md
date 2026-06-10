# RAG-PRA 后端模块关系图

## 目录结构

```
Backend/src/
├── server.py              # FastAPI 应用入口
├── dependencies.py        # 全局共享状态与依赖注入
├── config.py              # 配置中心（环境变量 + 路径 + 参数）
├── config_manager.py      # 配置持久化（JSON 文件读写 + 备份）
├── logger.py              # 日志系统（trace_id 上下文 + 文件轮转）
├── main.py                # CLI 命令行入口（click）
├── pipeline.py            # 管线调度器（串联全流程）
├── pdf_mineru_parser.py   # PDF 解析（MinerU API）
├── text_chunker.py        # 文本分块（LangChain RecursiveSplitter）
├── ingestion.py           # 索引构建（FAISS + BM25）
├── metadata.py            # 元信息管理（SQLite）
├── retrieval.py           # 混合检索（FAISS + BM25 融合）
├── reranking.py           # LLM 重排序
├── keyword_extractor.py   # 关键词提取（jieba + LLM）
├── question_rewriter.py   # 查询改写（LLM）
├── questions_processing.py # 问答处理器（检索->重排序->LLM生成）
├── api_requests.py        # LLM API 客户端（DashScope/OpenAI）
├── prompts.py             # Prompt 模板
├── retry_utils.py         # 重试工具（指数退避）
├── history_store.py       # 历史记录存储（SQLite）
└── routers/
    ├── __init__.py         # 路由包导出
    ├── health.py           # 健康检查 + 链路追踪
    ├── documents.py        # 文档管理（上传/解析/分块/索引/删除）
    ├── query.py            # 查询（检索/问答/流式问答）
    ├── history.py          # 历史记录 CRUD
    └── admin.py            # 管理接口（配置/日志级别/重启/前端日志）
```

## 模块依赖关系

### 第一层：基础设施（无内部依赖）

| 模块 | 职责 | 依赖 |
|------|------|------|
| `config.py` | 环境变量加载、路径定义、RunConfig 数据类、CONFIG_SCHEMA | dotenv（外部） |
| `logger.py` | 日志初始化、trace_id 上下文传播、文件轮转 | config |
| `prompts.py` | 5 种答案类型的 Prompt 模板 | 无 |
| `retry_utils.py` | 指数退避重试、Embedding 调用封装 | config, logger, dashscope（外部） |

### 第二层：数据处理（依赖基础设施）

| 模块 | 职责 | 依赖 |
|------|------|------|
| `pdf_mineru_parser.py` | 调用 MinerU API 解析 PDF 为 Markdown | config, logger |
| `text_chunker.py` | Markdown 文本递归分块 | config, logger |
| `ingestion.py` | 构建 FAISS 向量索引 + BM25 稀疏索引 | config, logger, retry_utils |
| `metadata.py` | SQLite 元信息 CRUD + 一致性校验 | config, logger |
| `history_store.py` | SQLite 历史记录 CRUD + 自动清理 | config, logger |
| `config_manager.py` | JSON 配置文件读写 + 备份恢复 | config |

### 第三层：检索与推理（依赖数据处理 + 基础设施）

| 模块 | 职责 | 依赖 |
|------|------|------|
| `api_requests.py` | DashScope LLM 调用、流式/非流式、JSON 修复 | config, prompts |
| `retrieval.py` | FAISS 向量检索 + BM25 稀疏检索 + 混合融合 | config, logger, retry_utils |
| `reranking.py` | LLM 相关性评分重排序 | config, logger |
| `keyword_extractor.py` | jieba 分词 + LLM 关键词提取 | config |
| `question_rewriter.py` | LLM 查询改写 | config, logger |

### 第四层：问答处理器（依赖检索与推理）

| 模块 | 职责 | 依赖 |
|------|------|------|
| `questions_processing.py` | 串联检索->重排序->上下文截取->Prompt构建->LLM生成->页码校验 | retrieval, reranking, api_requests, config, logger, prompts |

### 第五层：管线调度器（依赖问答处理器 + 数据处理）

| 模块 | 职责 | 依赖 |
|------|------|------|
| `pipeline.py` | 串联全流程：PDF解析->分块->索引->元信息->问答 | config, logger, 懒加载 questions_processing/pdf_mineru_parser/text_chunker/ingestion/metadata |

### 第六层：Web 服务层（依赖管线调度器）

| 模块 | 职责 | 依赖 |
|------|------|------|
| `dependencies.py` | Pipeline 单例、写锁、元数据管理器、配置同步 | pipeline, metadata, logger |
| `server.py` | FastAPI 应用入口、中间件、路由注册 | config, logger, history_store, routers |
| `routers/health.py` | /health, /api/trace | config, dependencies |
| `routers/documents.py` | 文档上传/解析/分块/索引/删除/校验 | config, dependencies |
| `routers/query.py` | /api/retrieve, /api/answer, /api/answer/stream | dependencies |
| `routers/history.py` | 历史记录 CRUD + 清理 | history_store, dependencies |
| `routers/admin.py` | 配置/日志级别/重启/前端日志 | config, config_manager, dependencies, logger |

### 第七层：CLI 入口

| 模块 | 职责 | 依赖 |
|------|------|------|
| `main.py` | click 命令行入口，支持索引构建和问答 | config, pipeline, logger |

## 核心调用链

### 索引管线（写入路径）

```
server.py
  └─> routers/documents.py
        └─> dependencies.get_pipeline()
              └─> pipeline.py
                    ├─> pdf_mineru_parser.py   (PDF -> Markdown)
                    ├─> text_chunker.py         (Markdown -> Chunks)
                    ├─> ingestion.py            (Chunks -> FAISS + BM25)
                    └─> metadata.py             (元信息 -> SQLite)
```

### 查询管线（读取路径）

```
server.py
  └─> routers/query.py
        └─> dependencies.get_pipeline()
              └─> pipeline.question_processor (懒加载)
                    └─> questions_processing.py
                          ├─> retrieval.py           (FAISS + BM25 混合检索)
                          │     └─> retry_utils.py   (Embedding 重试)
                          ├─> reranking.py            (LLM 相关性重排序)
                          │     └─> api_requests.py   (DashScope 调用)
                          │           └─> prompts.py  (Prompt 模板)
                          └─> api_requests.py         (LLM 生成答案)
                                └─> prompts.py
```

### 配置管理路径

```
server.py
  └─> routers/admin.py
        ├─> config_manager.py     (JSON 配置读写)
        │     └─> config.py       (CONFIG_SCHEMA)
        └─> dependencies.apply_config_to_pipeline()
              └─> pipeline.config (运行时热更新)
```

## 数据流向

```
PDF文件 ──parse──> Markdown ──chunk──> JSON分块 ──index──> FAISS + BM25
                                                         │
用户问题 ──retrieve──> 候选文档 ──rerank──> 精选文档 ──LLM──> 答案
                                                         │
                                              ──history──> SQLite
```
