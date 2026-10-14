# chapter12 规范（Spec）—— Web 服务化部署与生产级工程实践

> **文件性质**：SDD（Specification-Driven Development）规范文档
> **对应源码**：`chapter12/` 下 7 个 `.py` 文件（共 2926 行）
> **编写依据**：逐文件通读源码后提炼，契约字段均来自代码事实，未臆造
> **状态**：v1.0 ｜ 2026-10-14

---

# 上篇：意图与学习路径

## 1. 本章意图（Why）

第 12 章回答一个前 11 章都没回答的问题：**当智能体不再是"我电脑上跑的一个脚本"，而是一个要对多个用户提供服务的线上系统时，需要补哪些工程能力？**

前 11 章关注的是"智能体能不能用"；本章关注的是"智能体能不能**上线**"。两者的差别不是技术栈换了，而是**约束变了**：

| 维度 | 第 1~11 章（单机脚本） | 第 12 章（线上服务） |
|---|---|---|
| 调用方 | 只有自己 | 未知的多个用户 |
| 失败代价 | 报错重跑 | 用户看到 500 / 额度被刷爆 |
| 性能 | 能跑就行 | 并发、延迟、排队、限流 |
| 安全 | 不关心 | 认证、传输加密、安全头 |
| 可观测 | print | 结构化日志 + 健康检查 + 统计指标 |

> 📌 与五模块架构的对应：本章是**横切支撑层**的集中实现——编排调度（12-03 异步/12-06 队列）、安全对齐（12-02 四层防御）、可观测评估（12-01 日志/12-05 容错统计）、成本限流（12-04 缓存/12-06 令牌桶）。它相当于把第 13 章的系统"搬到线上"所必须补的那一层。

## 2. 学习路径（按源码顺序）

| 顺序 | 文件 | 行数 | 学什么 | 掌握后应该能回答 |
|---|---|---|---|---|
| 1 | `01_web服务记录日志并发.py` | ~309 | Flask 服务骨架：日志 + 并发观测 + `/health` | 为什么"云端 API 化"之后不再需要 `model_lock`？ |
| 2 | `02_web服务部署环境安全架构手段.py` | ~334 | 安全纵深防御四层：HTTPS / 认证 / 限流 / 安全头 | 为什么认证优先级高于限流和加密？ |
| 3 | `03_API负载均衡与异步任务调度.py` | ~388 | 异步任务（提交-轮询）+ 轮询负载均衡 + 状态持久化 | 提交接口为什么立即返回 202 而不是等结果？ |
| 4 | `04_多层级缓存与记忆系统.py` | ~366 | 三层记忆：短期缓存 / 长期知识库 / 跨模型共享 | 会话历史为什么能从 qwen 共享给 qwen-turbo？ |
| 5 | `05_智能体容错机制实现.py` | ~345 | 容错五件套：超时 / 退避重试 / 切换 / 熔断 / 降级 | 熔断相比"无限重试"省下了什么？ |
| 6 | `06_高并发的限流与降级策略.py` | ~523 | 令牌桶限流 + 优先级队列削峰 + worker 池 | 令牌桶"读-扣-写"为什么必须原子？ |
| 7 | `07_模拟mcp服务与coze调用.py` | ~661 | 真实 MCP 规范服务端 + Coze Bot 编排模拟 | MCP 为什么把上下文当"资源"而非"消息"？ |

**建议学习方式**：12-01 是模板（日志/健康检查骨架），12-02~12-06 都在它之上加一层能力，建议顺序读；12-07 相对独立（协议层），可先跳过，第 13 章读 MCP 时再回来看。**每篇都跑 `python <file>` 看 self-test——本篇的价值全在"故障是否真的被触发验证"**。

## 3. 本章的工程主线：从"能跑"到"上线"的六件事

本章 7 个文件覆盖了把一个 LLM 服务推上线所必须补的六类工程能力。这是本章最值得带走的知识结构：

| # | 工程能力 | 本篇 | 核心手段 | 教材缺失点 |
|---|---|---|---|---|
| 1 | **可观测** | 12-01 | 结构化日志（request_id + 耗时 + token）+ `/health` | 配了 logging 却一行都没打 |
| 2 | **安全** | 12-02 | HTTPS → API Key → 限流 → 安全响应头（由外到内） | 完全没有认证，API 裸奔 |
| 3 | **异步与扩展** | 12-03 | 提交-轮询 + RoundRobin 分发 + 状态落盘 | 标题承诺"负载均衡"却零实现 |
| 4 | **记忆分层** | 12-04 | 短期 session / 长期知识库 / 跨模型共享 | Redis 依赖 + 本地 GPU，跑不起来 |
| 5 | **容错** | 12-05 | 超时 + 指数退避 + 切换 + 熔断 + 降级 | 重试内重加载模型；无熔断 |
| 6 | **高并发保护** | 12-06 | 令牌桶 + 优先级队列 + worker 池 + 背压 | 桶初始为空 + 非原子 + 单 worker |

> ⚠️ **最值得记住的三条**：
> 1. **API 化 = 并发难题外移**（12-01 的核心洞察）。教材本地 GPU 推理必须用 `model_lock` 串行化（显存限制）；改用云端 API 后，并发压力交给服务商，服务端只需关注自己的并发水位。这就是"部署"的价值之一。
> 2. **容错代码必须被故障验证**（12-05）。教材写了重试/切换/降级，但 `run_demo` 只演示 happy path——容错代码从未被触发过，等于不知道灵不灵。改写引入**故障注入后端** `FaultyBackend`，让每种机制在 self-test 中真实触发。
> 3. **限流的原子性**（12-06）。令牌桶的"读令牌 → 判断 → 扣减"三步若不是原子操作，并发时会读到同一令牌数、把桶扣成负数。Redis 用 Lua 脚本；单进程用 `threading.Lock`。

## 4. 学习检查清单

- [ ] 能说清"本地 GPU 推理需要锁、云端 API 不需要锁"的原因
- [ ] 能画出安全纵深防御的四层顺序，并解释为什么是这个顺序
- [ ] 能解释异步任务为什么用"提交-轮询"而不是"长连接等结果"
- [ ] 能说明 `session://{id}/history` 这种 URI 在 MCP 里代表什么
- [ ] 能解释指数退避 `0.5 × 2^attempt` 为什么比"立即重试"对故障服务更友好
- [ ] 能说清熔断器的三种状态（闭合/打开/半开）及转换条件
- [ ] 能解释优先级队列为什么用 `(priority, seq)` 而不是 `(priority, time)`
- [ ] 能说出本章所有 `cache.json` 的五种用途（会话历史 / 向量 / 任务状态 / 令牌桶 / MCP 会话）

---

# 下篇：契约与验收

## 5. 统一技术约束（Global Constraints）

本章 7 个文件共享同一套硬约束：

```
C-01  Web 框架：Flask（教材用 FastAPI，本系列统一 Flask，异步模式与框架无关）
C-02  模型接入：dashscope 原生协议为主；跨模型演示走 OpenAI 兼容模式
C-03  模型名：qwen-plus（主力）/ qwen-turbo（备用）；DeepSeek 槽位保留可改回
C-04  密钥来源：DASHSCOPE_API_KEY（环境变量）；AGENT_API_KEY（12-02 认证用）
C-05  必需参数：result_format='message'
C-06  响应路径：resp.output.choices[0].message.content
C-07  状态码校验：resp.status_code != 200 → 抛 RuntimeError
C-08  持久化：一律用运行目录 cache.json（本项目环境无 Redis，按约定替代）
C-09  日志：控制台 + 文件双输出（12-01 起），格式 "%(asctime)s [%(levelname)s] %(message)s"
C-10  入口：main 后台线程启动服务 → self-test → sys.exit(0/1)，服务用 daemon 线程
C-11  服务化必备：每个服务都提供 /health 健康检查端点
C-12  运行前置：DASHSCOPE_API_KEY 已设置；flask / flask-limiter / requests 已安装
```

> 📌 **关于 Redis 的统一约定**：教材 12-03/04/06/07 都依赖 Redis，但本环境无 Redis。全章统一用 `cache.json` 承接 Redis 的持久化职责。**生产多实例部署时应改回 Redis**（限流需 `storage_uri="redis://..."`，任务队列升级为 Celery/RQ）。

## 6. 逐文件契约

### F-01 `01_web服务记录日志并发.py`（可观测基线）

| 项 | 契约 |
|---|---|
| **意图** | 建立 Flask 服务骨架：OpenAI 兼容端点 + 结构化日志 + 并发观测 |
| **端点** | `GET /health`（状态 + 并发统计）；`POST /v1/chat/completions` |
| **请求契约** | `{"messages": [...], "max_tokens": 512, "temperature": 0.7}`；非法 JSON → 400；`messages` 空 → 400 |
| **响应契约** | **OpenAI 兼容格式**：`{id: "chatcmpl-{rid}", object: "chat.completion", created, model, choices[{index,message,finish_reason}], usage{prompt_tokens,completion_tokens,total_tokens}}`（vLLM/Ollama 行业标准） |
| **日志契约** | 每请求打 3 行：请求开始（含并发数）/ 请求完成（含耗时 ms + token 用量）；同时写控制台与 `agent_server.log` |
| **并发契约** | `_stats = {total, active, max_active}`；`max_active` 峰值即并发水位；计数 ±1 必须包在 `threading.Lock` 内，`-1` 放 `finally` |
| **⚠️ 教材 bug（注释实录）** | `torch.time.time()` —— **torch 没有 time 模块**，应为 `time.time()`；且本地加载 `Qwen/Qwen3-7B` + `.cuda()` 需约 15GB 显存 |
| **关键洞察** | 教材用本地 GPU 推理需 `model_lock` 串行化；改用云端 API 后并发交给服务商——**这就是"部署"的核心价值之一** |
| **验收标准** | self-test 4 项：`/health` 可达 / 单请求 / 并发 3 请求全成 / `max_active >= 3`（证明真并发非串行） |

### F-02 `02_web服务部署环境安全架构手段.py`（安全纵深防御）

| 项 | 契约 |
|---|---|
| **意图** | 安全纵深防御四层，**由外到内**：传输加密 → 认证 → 限流 → 安全响应头 |
| **第 1 层 传输加密** | HTTPS，`ssl_context="adhoc"`（Flask 内置自签名证书，需 cryptography 库）；生产替换正式证书 |
| **第 2 层 认证** | `@require_api_key` 装饰器；支持 `X-API-Key` 头或 `Authorization: Bearer <key>`；缺失/错误 → **401** |
| **第 3 层 限流** | `flask-limiter`，`@limiter.limit("5 per minute")`（教学值设小便于验证）；超限 → **429**；`storage_uri="memory://"`（生产多实例改 redis） |
| **第 4 层 安全响应头** | `@app.after_request` 统一附加：`X-Content-Type-Options: nosniff` / `X-Frame-Options: DENY` / `Referrer-Policy: no-referrer` / `Content-Security-Policy: default-src 'none'` |
| **恒时比较** | 认证用 `secrets.compare_digest(key, API_KEY)` —— 防时序攻击逐位猜 Key |
| **输入限制** | `max_tokens` 上限截断 1024；`messages` 不得超 20 条（防资源滥用） |
| **⚠️ 教材问题（注释实录）** | ① `cert.pem/key.pem` 凭空出现（不存在必报错）；② `ProxyFix(app.wsgi_app)` **无参数调用**默认全 0，等于没生效（正确：`x_for=1, x_proto=1, x_host=1`）；③ **完全无认证**，API 裸奔 |
| **优先级洞察** | 认证是安全第一道防线，**优先级高于限流和加密** |
| **验收标准** | self-test 4 项：HTTPS 可达 / 无 Key → 401 / 带 Key → 200（真实调用）/ 连发触发 429 |

### F-03 `03_API负载均衡与异步任务调度.py`（异步 + 负载均衡）

| 项 | 契约 |
|---|---|
| **意图** | 把耗时 LLM 调用异步化（提交-轮询），并补上教材承诺但未实现的负载均衡 |
| **端点** | `GET /health`；`POST /generate`（提交）；`GET /result/<task_id>`（查询） |
| **提交契约** | `{"prompt": str}` → `202 {"task_id", "status": "PENDING"}`（**立即返回，不阻塞**） |
| **查询契约** | `{"status": "pending"/"processing"/"completed"/"failed", "instance", "result"}`；不存在 → 404 |
| **状态机契约** | `PENDING → PROCESSING → COMPLETED / FAILED`（教材 Celery 语义保留） |
| **负载均衡契约** | `RoundRobinRouter`：`threading.Lock` 保护 `_index`，把任务交替分给 `instance-0` / `instance-1`；`stats()` 返回分发计数（验证流量均匀） |
| **持久化契约** | `cache.json` 替代 Redis backend；`_load_cache()` 启动时恢复历史任务；**重启后仍可查询** |
| **⚠️ 教材问题（注释实录）** | ① Celery 依赖 `redis://localhost:6379`（本环境无 Redis）；② Celery 4+ 在 Windows 官方不支持，教学难跑；③ 双文件（main.py + tasks.py）无法单文件验证；④ **标题承诺"负载均衡"但代码零实现** |
| **生产演进提示** | 单进程线程池 + 文件状态适用于教学/单机；多机水平扩展应升级 Celery/RQ + Redis，负载均衡用 Nginx/云 SLB |
| **验收标准** | self-test 4 项：提交立即返回 / 轮询至完成 / 并发 4 任务轮询分发均匀（两实例都被用）/ `cache.json` 落盘验证 |

### F-04 `04_多层级缓存与记忆系统.py`（三层记忆架构）

| 项 | 契约 |
|---|---|
| **意图** | 构建三层记忆：短期会话缓存 / 长期知识库 / 跨模型记忆共享 |
| **层级 1 短期缓存** | `JSONCache` 落盘 `cache.json`，结构 `{"sessions": {sid: [{"role","content"}]}, "vectors": {...}}`；`append_history`（等价 Redis rpush）/ `get_history`（等价 lrange 0 -1） |
| **层级 2 长期知识库** | `text-embedding-v3`（1024 维）+ 纯 Python 余弦相似度 top-k（`TOP_K=2`）；**向量也缓存落盘**，缺失分块才调 API |
| **层级 3 跨模型共享** | 同 `session_id` 的历史同时注入**两个不同后端**（`backend_a`: qwen-plus 原生 / `backend_b`: qwen-turbo OpenAI 兼容）；对话 2 的"它"能指代对话 1 |
| **知识库内置** | `KNOWLEDGE_TEXT` 内置（替代教材缺失的 `sample_knowledge.txt`），主题为 Transformer/Self-Attention |
| **分块契约** | `split_text(text, chunk_size=120)`：按行聚合（教材用 langchain 切分器） |
| **⚠️ 教材问题（注释实录）** | ① `import redis`；② `Qwen2Chat`/`DeepSeekChat` 虚构类 + `ConversationBufferMemory`/`ConversationalRetrievalChain` 已废弃；③ 本地 GPU 模型（Qwen1.5-14B, device="cuda"）；④ `sample_knowledge.txt` 凭空出现；⑤ HuggingFaceEmbeddings 需下 90MB 本地模型 |
| **设计价值** | 记忆由 `cache` 统一管理，与模型解耦——**同一份历史换模型照样能读** |
| **验收标准** | self-test 4 项：知识库语义检索命中 / qwen-plus 对话 + 历史落盘（2 条）/ qwen-turbo 接续（历史 4 条，证明跨模型共享）/ 会话隔离（新 session 历史为空） |

### F-05 `05_智能体容错机制实现.py`（容错五件套）

| 项 | 契约 |
|---|---|
| **意图** | 构建"打不死"的智能体：超时 + 指数退避重试 + 自动切换 + 熔断 + 优雅降级 |
| **① 超时控制** | `ThreadPoolExecutor` + `future.result(timeout=self.timeout)`；超时抛 `FutureTimeout`（教材机制保留） |
| **② 指数退避** | 间隔 = `backoff_base × 2^attempt`（0.5s → 1s → 2s）；给故障服务喘息窗口 |
| **③ 自动切换** | 后端列表顺序尝试（`qwen-plus` 原生 → `qwen-turbo` 兼容模式） |
| **④ 熔断器** | `CircuitBreaker(threshold=2, cooldown=30.0)`：连续 2 次失败 → 打开；冷却后半开试探；打开期间 `allow()` 返回 False，上层直接跳过 |
| **⑤ 优雅降级** | 全部后端失败 → `FALLBACK_MSG = "很抱歉，我暂时无法回答您的问题，请稍后再试。"` |
| **故障注入契约** | `FaultyBackend(name, fail_times=N, forever=Bool)`：可控模拟"抛异常"故障，让每种容错机制真实触发 |
| **可观测契约** | `stats = {name: {ok, fail, skip}}` 三计数器 |
| **⚠️ 教材问题（注释实录）** | ① 全部虚构类/废弃 API/本地 GPU；② **`load_model` 在重试循环内调用**——每次重试重新加载大模型（几十秒），让"重试"本身成为灾难；③ **重试无退避**；④ **无熔断**；⑤ 故障从未被触发（`run_demo` 只走 happy path） |
| **验收标准** | self-test 5 项：正常调用 / 主后端故障切换 backup / 首次失败重试成功（fail_times=1）/ 全后端故障降级 / **熔断验证**（连续失败打开 → 第三问直接跳过 `skip >= 1`） |

### F-06 `06_高并发的限流与降级策略.py`（限流 + 削峰）

| 项 | 契约 |
|---|---|
| **意图** | 高并发下的稳定性保护：令牌桶限流 + 优先级队列削峰 + worker 池 + 降级链 |
| **端点** | `GET /health`（含桶令牌数 + 队列长度 + 统计）；`POST /chat` |
| **请求契约** | `{"message": str, "priority": 0(高)/1(默认)}`；响应 `200` 结果 / `429` 限流 / `503` 队列满 / `504` 超时 |
| **令牌桶契约** | `TokenBucket(capacity=5, refill_rate=2/s)`：**初始满桶**（教材初始 0 → 首批请求全被拒）；**`threading.Lock` 保证"读-扣-写"原子**（教材 `get/decr` 分离有竞态，会把桶扣成负数）；惰性按时间补充；状态落盘 `cache.json`（防重启回满绕过限流） |
| **优先级队列契约** | `queue.PriorityQueue(maxsize=20)`；条目 `PriorityEntry` 用 **`(priority, seq)`** 排序——`seq` 单调递增（`itertools.count`）保证同级 FIFO 且比较稳定（用 `(priority, time)` 在同秒内不稳定） |
| **Worker 池契约** | `WORKER_COUNT=2` 消费者线程（教材单 worker 是吞吐瓶颈）；异常时也回填结果（`finally: entry.event.set()`），**不让请求挂死** |
| **结果桥接契约** | 请求线程经 `threading.Event` 等待 worker 完成；`wait(timeout=60)` |
| **降级链契约** | `qwen-plus` → `qwen-turbo` → `FALLBACK_MSG = "系统繁忙，请稍后再试。"` |
| **⚠️ 教材问题（注释实录）** | ① Redis 令牌桶；② 桶初始为空 + 非原子；③ 虚构类/废弃 API；④ `@app.on_event("startup")` 已被 FastAPI 废弃；⑤ 单消费者吞吐 ~0.5 req/s，队列必然积压；⑥ **限流/削峰/优先级/降级全部零验证**；⑦ worker 异常退出后 future 永远 pending |
| **验收标准** | self-test 6 项：正常流 / **并发突发 429**（10 线程，需注入本地假 LLM 加速消耗）/ 令牌按速率恢复 / 优先级插队（三线程错峰，high 早于 low-2 完成）/ 降级实测（坏模型名）/ 队列指标可观测 |

### F-07 `07_模拟mcp服务与coze调用.py`（真实 MCP + Coze 编排）

| 项 | 契约 |
|---|---|
| **意图** | 按**真实 MCP 2025-06-18 规范**实现服务端，并模拟扣子（Coze）Bot 的 MCP 集成工作流 |
| **协议常量** | `MCP_PROTOCOL_VERSION = "2025-06-18"`；错误码 `-32700`（Parse error）/ `-32601`（Method not found）/ `-32602`（Invalid params） |
| **Server 契约** | `McpServer.handle(raw: str) -> str`：JSON-RPC 2.0 单入口；分发 `initialize` / `tools/list` / `tools/call` / `resources/list` / `resources/read`；**notification（无 id）返回空串** |
| **initialize 契约** | 返回 `{protocolVersion, capabilities{tools, resources}, serverInfo{name, version}}` |
| **tools 原语** | `search_knowledge` 工具，`inputSchema` 为标准 JSON Schema；`tools/call` 结果包装为 `{content: [{type:"text", text}], isError}` |
| **resources 原语** | 会话历史以 URI **`session://{sid}/history`** 暴露；`resources/read` 返回 `{contents: [{uri, mimeType, text}]}`——**真实 MCP 把上下文当"资源"而非"消息前缀"** |
| **Client 契约** | `McpClient`：请求 id 自增；`initialize()` 后必须发 `notifications/initialized` 通知（规范要求）；响应含 error 抛 `RuntimeError` |
| **CozeBot 契约** | 工作流：**先写 user 历史**（修复教材顺序 bug）→ MCP 工具检索知识 → 组装上下文（system 知识增强 + 完整历史）→ qwen-plus 生成 → 回写 assistant |
| **⚠️ 教材问题（注释实录）** | ① `import redis`；② 虚构类/废弃 API；③ HuggingFaceEmbeddings + Chroma（`./chroma_db/` 空库也能"检索成功"）；④ `memory.chat_memory.messages = history` 直接注入绕开截断；⑤ **"MCP 协议层"名不副实**——只是把消息存 Redis 并给键加 `mcp:` 前缀，与真实 MCP 毫无关系；⑥ **"Coze 调用"凭空**——真实扣子通过注册"MCP 扩展"集成外部工具；⑦ user 消息在 `qa_chain.run()` 之后才写缓存（顺序 bug） |
| **容错契约** | 知识库 embedding 不可用时**降级为空结果**（不向外抛）；LLM 调用失败返回"（系统繁忙，请稍后再试。）" |
| **传输层说明** | 教学用进程内消息传递（协议层与传输层解耦是 MCP 设计要点）；生产用官方 `mcp` SDK 跑 stdio / Streamable HTTP |
| **验收标准** | self-test 6 项：initialize 握手 / tools/list 清单 / tools/call 真实检索 / Coze 两轮对话（RoPE 承接）/ resources 读取历史（角色顺序 user,assistant,user,assistant）/ 三种错误码 |

## 7. 全章验收清单

| # | 验收项 | 判定方式 |
|---|---|---|
| V-01 | 7 个文件均可独立执行（`python <file>`） | 无 ImportError，服务经 daemon 线程启动，`sys.exit(0)` |
| V-02 | 5 个 Web 服务（12-01/02/03/06/07 中的服务型）均提供 `/health` | 静态 + 实跑 |
| V-03 | 均使用 dashscope 原生协议 + `result_format='message'` | 静态检查 |
| V-04 | 均含 `status_code != 200` 校验 | 静态检查 |
| V-05 | 所有持久化均用 `cache.json`，无 Redis/Chroma 依赖 | 静态检查 |
| V-06 | 均无 `torch.time.time()` 等教材 bug | 静态检查 |
| V-07 | 12-02 四层防御全部实跑验证：HTTPS 可达 / 401 / 200 / 429 | 实跑观察 |
| V-08 | 12-05 五种容错机制全部被故障注入触发 | 实跑观察 |
| V-09 | 12-06 令牌桶初始满桶 + 并发突发触发 429 + 优先级插队生效 | 实跑观察 |
| V-10 | 12-07 MCP 三种错误码（-32700/-32601/-32602）全部正确 | 实跑观察 |
| V-11 | 所有服务型文件均通过全部 self-test | 实跑观察 |
| V-12 | 12-04 跨模型记忆共享：第二模型读到第一模型写入的 4 条历史 | 实跑观察 |

## 8. 已知缺口（Gap Analysis）

本章是"教学版生产化"。以下为真实上线还需要的，教材与本章均未覆盖：

| 缺口 | 说明 | 生产应补 |
|---|---|---|
| **真实证书** | 12-02 用 adhoc 自签名证书 | 正式 CA 证书 + 自动续期 |
| **集中式限流** | 内存存储，进程内计数，多实例不共享 | Redis `storage_uri="redis://..."` |
| **真实任务队列** | 单进程线程池 + 文件状态 | Celery/RQ + Redis，或云 MNS/SQS |
| **真实负载均衡** | 进程内 RoundRobin 模拟 | Nginx / 云 SLB 多实例 upstream |
| **容器化/编排** | 无 | Docker + K8s |
| **可观测平台** | 仅文件日志 | Prometheus + Grafana / 链路追踪 |
| **真实 MCP 传输** | 进程内 `handle(str)` | 官方 `mcp` SDK + stdio / Streamable HTTP |
| **真实 Coze 集成** | CozeBot 为编排模拟 | 扣子平台注册 MCP 扩展（填 MCP 服务 URL） |
| **灰度/回滚** | 无 | 发布策略与版本管理 |

> 📌 **写作纪律**：本章 spec 严格以代码事实为准。教材问题与实测踩坑（`torch.time` bug、ProxyFix 无参、令牌桶非原子、优先级队列 seq 必要性）均如实收录。

---

**版本记录**

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-10-14 | 首版：7 文件全覆盖，上篇意图/学习路径 + 下篇契约/验收 |
