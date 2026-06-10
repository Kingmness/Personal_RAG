# PRA-RAG 调试分析报告

> 分析时间: 2026-06-06
> 分析范围: Backend/src 全部源代码 + 运行日志
> 分析工具: TRAE-debugger

---

## 分析方法

遵循 TRAE-debugger 科学调试流程：

1. **日志证据收集**: 分析现有日志中的错误和告警
2. **假设构建**: 基于日志和代码分析构建故障假设
3. **插桩建议**: 为关键路径设计调试插桩点
4. **根因分析**: 追踪故障的完整调用链
5. **修复建议**: 提供可验证的修复方案

---

## 一、已确认的运行时故障

### BUG-1: 流式问答 KeyError 'data' (高频)

**现象**: 日志中反复出现 `流式问答失败: 'data'` 错误

**日志证据**:
```
2026-06-04 20:58:42 [ERROR] pra.api: 流式问答失败: 'data'
2026-06-04 20:59:32 [ERROR] pra.api: 流式问答失败: 'data'
2026-06-04 20:00:11 [ERROR] pra.api: 流式问答失败: 'data'
... (共 10+ 次)
```

**假设**: DashScope API 流式响应格式变更，`chunk.choices[0].delta` 中不包含 `data` 键，或流式响应中存在非标准 chunk（如 `choices` 为空列表）

**根因追踪**:

```
server.py:answer_stream
  -> questions_processing.py:answer_stream
    -> api_requests.py:chat_stream
      -> OpenAI SDK stream
        -> chunk.choices[0].delta.content  <-- 可能 choices 为空列表
```

**代码位置**: [api_requests.py:99-108](file:///Users/woman/Desktop/AI_Study/18-项目实战：企业知识库/RAG-PRA/Backend/src/api_requests.py#L99-L108)

```python
for chunk in stream:
    delta = chunk.choices[0].delta  # <-- choices 可能为空
    if delta.content:
        yield delta.content
```

**修复建议**:

```python
for chunk in stream:
    if not chunk.choices:
        continue
    delta = chunk.choices[0].delta
    if delta.content:
        yield delta.content
```

**验证方式**: 修复后发送流式问答请求，确认不再出现 `'data'` KeyError

---

### BUG-2: LLM 免费额度耗尽导致 403 错误 (中频)

**现象**: DashScope API 返回 403，免费额度已用完

**日志证据**:
```
2026-06-04 20:54:04 [ERROR] pra.api: 流式问答失败: Error code: 403 -
{'error': {'message': 'The free tier of the model has been exhausted...',
'type': 'AllocationQuota.FreeTierOnly'}}
```

**假设**: 未对 API 403 错误做专门处理，用户看到的错误信息不友好

**根因追踪**:

```
server.py:answer_stream
  -> questions_processing.py:answer_stream
    -> reranking.py:Reranker._score_batch / api_requests.py:chat_stream
      -> OpenAI SDK -> DashScope API 403
        -> 异常冒泡到 server.py 的 except Exception
```

**代码位置**: [server.py:590-593](file:///Users/woman/Desktop/AI_Study/18-项目实战：企业知识库/RAG-PRA/Backend/src/server.py#L590-L593)

**修复建议**: 在 `server.py` 的流式问答异常处理中，识别 403 错误并返回友好提示：

```python
except Exception as e:
    error_msg = str(e)
    if "403" in error_msg or "AllocationQuota" in error_msg:
        friendly_msg = "LLM API 额度不足，请联系管理员"
    else:
        friendly_msg = "问答服务暂时不可用"
    _log.error(f"流式问答失败: {e}")
    error_event = {"type": "error", "message": friendly_msg}
    yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"
```

---

### BUG-3: 重启脚本不存在 (低频)

**现象**: 调用 `/api/restart` 端点返回 404

**日志证据**:
```
2026-06-04 22:00:42 [ERROR] pra.api: 重启失败: 404: 重启脚本不存在
```

**假设**: `restart.sh` 脚本未部署到预期位置

**代码位置**: [server.py:751-754](file:///Users/woman/Desktop/AI_Study/18-项目实战：企业知识库/RAG-PRA/Backend/src/server.py#L751-L754)

**修复建议**: 在启动时检测 `restart.sh` 是否存在，若不存在则在日志中警告，并在 API 响应中给出更明确的部署指引

---

### BUG-4: Retriever.retrieve() 参数不匹配 (历史)

**现象**: 早期日志中出现 `unexpected keyword argument 'top_k'`

**日志证据**:
```
2026-05-30 20:59:03 [ERROR] pra.api: 检索失败: Retriever.retrieve() got an unexpected keyword argument 'top_k'
```

**假设**: `server.py` 调用 `retriever.retrieve()` 时传入了 `top_k` 参数，但 `retrieval.py` 的 `retrieve()` 方法签名中没有此参数（应为 `route_top_k`）

**当前状态**: 查看当前代码，`server.py` 已使用 `route_top_k`，此问题可能已修复。但需确认前端是否仍发送 `top_k` 参数

---

## 二、潜在运行时风险

### RISK-1: 重排序耗时过长

**现象**: 日志中出现重排序耗时告警

**日志证据**:
```
2026-05-31 16:22:15 [WARNING] pra.question_processor: [QA告警] Step2 重排序 耗时=41.15s > 阈值=15.0s
```

**假设**: 重排序 LLM 调用批次过大或 API 限流导致响应缓慢

**根因追踪**:

```
questions_processing.py:answer
  -> reranking.py:Reranker.rerank
    -> ThreadPoolExecutor(max_workers=min(len(batches), 4))
      -> _score_batch -> OpenAI API
        -> DashScope 限流 -> 响应延迟
```

**代码位置**: [reranking.py:181](file:///Users/woman/Desktop/AI_Study/18-项目实战：企业知识库/RAG-PRA/Backend/src/reranking.py#L181)

**建议**: 增加单批次 LLM 调用超时设置，并在超时后降级为纯检索分数排序

---

### RISK-2: Pipeline 单例竞态条件

**现象**: `server.py` 中 Pipeline 使用双重检查锁模式，但 `asyncio.Lock` 在多线程环境下不安全

**代码位置**: [server.py:127-145](file:///Users/woman/Desktop/AI_Study/18-项目实战：企业知识库/RAG-PRA/Backend/src/server.py#L127-L145)

**假设**: 当多个并发请求同时触发 Pipeline 重建时，可能出现竞态条件

**调试插桩建议**:

```python
# 在 get_pipeline() 中增加日志
def get_pipeline():
    global pipeline, _write_lock
    if pipeline is not None:
        return pipeline
    _log.info("[DEBUG] Pipeline 未初始化，等待锁...")
    async with _write_lock:
        _log.info("[DEBUG] 获取锁成功，开始初始化 Pipeline")
        if pipeline is not None:
            _log.info("[DEBUG] Pipeline 已被其他线程初始化")
            return pipeline
        pipeline = Pipeline()
        _log.info("[DEBUG] Pipeline 初始化完成")
    return pipeline
```

---

### RISK-3: LLM 返回格式异常

**现象**: `json_repair` 被频繁调用，说明 LLM 输出经常不是合法 JSON

**代码位置**:
- [api_requests.py:140-142](file:///Users/woman/Desktop/AI_Study/18-项目实战：企业知识库/RAG-PRA/Backend/src/api_requests.py#L140-L142)
- [reranking.py:120-122](file:///Users/woman/Desktop/AI_Study/18-项目实战：企业知识库/RAG-PRA/Backend/src/reranking.py#L120-L122)
- [questions_processing.py:466-469](file:///Users/woman/Desktop/AI_Study/18-项目实战：企业知识库/RAG-PRA/Backend/src/questions_processing.py#L466-L469)

**假设**: `enable_thinking: False` 在某些模型版本上不生效，LLM 在 JSON 前输出思考过程

**调试插桩建议**: 在 `chat_json` 和 `answer_stream` 的 JSON 解析失败处记录原始 LLM 输出：

```python
try:
    parsed = json.loads(raw)
except json.JSONDecodeError:
    _log.warning("[DEBUG] JSON 解析失败, 原始输出前500字符: %s", raw[:500])
    parsed = json.loads(repair_json(raw))
```

---

### RISK-4: FAISS 索引维度不匹配

**现象**: 当 Embedding 模型更换后，新构建的向量维度与已有索引不一致

**假设**: 系统未校验 FAISS 索引维度与当前 Embedding 模型的一致性

**代码位置**: [retrieval.py:74-80](file:///Users/woman/Desktop/AI_Study/18-项目实战：企业知识库/RAG-PRA/Backend/src/retrieval.py#L74-L80)

**调试插桩建议**: 在加载 FAISS 索引时记录向量维度，并在检索时校验查询向量维度是否匹配：

```python
# 加载时
_log.info("[DEBUG] FAISS 索引 %s: 维度=%d, 向量数=%d", db_name, index.d, index.ntotal)

# 检索时
if query_emb.shape[0] != index.d:
    _log.error("[DEBUG] 维度不匹配: 查询=%d, 索引=%d", query_emb.shape[0], index.d)
    continue
```

---

## 三、关键路径调试插桩方案

### 3.1 完整问答流程追踪

为端到端追踪问答请求，建议在 `server.py` 中为每个请求分配唯一 `trace_id`：

```python
import uuid

@app.post("/api/answer/stream")
async def answer_stream(request: Request, body: AnswerRequest):
    trace_id = str(uuid.uuid4())[:8]
    _log.info(f"[TRACE:{trace_id}] 开始流式问答: question={body.question[:50]}")
    # ... 传递 trace_id 到各步骤日志
```

### 3.2 性能瓶颈定位

当前各步骤已有耗时日志，但缺少以下关键指标：

| 缺失指标 | 插桩位置 | 建议阈值 |
|---------|---------|---------|
| Embedding API 调用耗时 | `retrieval.py:_embed_query` | > 3s |
| BM25 搜索耗时 | `retrieval.py:_bm25_search` | > 1s |
| FAISS 搜索耗时 | `retrieval.py:_faiss_search` | > 0.5s |
| LLM 单批次评分耗时 | `reranking.py:_score_batch` | > 10s |
| JSON 解析失败率 | `api_requests.py:chat_json` | > 10% |

### 3.3 内存使用监控

`Retriever` 在启动时加载所有索引到内存，建议增加内存使用日志：

```python
import psutil

def _log_memory_usage():
    process = psutil.Process()
    mem_mb = process.memory_info().rss / 1024 / 1024
    _log.info("[MEMORY] 当前进程内存: %.1f MB", mem_mb)
```

---

## 四、调试环境配置建议

### 4.1 日志级别调整

开发/调试环境建议在 `.env` 中增加：

```
LOG_LEVEL=DEBUG
```

当前 `logger.py` 硬编码为 `logging.INFO`，建议改为可配置：

```python
import os
level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
```

### 4.2 请求重放机制

为便于复现问题，建议在 `server.py` 中增加请求日志记录（可选开关）：

```python
# 记录完整请求参数到调试日志
if os.getenv("DEBUG_LOG_REQUESTS") == "1":
    _log.debug("[REQUEST] %s %s", request.method, request.url.path)
```

---

## 五、故障速查表

| 故障现象 | 可能根因 | 快速定位 | 修复方案 |
|---------|---------|---------|---------|
| 流式问答失败: 'data' | OpenAI SDK chunk.choices 为空 | `api_requests.py:chat_stream` | 增加 `if not chunk.choices: continue` |
| 流式问答失败: 403 | DashScope 免费额度耗尽 | 检查 `.env` 中 API Key 状态 | 充值或切换付费模式 |
| 重排序耗时 > 15s | API 限流或批次过大 | `reranking.py:rerank` 日志 | 减小 `rerank_batch_size` 或增加超时 |
| 检索无结果 | 索引未构建或维度不匹配 | `retrieval.py` 加载日志 | 重新构建索引 |
| JSON 解析失败 | LLM 输出非标准 JSON | `api_requests.py` raw 输出 | `json_repair` 已兜底，优化 Prompt |
| 重启脚本不存在 | `restart.sh` 未部署 | 项目根目录检查 | 创建 `restart.sh` |
| Pipeline 初始化慢 | 索引文件过多 | 启动日志 | 考虑懒加载索引 |

---

## 六、总结

### 已确认故障 (4 个)

| ID | 故障 | 严重程度 | 状态 |
|----|------|---------|------|
| BUG-1 | 流式问答 KeyError 'data' | HIGH | 待修复 |
| BUG-2 | LLM 403 额度耗尽无友好提示 | MEDIUM | 待修复 |
| BUG-3 | 重启脚本不存在 | LOW | 待部署 |
| BUG-4 | retrieve() 参数不匹配 | LOW | 可能已修复 |

### 潜在风险 (4 个)

| ID | 风险 | 严重程度 | 建议优先级 |
|----|------|---------|-----------|
| RISK-1 | 重排序耗时过长 | MEDIUM | P1 |
| RISK-2 | Pipeline 单例竞态 | MEDIUM | P2 |
| RISK-3 | LLM 返回格式异常 | LOW | P3 |
| RISK-4 | FAISS 维度不匹配 | LOW | P3 |

### 优先修复建议

1. **立即修复 BUG-1**: `chat_stream` 中增加 `chunk.choices` 空值检查，这是最高频的运行时错误
2. **尽快修复 BUG-2**: 增加对 403 错误的友好提示，改善用户体验
3. **中期优化 RISK-1**: 为重排序增加超时和降级机制，避免单次请求耗时过长
4. **长期改进**: 引入 trace_id 全链路追踪和可配置日志级别
