# PRA-RAG 企业知识库项目架构分析

## 一、项目概述

PRA-RAG 是一个基于检索增强生成（Retrieval-Augmented Generation）技术的企业知识库问答系统。系统以金融领域研报、年报、调研纪要等 PDF 文档为知识来源，通过"文档解析 -> 文本分块 -> 索引构建 -> 混合检索 -> LLM 重排 -> 答案生成"的完整 Pipeline，实现对结构化问题的精准回答。

系统支持 5 种答案类型（数值/名称/布尔/列表/开放文本），并提供 REST API 和 CLI 两种使用方式。

---

## 二、技术栈

### 2.1 核心框架与语言

| 类别 | 技术 | 说明 |
|------|------|------|
| 编程语言 | Python 3.10+ | 项目最低要求 Python 3.10 |
| Web 框架 | FastAPI + Uvicorn | 提供 REST API 服务，支持 SSE 流式输出 |
| CLI 框架 | Click | 提供命令行接口，支持各阶段单独执行 |
| 数据校验 | Pydantic | FastAPI 请求/响应模型定义 |

### 2.2 AI / NLP 相关

| 类别 | 技术 | 说明 |
|------|------|------|
| LLM | 通义千问 (qwen3.6-plus) | 通过 DashScope OpenAI 兼容接口调用，用于重排序和答案生成 |
| Embedding | 通义千问多模态向量模型 (tongyi-embedding-vision-flash) | 通过 DashScope MultiModalEmbedding API 调用，用于文档和问题的向量化 |
| PDF 解析 | MinerU 云端 API | 云端 PDF 解析服务，支持表格解析和图片 OCR |
| Tokenizer | tiktoken (gpt-4o) | 用于文本分块时的 token 计数 |
| 文本分块 | LangChain RecursiveCharacterTextSplitter | 基于 tiktoken 编码器的递归字符分块器 |

### 2.3 检索与索引

| 类别 | 技术 | 说明 |
|------|------|------|
| 向量检索 | FAISS (IndexFlatIP) | 基于内积的向量检索，L2 归一化后等价于余弦相似度 |
| 关键词检索 | rank_bm25 (BM25Okapi) | 经典 BM25 算法，基于分词后的文本匹配 |
| 混合检索 | FAISS + BM25 加权融合 | FAISS 权重 0.6，BM25 权重 0.4，min-max 归一化后加权 |

### 2.4 工具库

| 类别 | 技术 | 说明 |
|------|------|------|
| HTTP 客户端 | OpenAI Python SDK | 用于调用 DashScope 的 OpenAI 兼容接口 |
| JSON 修复 | json_repair | 修复 LLM 输出的非标准 JSON |
| PDF 处理 | PyPDF2 | 用于 PDF 切分（大文件拆分） |
| 环境变量 | python-dotenv | 从 .env 文件加载环境变量 |
| 异步并发 | asyncio + ThreadPoolExecutor | 并行 API 请求和 LLM 重排批处理 |
| 进度条 | tqdm | 批量处理时的进度展示 |

---

## 三、系统架构

### 3.1 整体架构图

```
+------------------------------------------------------------------+
|                        用户交互层                                   |
|  +-------------------+          +-------------------+              |
|  |   REST API        |          |   CLI 命令行       |              |
|  |   (FastAPI)       |          |   (Click)         |              |
|  +--------+----------+          +--------+----------+              |
+-----------|------------------------------|-------------------------+
            |                              |
            v                              v
+------------------------------------------------------------------+
|                     Pipeline 中枢调度层                             |
|  +------------------------------------------------------------+  |
|  |                    Pipeline (pipeline.py)                    |  |
|  |  串联5个阶段: 解析 -> 分块 -> 索引 -> 元信息 -> 问答         |  |
|  +------------------------------------------------------------+  |
+-----------|-------------------------------------------------------
            |
  +---------+---------+---------+---------+---------+
  |         |         |         |         |         |
  v         v         v         v         v         v
+------+ +------+ +------+ +------+ +------+ +-----------+
| PDF  | | 文本 | | 索引 | | 元信 | | 问答 | | 问题重写  |
| 解析 | | 分块 | | 构建 | | 息管 | | 处理 | | (比较类    |
|      | |      | |      | | 理   | |      | |  问题拆解) |
+------+ +------+ +------+ +------+ +------+ +-----------+
  |         |         |                |
  v         v         v                v
+------+ +------+ +------+      +-----------+
|MinerU| |LangCh| |BM25  |      | 元信息    |
|云端  | |ain   | |Ingest|      | CSV管理   |
|API   | |Split | |FAISS |      |           |
+------+ +------+ |Ingest|      +-----------+
                  +------+
                      |
            +---------+---------+
            |                   |
            v                   v
        +-------+          +-------+
        | BM25  |          | FAISS |
        | Index |          | Index |
        +-------+          +-------+

+------------------------------------------------------------------+
|                     问答处理核心流程                                |
|                                                                   |
|  用户问题                                                          |
|    |                                                              |
|    v                                                              |
|  [问题嵌入] -> [路由筛选] -> [FAISS检索] + [BM25检索]              |
|                                  |                                |
|                                  v                                |
|                           [混合融合]                               |
|                                  |                                |
|                                  v                                |
|                           [LLM重排序]                              |
|                                  |                                |
|                                  v                                |
|                        [上下文截取与构建]                           |
|                                  |                                |
|                                  v                                |
|                         [LLM答案生成]                              |
|                                  |                                |
|                                  v                                |
|                         [页码校验] -> 最终答案                      |
+------------------------------------------------------------------+
```

### 3.2 数据流架构

```
PDF 文件  -->  MinerU 解析  -->  Markdown (带页码标记)
                                       |
                                       v
                              按页码 + Token 分块
                                       |
                                       v
                              Chunked JSON (每文档一个)
                                     /     \
                                    /       \
                                   v         v
                            BM25 索引     FAISS 向量索引
                            (.pkl)        (.faiss)
                                    \     /
                                     \   /
                                      v v
                                  混合检索引擎
                                       |
                                       v
                              LLM 重排序 + 答案生成
                                       |
                                       v
                                  结构化答案 (JSON)
```

---

## 四、目录结构

```
PRA/
+-- server.py                          # FastAPI 后端服务入口
+-- main.py                            # CLI 命令行入口
+-- pipeline.py                        # Pipeline 中枢调度器
+-- config.py                          # 统一配置管理
+-- logger.py                          # 日志系统
+-- setup.py                           # 安装配置
|
+-- pdf_mineru_parser.py               # MinerU 云端 PDF 解析器
+-- text_chunker.py                    # Markdown 文本分块工具
+-- ingestion.py                       # 索引构建 (BM25 + FAISS)
+-- retrieval.py                       # 混合检索引擎
+-- reranking.py                       # LLM 重排序模块
+-- prompts.py                         # Prompt 模板与结构化输出 Schema
+-- api_requests.py                    # LLM API 客户端封装
+-- questions_processing.py            # 问答处理器 (检索->重排->生成)
+-- keyword_extractor.py               # 问题关键字提取器
+-- question_rewriter.py               # 比较类问题重写器
+-- metadata.py                        # 元信息管理器
+-- api_request_parallel_processor.py  # 并行 API 请求处理器
|
+-- pdf_data/                          # 原始 PDF 文件存放目录
+-- parsed_md/                         # 解析后的 Markdown 文件
+-- chunked_json/                      # 分块后的 JSON 文件
+-- faiss_index/                       # FAISS 向量索引文件
+-- bm25_index/                        # BM25 索引文件
+-- logs/                              # 运行日志
+-- design/                            # 设计文档
|
+-- .env                               # 环境变量配置
+-- answers.json                       # 批量问答结果输出
+-- metadata.csv                       # 文档元信息注册表
```

---

## 五、核心模块详解

### 5.1 配置管理 (config.py)

集中管理所有常量、模型名、分块参数、检索参数等。采用 `.env` 环境变量 + 类属性二级覆盖机制。

**关键配置项：**

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| EMBEDDING_MODEL | tongyi-embedding-vision-flash-2026-03-06 | 嵌入模型 |
| LLM_MODEL | qwen3.6-plus-2026-04-02 | LLM 对话模型 |
| CHUNK_SIZE | 300 | 每个分块的 token 数 |
| CHUNK_OVERLAP | 50 | 分块之间的重叠 token 数 |
| ROUTE_TOP_K | 3 | 路由匹配的数据库数量 |
| FAISS_TOP_N | 30 | FAISS 检索返回数量 |
| BM25_TOP_N | 30 | BM25 检索返回数量 |
| HYBRID_TOP_N | 10 | 混合融合后返回数量 |
| FAISS_WEIGHT | 0.6 | FAISS 检索权重 |
| BM25_WEIGHT | 0.4 | BM25 检索权重 |
| RERANK_BATCH_SIZE | 4 | 重排批次大小 |
| RERANK_TOP_N | 10 | 重排后保留数量 |
| RERANK_LLM_WEIGHT | 0.7 | LLM 重排权重 |

**数据类：**
- `RunConfig`：Pipeline 运行参数配置，可被命令行参数覆盖
- `PipelinePaths`：Pipeline 路径配置，管理各阶段的数据目录

### 5.2 Pipeline 中枢调度器 (pipeline.py)

串联 PDF 解析、文本分块、索引构建、元信息注册、问答处理的完整流程。支持单步执行和全流程一键运行，支持增量处理单个文档。

**5 个阶段：**

| 阶段 | 方法 | 说明 |
|------|------|------|
| 1. PDF 解析 | `parse_pdfs()` / `parse_single_pdf()` | 调用 MinerU 云端 API 将 PDF 解析为 Markdown |
| 2. 文本分块 | `chunk_reports()` / `chunk_single_report()` | 将 Markdown 按页码和 token 分块 |
| 3. 索引构建 | `build_indices()` / `build_single_index()` | 构建 BM25 和 FAISS 索引 |
| 4. 元信息注册 | `register_metadata()` / `register_single_metadata()` | 注册文档元信息到 metadata.csv |
| 5. 问答处理 | `answer_question()` / `batch_answer()` | 执行完整的 RAG 问答流程 |

### 5.3 PDF 解析器 (pdf_mineru_parser.py)

基于 MinerU 云端 API 的 PDF 文档解析器，核心特性：

- **自动切分**：超过 200MB 或 200 页的 PDF 自动按页切分后再解析
- **批量上传**：支持一次批量上传多个文件（最多 200 个）
- **轮询等待**：解析完成后自动下载结果，支持 ZIP 包解压
- **页码保留**：解析结果中保留源文件的页码标记（`<!-- 第N页 -->`）
- **表格和公式**：启用公式识别和表格解析

### 5.4 文本分块器 (text_chunker.py)

基于页码标记对 Markdown 文件进行分块：

1. 按 `<!-- 第N页 -->` 标记将 Markdown 拆分为页面
2. 每页使用 LangChain 的 `RecursiveCharacterTextSplitter` 按 300 token 分块
3. 使用 tiktoken (gpt-4o) 计算 token 数
4. 输出 JSON 格式，每个 chunk 包含 id、page、length_tokens、text

### 5.5 索引构建 (ingestion.py)

为每个源文档分别构建 BM25 索引和 FAISS 向量库：

**BM25Ingestor：**
- 使用 `rank_bm25.BM25Okapi` 构建关键词索引
- 对文本按空格分词后构建索引
- 保存为 `.pkl` 文件

**VectorDBIngestor：**
- 调用 DashScope MultiModalEmbedding API 获取文本嵌入向量
- 每批最多 10 个文本，分批调用 API
- 使用 FAISS `IndexFlatIP` 构建向量索引（L2 归一化后等价余弦相似度）
- 保存为 `.faiss` 文件

### 5.6 混合检索引擎 (retrieval.py)

核心检索模块，实现"嵌入 -> 路由 -> 双路检索 -> 融合 -> 父页面返回"的完整流程：

1. **嵌入问题**：调用 DashScope API 将用户问题转为向量
2. **路由筛选**：在所有 FAISS 数据库中检索 Top-3，按平均余弦相似度选出最相关的 `route_top_k` 个数据库
3. **FAISS 检索**：在匹配到的数据库中进行向量相似度检索
4. **BM25 检索**：在匹配到的数据库中进行关键词检索
5. **混合融合**：对 FAISS 和 BM25 分数分别做 min-max 归一化，按 0.6:0.4 加权融合，单侧缺失时补 0.3
6. **父页面返回**：根据匹配 chunk 的原始页码，返回整页文本

### 5.7 LLM 重排序 (reranking.py)

基于 DashScope 通义千问的 LLM 重排序器：

1. 将文档分批（每批 4 个），并行调用 LLM 对每批进行相关性评分
2. LLM 对每个文档块输出 0~1 的相关性分数和推理理由
3. 检索分数与 LLM 分数分别归一化后加权融合（默认 LLM 权重 0.7，检索权重 0.3）
4. 按融合分数降序取 top_n

### 5.8 Prompt 模板 (prompts.py)

定义 5 种答案类型的 Prompt 模板，每种包含指令、JSON 格式要求和 2 个示例：

| 类型 | 说明 | final_answer 格式 |
|------|------|-------------------|
| number | 数值型 | 数字 或 "N/A" |
| name | 名称型 | 字符串 或 "N/A" |
| boolean | 布尔型 | true/false/"N/A" |
| list | 列表型 | 字符串数组 或 "N/A" |
| text | 开放文本型 | 自然语言 或 "N/A" |

### 5.9 问答处理器 (questions_processing.py)

串联检索、重排序、LLM 生成答案的完整流程，核心特性：

- **关键词提取**：从问题中提取 2-gram 和 3-gram 中文关键词，去掉停用词
- **上下文截取**：基于关键词在文档中定位，截取前后各 100 字符，合并重叠片段，扩展到句子边界
- **页码校验**：过滤 LLM 幻觉页码，确保引用的页码在检索结果中真实存在
- **流式输出**：支持 SSE 流式推送进度和 LLM 输出
- **耗时告警**：各步骤超阈值时自动告警

### 5.10 问题关键字提取器 (keyword_extractor.py)

从用户问题中提取结构化关键字，支持两种模式：

- **正则提取**：基于预定义的公司名模式、指标关键词、维度关键词、时间范围模式
- **LLM 提取**：调用 LLM 进行更准确的结构化关键字提取

提取维度：companies、indicators、time_range、dimensions、quoted_text

### 5.11 问题重写器 (question_rewriter.py)

将比较类问题（涉及多家公司对比）拆解为针对单个公司的独立问题：

- 通过关键词模式判断是否为比较类问题
- 调用 LLM 将比较类问题拆解为多个独立子问题
- 每个子问题可独立通过 RAG 流程检索和回答

### 5.12 元信息管理 (metadata.py)

为每个源文档生成唯一标识（SHA-1），记录公司名、报告类型等元信息：

- 基于 SHA-1 哈希去重
- 保存为 CSV 文件，便于检索时按公司名过滤
- 支持从文件名自动推断公司名和报告类型

### 5.13 LLM API 客户端 (api_requests.py)

封装 DashScope 通义千问的 LLM 调用，提供 4 个核心方法：

| 方法 | 说明 |
|------|------|
| `chat()` | 普通对话，返回文本 |
| `chat_json()` | 强制 JSON 输出 |
| `chat_stream()` | 流式对话，逐 token 返回 |
| `answer_with_context()` | 基于检索上下文回答问题 |

### 5.14 日志系统 (logger.py)

统一的日志配置，支持控制台输出和文件日志：

- 日志文件按时间戳命名，存放在 `logs/` 目录
- 控制台输出 INFO 级别，文件输出 DEBUG 级别
- 避免重复添加 handler

---

## 六、API 接口

### 6.1 文档管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/companies` | 获取所有公司列表 |
| GET | `/api/documents` | 获取文档列表（可按公司过滤） |
| POST | `/api/upload` | 上传 PDF 文件 |
| GET | `/api/document/status` | 获取单个文档的处理状态 |

### 6.2 文档处理（批量）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/parse` | 解析所有 PDF 文档 |
| POST | `/api/chunk` | 文本分块 |
| POST | `/api/index` | 构建索引 |
| POST | `/api/metadata` | 注册元信息 |

### 6.3 文档处理（单个文档增量）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/parse/single` | 增量解析单个 PDF |
| POST | `/api/chunk/single` | 增量分块单个文档 |
| POST | `/api/index/single` | 增量构建单个文档索引 |
| POST | `/api/metadata/single` | 增量注册单个文档元信息 |

### 6.4 问答

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/retrieve` | 检索文档片段 |
| POST | `/api/answer` | 完整问答流程 |
| POST | `/api/answer/stream` | 流式问答（SSE） |

---

## 七、CLI 命令

| 命令 | 说明 |
|------|------|
| `python3 main.py parse-pdfs` | 解析 PDF 文件 |
| `python3 main.py chunk` | 文本分块 |
| `python3 main.py build-index` | 构建索引 |
| `python3 main.py register-metadata` | 注册元信息 |
| `python3 main.py answer` | 单个问题问答 |
| `python3 main.py batch-answer` | 批量问答 |
| `python3 main.py full-pipeline` | 一键全流程 |

---

## 八、关键设计决策

### 8.1 按文档独立建索引

系统为每个源文档分别构建 BM25 和 FAISS 索引，而非将所有文档合并为一个索引。这样做的优势：
- 支持增量添加新文档，无需重建全部索引
- 路由阶段可按文档粒度筛选，减少无关文档的干扰
- 索引文件独立，便于管理和删除

### 8.2 路由机制

在检索前增加路由阶段，先在所有数据库中做 Top-3 检索，按平均相似度筛选最相关的数据库。这避免了在全量数据库中检索带来的噪声问题，尤其当知识库文档数量多、主题差异大时效果显著。

### 8.3 混合检索 + LLM 重排

采用"BM25 + FAISS 混合检索 -> LLM 重排"的两阶段策略：
- 第一阶段：BM25 和 FAISS 各自检索，加权融合取 Top-N，保证召回率
- 第二阶段：LLM 对候选文档进行相关性评分，与检索分数加权融合，保证精准度

### 8.4 上下文截取

在构建 LLM 上下文时，基于问题关键词对文档内容进行截取，只保留关键词附近的文本片段。这减少了送入 LLM 的 token 量，同时提高了信息的信噪比。

### 8.5 父页面返回

检索匹配到的是 chunk 级别，但返回给 LLM 的是整页文本。这样做的优势：
- 保留完整的上下文信息，避免 chunk 切割导致的信息丢失
- LLM 可以看到同一页上的其他相关信息

### 8.6 页码校验

LLM 生成的答案中可能引用不存在的页码（幻觉），系统会校验引用页码是否在检索结果中真实存在，过滤幻觉页码。

---

## 九、外部服务依赖

| 服务 | 用途 | 配置项 |
|------|------|--------|
| DashScope (通义千问) | LLM 对话 + 文本嵌入 | `DASHSCOPE_API_KEY` |
| MinerU 云端 API | PDF 文档解析 | `MINERU_KEY` |

---

## 十、数据存储

| 目录/文件 | 格式 | 说明 |
|-----------|------|------|
| `pdf_data/` | PDF | 原始 PDF 文件 |
| `parsed_md/` | Markdown | 解析后的 Markdown（带页码标记） |
| `chunked_json/` | JSON | 分块后的数据，每文档一个文件 |
| `faiss_index/` | FAISS | 向量索引文件 |
| `bm25_index/` | Pickle | BM25 索引文件 |
| `metadata.csv` | CSV | 文档元信息注册表 |
| `logs/` | Log | 运行日志 |
| `answers.json` | JSON | 批量问答结果输出 |

---

## 十一、模块依赖关系

```
server.py  -->  pipeline.py  -->  pdf_mineru_parser.py
    |               |              text_chunker.py
    |               |              ingestion.py  -->  retrieval.py (加载索引)
    |               |              metadata.py
    |               |              questions_processing.py
    |                                      |
    |                                      +--> retrieval.py  --> config.py
    |                                      +--> reranking.py  --> api_requests.py
    |                                      +--> api_requests.py
    |                                      +--> prompts.py
    |
    +--> config.py
    +--> logger.py

main.py  -->  pipeline.py  (同上)

keyword_extractor.py  -->  api_requests.py  -->  config.py
question_rewriter.py  -->  api_requests.py  -->  config.py
api_request_parallel_processor.py  (独立工具模块)
```

---

## 十二、示例数据

项目内置了 13 份 PDF 文档作为知识库，涵盖以下主题：

- **中芯国际**（9 份）：券商研报、年报、调研纪要
- **迪士尼**（3 份）：乐园现状、公司发展、旅游攻略
- **浦发银行**（1 份）：考核办法

这些文档已完成了从 PDF 解析到索引构建的全流程，可直接用于问答测试。
