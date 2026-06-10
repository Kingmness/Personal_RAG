# PRA-RAG 部署指南

## 1. 环境要求

| 项目 | 最低版本 | 说明 |
|------|----------|------|
| Python | 3.10+ | 后端运行环境 |
| Node.js | 18+ | 前端构建环境 |
| pip | 最新 | Python 包管理 |

## 2. 环境变量配置

在 `Backend/.env` 文件中配置以下变量：

```env
# 通义千问 API Key（必填，用于 Embedding 和 LLM 调用）
DASHSCOPE_API_KEY='sk-xxxxxxxxxxxxxxxx'

# MinerU API Key（必填，用于 PDF 解析）
MINERU_KEY='your_mineru_token'

# LLM 模型名称（可选，默认 qwen3.6-35b-a3b）
LLM_MODEL=qwen3.6-35b-a3b

# Embedding 模型名称（可选，默认 tongyi-embedding-vision-flash-2026-03-06）
EMBEDDING_MODEL=tongyi-embedding-vision-flash-2026-03-06

# API 认证密钥（可选，为空则不启用认证）
API_AUTH_KEY=

# CORS 允许的前端域名（可选，默认 http://localhost:5173,http://localhost:3000）
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
```

## 3. 后端部署

### 3.1 安装依赖

```bash
cd Backend
pip3 install -e . -i https://pypi.tuna.tsinghua.edu.cn/simple
```

或手动安装：

```bash
pip3 install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

核心依赖清单：
- `fastapi` + `uvicorn` - Web 服务
- `dashscope>=1.20` - 通义千问 SDK
- `faiss-cpu>=1.9` - 向量检索
- `rank-bm25>=0.2` - 关键词检索
- `jieba>=0.42.1` - 中文分词
- `langchain>=0.3` - 文本分块
- `tiktoken>=0.8` - Token 计数
- `slowapi>=0.1.9` - 速率限制
- `openai>=1.50` - LLM 兼容接口
- `click>=8.1` - CLI 工具

### 3.2 启动后端服务

```bash
cd Backend
python3 -m uvicorn src.server:app --host 0.0.0.0 --port 4000
```

生产环境建议：

```bash
uvicorn src.server:app --host 0.0.0.0 --port 4000 --workers 2
```

### 3.3 CLI 命令行使用

```bash
cd Backend

# 查看项目信息
python3 -m src.main info

# PDF 解析
python3 -m src.main parse-pdfs

# 文本分块
python3 -m src.main chunk

# 构建索引
python3 -m src.main build-index

# 注册元信息
python3 -m src.main register-metadata --company "中芯国际"

# 单个问答
python3 -m src.main answer --question "中芯国际2024年营收是多少？" --type number

# 批量问答
python3 -m src.main batch-answer --questions questions.json --output answers.json

# 一键全流程
python3 -m src.main full-pipeline
```

## 4. 前端部署

### 4.1 安装依赖

```bash
cd frontend
npm install
```

### 4.2 开发模式启动

```bash
npm run dev
```

默认访问地址：`http://localhost:3000`

前端开发服务器会自动将 `/api` 请求代理到后端 `http://localhost:4000`。

### 4.3 生产构建

```bash
npm run build
```

构建产物在 `dist/` 目录下，可部署到 Nginx 等静态服务器。

### 4.4 Nginx 配置示例

```nginx
server {
    listen 80;
    server_name your-domain.com;

    # 前端静态文件
    location / {
        root /path/to/RAG-PRA/frontend/dist;
        try_files $uri $uri/ /index.html;
    }

    # API 代理到后端
    location /api/ {
        proxy_pass http://127.0.0.1:4000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    # 健康检查
    location /health {
        proxy_pass http://127.0.0.1:4000;
    }
}
```

## 5. 数据处理流程

完整的文档处理流程为四步：

```
上传 PDF -> 解析(parse) -> 分块(chunk) -> 构建索引(index) -> 注册元信息(metadata)
```

可通过前端界面或 CLI 逐步执行，也可使用 `full-pipeline` 一键完成。

## 6. API 端点一览

| 方法 | 路径 | 说明 | 速率限制 |
|------|------|------|----------|
| GET | `/health` | 健康检查 | 无 |
| GET | `/api/companies` | 获取公司列表 | 无 |
| GET | `/api/documents` | 获取文档列表 | 无 |
| GET | `/api/document/status` | 获取文档处理状态 | 无 |
| GET | `/api/validate` | 校验索引一致性 | 无 |
| POST | `/api/upload` | 上传 PDF | 10/min |
| POST | `/api/parse` | 批量解析 PDF | 无 |
| POST | `/api/parse/single` | 单文档解析 | 无 |
| POST | `/api/chunk` | 批量文本分块 | 无 |
| POST | `/api/chunk/single` | 单文档分块 | 无 |
| POST | `/api/index` | 批量构建索引 | 无 |
| POST | `/api/index/single` | 单文档索引 | 无 |
| POST | `/api/metadata` | 批量注册元信息 | 无 |
| POST | `/api/metadata/single` | 单文档元信息 | 无 |
| POST | `/api/retrieve` | 检索文档片段 | 30/min |
| POST | `/api/answer` | 完整问答 | 20/min |
| POST | `/api/answer/stream` | 流式问答(SSE) | 20/min |
| DELETE | `/api/document/{file_name}` | 删除文档 | 10/min |

## 7. 注意事项

### 7.1 API Key 安全

- `DASHSCOPE_API_KEY` 和 `MINERU_KEY` 是敏感信息，不要提交到版本控制
- 如需启用 API 认证，设置 `API_AUTH_KEY` 环境变量，前端请求需在 Header 中携带 `X-API-Key`

### 7.2 文件大小限制

- PDF 上传上限：200MB
- MinerU 单文件页数上限：200页（超出会自动切分）

### 7.3 日志管理

- 日志文件位于 `Backend/logs/pra.log`
- 自动轮转：单文件最大 10MB，保留 5 个备份
- 自动清理：超过 7 天的日志文件会被自动删除

### 7.4 端口冲突

- 后端默认端口：4000
- 前端默认端口：3000（被占用时 Vite 自动切换到 3001）
- 如需修改端口，后端修改 uvicorn 启动参数，前端修改 `vite.config.ts` 中的 `server.port`

### 7.5 常见问题

**Q: 启动后端报 `DASHSCOPE_API_KEY` 未找到**
A: 检查 `Backend/.env` 文件是否存在且包含有效的 API Key。

**Q: PDF 解析失败**
A: 检查 `MINERU_KEY` 是否配置，MinerU 云端服务是否可用。

**Q: 前端无法连接后端**
A: 确认后端已启动且端口正确，检查 `vite.config.ts` 中的 proxy 配置。

**Q: 嵌入 API 偶发失败**
A: 已内置指数退避重试机制（最多 3 次），如持续失败检查 API Key 和网络。

**Q: 日志文件过多**
A: 日志会自动清理 7 天前的文件，如需手动清理可删除 `Backend/logs/` 下的旧文件。
