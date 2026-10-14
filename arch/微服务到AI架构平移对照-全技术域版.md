# 微服务（Java/SpringBoot） → AI Agent（Python）全技术域平移对照手册

> **这是第二版、更全面的对照表**。第一版 `微服务到AI架构平移对照.md` 只覆盖了"分层架构"一个视角；
> 本手册按 **20 个技术域** 逐一穷举对照，覆盖绝大多数工程场景，并额外补上 **Java ↔ Python 语言/生态层面**的差异。
>
> 阅读对象：SpringBoot 微服务架构师（Java 栈）→ 转 AI Agent 开发（Python 栈）。
> 配套：`ch02-六层架构详图.svg`、`ch10-A2A六层架构详图.svg`、`ch12-七层组件栈详图.svg`、`全书架构汇总.md`

---

## 〇、先看结论：三种平移状态

全书 13 章的技术点，按"能否平移"分三类：

| 状态 | 含义 | 数量 | 代表 |
|---|---|---|---|
| 🟢 **直接平移** | 概念一一对应，换个库/换个名字即可 | ~60% | 网关、限流、熔断、可观测、鉴权、连接池、序列化 |
| 🟡 **需要重构** | 概念对应但机制变了，要重新设计 | ~25% | 编排（控制反转）、一致性、幂等、测试、缓存 |
| 🔴 **全新领域** | 微服务里没有对应物，必须从零学 | ~15% | RAG/向量检索、上下文工程、Token 成本、Prompt 工程、幻觉治理 |

> **一句话**：你的**基础设施经验（后 40%）几乎全额可用**，**业务编排经验（中间 30%）要重构**，**AI 特有部分（前 30%）是新大陆**。

---

## 一、基础映射总表（20 个技术域）

| # | 技术域 | 微服务（Java） | AI Agent（Python） | 状态 |
|---|---|---|---|---|
| 1 | **开发语言** | Java 17+ | Python 3.10+ | 🔴 语言换栈 |
| 2 | **Web 框架** | Spring Boot / WebFlux | FastAPI / Flask | 🟢 |
| 3 | **依赖注入（DI）** | Spring IoC / `@Autowired` | 无 DI 容器（手工组装 / Pydantic） | 🟡 |
| 4 | **配置管理** | `application.yml` + Nacos Config | 环境变量 + `.env` / pydantic-settings | 🟡 |
| 5 | **服务注册发现** | Nacos / Eureka / Consul | Agent Card 目录（A2A） | 🟡 |
| 6 | **网关** | Spring Cloud Gateway | Flask/FastAPI 中间件 + 反向代理 | 🟢 |
| 7 | **服务调用** | Feign / RestTemplate / Dubbo | Function Calling + MCP | 🟡 反转 |
| 8 | **消息/事件** | Kafka / RocketMQ / RabbitMQ | A2A Pub/Sub / Redis Stream | 🟢 |
| 9 | **缓存** | Redis / Caffeine | Redis / 语义向量缓存 | 🟡 |
| 10 | **数据库** | MySQL / PostgreSQL / MyBatis | 同 + 向量数据库（FAISS/Milvus） | 🔴 新增向量库 |
| 11 | **事务与一致性** | `@Transactional` / Seata / SAGA | 无原生事务，靠幂等 + 补偿 | 🔴 需重学 |
| 12 | **限流熔断降级** | Sentinel / Hystrix / Resilience4j | 手写令牌桶 + 熔断器 + 降级链 | 🟢 |
| 13 | **可观测** | Micrometer / SkyWalking / ELK | OpenTelemetry / LangSmith / Langfuse | 🟢 |
| 14 | **鉴权安全** | Spring Security / JWT / OAuth2 | API Key / Bearer Token（A2A） | 🟢 |
| 15 | **内容安全** | （一般无） | 敏感词 Trie + 置信度 logprobs | 🔴 新增 |
| 16 | **异步/并发** | `@Async` / CompletableFuture / 线程池 | ThreadPool / asyncio | 🟢 |
| 17 | **任务调度** | XXL-Job / Quartz / `@Scheduled` | 优先级队列 + Worker 池 / DAG 调度 | 🟡 |
| 18 | **测试** | JUnit / Mockito / Testcontainers | pytest / 真实调用 / LLM-as-a-Judge | 🔴 断言方式变 |
| 19 | **构建部署** | Maven/Gradle + Docker + K8s | pip/uv + Poetry + Docker + K8s | 🟡 |
| 20 | **API 文档** | Swagger / OpenAPI | OpenAPI / MCP Schema / Agent Card | 🟢 |

---

## 二、逐域详表（重点域展开）

### 域 1：语言栈 Java → Python（🔴 换栈，但不难）

| 维度 | Java | Python | 备注 |
|---|---|---|---|
| 类型系统 | 强静态类型（编译期检查） | 动态类型（运行期）→ **用类型注解 + Pydantic 补回** | Agent 里 Pydantic 承担了 DTO + 校验 |
| 空值 | `Optional<T>` / `null` | `None` + `Optional[T]` | 同样的空指针噩梦 |
| 并发 | Thread + `synchronized` / 虚拟线程 | GIL 限制 → **多进程 / asyncio / Thread（IO 密集）** | ⚠️ GIL 是新坑：CPU 密集必须多进程 |
| 包管理 | Maven / Gradle | pip / uv / Poetry（推荐 uv） | 无中央仓库，注意版本冲突 |
| 异常 | Checked/Unchecked | 全部 Unchecked → **"错误是数据"更自然** | 与 Agent 的错误哲学天然吻合 |
| 并发容器 | `ConcurrentHashMap` | `queue.Queue`（线程安全）/ `collections` | 项目里用 `threading.Lock` 护临界区 |
| 字符串/列表推导 | Stream API（`map/filter/collect`） | 列表推导 / 生成器（`[x for x in ...]`） | 表达力相当，Stream 更啰嗦 |
| 不可变数据 | `record` / `final` | `dataclass(frozen=True)` / tuple | Agent 里"工具返回不可变"是好习惯 |

**项目实证**：ch09 用 `Thread + Lock` 实现并发安全三原则（能隔离就不共享 → 能免锁就不手写锁 → 必须共享才用 Lock）；ch12 用 `ThreadPoolExecutor + PriorityQueue` 做任务调度。

---

### 域 2：Web 框架（🟢 极易平移）

| SpringBoot | FastAPI / Flask | 项目位置 |
|---|---|---|
| `@RestController` + `@GetMapping` | `@app.get()` / `@app.route()` | ch11 Flask 四个端点 |
| `@PostMapping` + `@RequestBody` | `@app.post()` + `request.get_json()` | ch11 `POST /ask` |
| `@RequestParam` / `@PathVariable` | 函数参数 / `<path:var>` | — |
| `ResponseEntity<T>` | `jsonify()` / `return dict` | ch11 统一 JSON 响应 |
| `@ControllerAdvice` + `@ExceptionHandler` | `@app.errorhandler(404)` | ch11 404/405 handler |
| Actuator `/actuator/health` | 手写 `GET /health` | ch11 self-test Test1 |
| CORS 配置 | `flask-cors` / FastAPI `CORSMiddleware` | ch02-08 CORS |
| Interceptor / Filter | `before_request` / Middleware | ch12-02 API Key 校验 |

**唯一注意**：Flask 开发服务器不能上生产，用 **waitress（Windows）/ gunicorn（Linux）** —— 就是你的 Tomcat 角色。

---

### 域 3：依赖注入与配置（🟡 需要重构）

| SpringBoot | AI Agent（Python） | 说明 |
|---|---|---|
| `@Service` / `@Component` | 普通类 | 无容器，手工 `new` |
| `@Autowired` 字段注入 | 构造函数传参 / 模块级单例 | 依赖更显式 |
| `@Bean` + `@Configuration` | 工厂函数 / 注册表 dict | **注册表模式**是核心 |
| `@Value("${x}")` | `os.getenv("X")` / `pydantic-settings` | ch13 统一读 `DASHSCOPE_API_KEY` |
| `application-{profile}.yml` | `.env` + 环境变量 | 无 profile，用环境变量切换 |
| `@ConditionalOnProperty` | if/else 或注册表判断 | 无声明式条件装配 |

**关键设计模式替换**：Spring 用 **DI 容器** 管理依赖；Agent 用 **注册表（Registry）** 管理可插拔能力：

```python
# Spring: @Autowired 由容器注入
# Agent: 注册表驱动，消灭 if/elif
TOOL_REGISTRY = {"get_weather": get_weather, "query_db": query_db}
fn = TOOL_REGISTRY.get(name)   # 声明即注册，加工具不改调用方
```

**项目实证**：ch13 有五张注册表——`MODEL_REGISTRY` / `TASK_REGISTRY` / `TOOL_REGISTRY` / 意图白名单 / 工具注册表。

---

### 域 5：服务注册发现（🟡 机制变了）

| 微服务 | AI Agent | 差异 |
|---|---|---|
| Nacos / Eureka 注册中心 | **A2A Agent Card 目录** | 无需中心节点，Card 自描述 |
| 服务名 → 实例列表 | Agent Card `skills[]` → 能力清单 | 发现的是**能力**不是"地址" |
| 健康检查心跳 | Agent Card `endpoint` + `/health` | 类似 |
| 负载均衡（Ribbon/LoadBalancer） | 在 Agent 侧按 skills 匹配评分选择 | ch10-06 协商竞标 |
| 元数据（版本/权重/标签） | Agent Card 的 `description` / `skills` | 语义化描述 |

**Agent Card 实例**（ch10-02，≈ Nacos 的服务元数据）：
```json
{
  "name": "flask-chat-agent",
  "description": "...",
  "skills": [{"id":"...", "name":"...", "description":"..."}],
  "endpoint": "http://..."
}
```
> 关键差异：Nacos 的元数据是**给运维看的**；Agent Card 是**给另一个 Agent（模型）看的**——所以描述是自然语言，用于让对方的 LLM 理解能力。

---

### 域 7：服务调用（🟡 控制反转，最核心差异）

| 微服务 | AI Agent | 差异等级 |
|---|---|---|
| Feign 声明式调用（编译期确定） | Function Calling（**运行时由模型决定**） | 🔴 反转 |
| 接口是 Java 方法 | 工具 = JSON Schema 说明书 + 本地执行体 | 🟡 |
| Dubbo RPC | MCP（Agent→Tool，跨进程） | 🟡 |
| 点对点 HTTP | A2A（Agent→Agent） | 🟡 |
| 固定超时/重试 | 工具永不抛异常，错误回传模型 | 🔴 反转 |

**这是全书最重要的一条**：
- 微服务：`OrderService.createOrder()` 是你在代码里写死的调用。
- Agent：模型读到 `tools=[get_weather, query_db, ...]`，**自己决定**这轮调 `get_weather` 还是 `query_db`。

```python
# 微服务思维（错误）
if "天气" in user_input: result = get_weather()
elif "数据" in user_input: result = query_db()

# Agent 思维（正确）：把选择权交给模型
resp = Generation.call(model="qwen-plus", messages=messages, tools=tool_specs)
for call in resp.output.choices[0].message.tool_calls:
    fn = TOOL_REGISTRY[call['function']['name']]   # 模型决定的
    result = fn(**json.loads(call['function']['arguments']))
```

---

### 域 8：消息与事件（🟢 基本平移）

| 微服务 | AI Agent | 项目位置 |
|---|---|---|
| Kafka Topic 订阅 | A2A Pub/Sub（`subscribeToTask` + SSE） | ch10-05 |
| RocketMQ 顺序消息 | PriorityQueue（priority, seq） | ch12-04 |
| 死信队列 | 工具失败 → 错误回传（不丢消息） | ch02/ch13 |
| 事件驱动架构 | 图编排（LangGraph 节点+边） | ch05 |
| 消息体 JSON | JSON-RPC 2.0 信封 | ch10-02 |

**A2A 通信两种模式**（ch10）：
- **Request-Response**（一对一）= 同步 RPC（`Request(id)` → `Response(result)`）
- **Pub/Sub**（一对多）= MQ 广播（`Notification` 无 id，不期待响应）

---

### 域 9-10：缓存与数据库（🟢 + 🔴 向量库新增）

**Redis 用途全平移表**：

| Redis 用途 | AI Agent 对应 | 项目位置 |
|---|---|---|
| Session 会话存储 | 对话记忆 memory | ch02-03、ch08-04 |
| 热点数据缓存 | **提示词缓存**（MD5 精确匹配，17.7x 加速） | ch07-06 |
| — | **语义向量缓存**（embedding 相似度 > 0.95 命中） | ch07/ch12-04 |
| 分布式锁 | 并发会话隔离（同 session_id 串行） | ch09-07 |
| INCR 计数器 / 限流 | 令牌桶限流 TokenBucket | ch12-06 |
| Pub/Sub | A2A Pub/Sub | ch10-05 |
| TTL 过期 | 记忆遗忘 / 上下文压缩 | ch07-07、ch08-05 |

> ⚠️ 你问的关键点：**ch12 教材用 `cache.json` + `threading.Lock` 替代 Redis，且自认"get/decr 三步非原子"是笔学费**。→ 换成真 Redis（`INCR`/`EXPIRE` 或 **Lua 脚本**）就是你的主场。

**数据库：新增"向量数据库"这一全新品类**（🔴）：

| 需求 | 选型 | 类比 |
|---|---|---|
| 原型/小知识库 | **FAISS** | 纯内存，≈ Embedded H2 |
| 轻量 RAG | **Chroma** | 嵌入式 + 持久化，≈ SQLite |
| 生产分布式 | **Milvus / Qdrant / Weaviate** | ≈ MySQL/PG 的生产版 |
| 全文检索 | Elasticsearch | 搜索能力平移 |
| 混合检索 | 向量（语义）+ BM25（关键词） | ch06-09 双通道 |

**向量检索三件套**（ch06 核心公式）：
```
RAG = 检索 + 生成
检索 = 向量化(Embedding) → 索引(FAISS) → 相似度搜索(top-k)
生成 = prompt 装检索结果 → LLM 据上下文回答
```

---

### 域 11：事务与一致性（🔴 必须重学）

| 微服务 | AI Agent | 说明 |
|---|---|---|
| `@Transactional` 本地事务 | ❌ 没有 | LLM 调用无法回滚 |
| Seata AT/TCC | 🟡 手写补偿 | 需要自己实现 |
| SAGA 长事务 | 🟡 状态机 + 补偿步骤 | ch13-04 TASK_REGISTRY |
| 幂等（幂等表/去重键） | 🟡 **副作用工具必须显式幂等** | ch02-04 注销机制是同一思路 |
| 最终一致性（MQ 重试） | 🟢 A2A Task 七态流转 | ch10 Task 生命周期 |
| 分布式锁 | 🟢 同 Redis 锁 | ch09-07 |

**核心认识**：Agent 的"事务"问题换了个形式——不是"数据一致性"，而是"**副作用工具被重复调用了怎么办**"（模型可能重试）。
- Task 七态生命周期（submitted→working→completed/failed/canceled）= 你的订单状态机
- `contextId` 由 SERVER 生成且多轮复用 = 你的会话/事务 ID

---

### 域 12：限流熔断降级（🟢 最易平移，逐条 1:1）

| Sentinel/Hystrix/Resilience4j | ch12 容错件 | 参数对照 |
|---|---|---|
| `TimeLimiter` / readTimeout | 超时 8s | 等价 |
| `Retry` + exponentialBackoff | 指数退避重试 | 等价 |
| `CircuitBreaker` | 熔断器 | 2 连败打开 / 30s 半开 ≈ failureRateThreshold / waitDurationInOpenState |
| `fallbackMethod` | 降级兜底 | 等价 |
| `@LoadBalanced` 多实例 | 模型降级链 qwen-plus→qwen-turbo | 🟡 能力降级 ≠ 实例切换 |
| 流量控制（Sentinel FlowRule） | flask-limiter + 令牌桶 | 等价 |
| 线程池隔离（Hystrix Bulkhead） | Worker 池 ×2 | 等价 |
| ChaosBlade 混沌工程 | 故障注入器 | 方法论一致 |

**三态拒绝语义**（ch12-06）：`429` 限流 / `503` 队列满 / `504` 超时 —— 与你的 HTTP 语义完全一致。

---

### 域 13：可观测（🟢 完全可以复用现有体系）

| 微服务 | AI Agent | 说明 |
|---|---|---|
| TraceId 全链路追踪 | `request_id` | ch12-01 直接注入 |
| SkyWalking / Zipkin | OpenTelemetry / LangSmith / **Langfuse** | Langfuse 是 AI 专用 |
| Micrometer 指标 | 分维度统计 + `/health` | ch12-01 |
| ELK 日志 | 结构化日志 + JSONL | ch07-05 |
| Prometheus / Grafana | 同 | 可直接复用 |
| — | **LLM 调用专项 trace**（prompt/response/token/成本） | 🔴 新增维度 |

> ch12 讲"可观测三件套"：`request_id 日志 + 分维度统计 + /health 端点`。
> **你可以直接把 SkyWalking 接上**——多出来的只是"LLM 调用明细"这个新维度（token 数、耗时、模型名、成本）。

---

### 域 14-15：安全（🟢 + 🔴 内容安全新增）

| 微服务安全 | AI Agent 安全 | 状态 |
|---|---|---|
| Spring Security 认证 | API Key / Bearer Token | 🟢 ch12-02、ch10-02 |
| JWT 校验 | 恒时比较防时序攻击 | 🟢 ch12-02 |
| OAuth2 授权 | Agent Card skills 能力匹配 | 🟡 ch10-02 |
| 输入校验（`@Valid`） | 参数校验 + 意图白名单 | 🟢 ch13-02 |
| 代码沙箱（Java SecurityManager 已废弃） | **AST 白名单求值 / 容器沙箱** | 🟡 ch13-03、ch04-04 |
| SQL 注入防护（PreparedStatement） | `?` 占位符 / 参数化 | 🟢 ch02-06 |
| 敏感数据脱敏 | 落盘前脱敏/加密 | 🟢 ch07 |
| — | **敏感词过滤**（Trie 前缀树，生成前/后双层） | 🔴 ch03-08 |
| — | **幻觉治理**（logprobs 置信度 + LLM-as-Judge） | 🔴 ch03-09、ch13-11 |
| — | **LLM 输出永不执行**（三步清洗） | 🔴 ch13-02 |

**新增安全边界**：微服务里"代码是自己写的，相对可信"；Agent 里"**模型输出是不可信输入**"——必须当作外部不可信数据来防御（剥围栏 → 括号定位 → 严格 JSON 解析 → 白名单求值）。

---

### 域 16-17：并发与调度（🟢 + 🟡）

| 微服务 | AI Agent | 项目位置 |
|---|---|---|
| `@Async` / CompletableFuture | `ThreadPoolExecutor` / `asyncio` | ch12-03 |
| 线程池参数调优 | Worker 池 + 队列 | ch12-03/ch12-06 |
| XXL-Job / Quartz | 优先级队列（priority, seq） | ch12-04 |
| `@Scheduled` | 手写调度循环 | — |
| DAG 工作流（Camunda/Flowable） | LangGraph 图编排 | ch05 |
| 轮询/加权负载均衡 | TaskDispatcher 轮询/加权 | ch09-03 |
| 分布式调度 | DAG 依赖解锁（heapq） | ch09-04 |
| 线程隔离 / ThreadLocal | ContextScope task_id 命名空间 | ch09-06 |

**⚠️ GIL 提醒**：Python 的 `threading` 只适合 IO 密集（LLM 调用正是 IO 密集，✅ 可用）；CPU 密集必须 `multiprocessing`。

---

### 域 18：测试（🔴 断言方式根本改变）

| JUnit5 / Mockito | pytest（本项目） | 差异 |
|---|---|---|
| `@Test` | `def test_*():` | 等价 |
| `assertEquals(a, b)` | `assert a == b` | 等价 |
| `@Mock` / Mockito | 真实调用（本项目策略：**不 mock**） | 🔴 项目选型 |
| `@SpringBootTest` | pytest fixture + 动态加载 | — |
| Testcontainers | — | — |
| 契约测试 | **LLM-as-a-Judge**（裁判模型） | 🔴 新增 |
| 断言相等 | 断言**结构正确 + 语义合理** | 🔴 不确定性 |

**测试三部曲**（ch13，与你熟悉的测试金字塔不同）：
```
① 工具调用正确率（steps 轨迹结构化比对）
② 并发压测（P95 / QPS / 串话检测）
③ 幻觉率与满意度（LLM-as-a-Judge 裁判）
```
> 递进逻辑：**对 → 扛得住 → 不说谎**。顺序反了会浪费测试成本。

**项目实测**：`tests/` 下 11 个文件 / 305 个测试；`@pytest.mark.live` 标记真实 API 调用；`conftest.py` 用 `importlib` 动态加载（因为文件名是"数字+中文"，无法 import）。

---

### 域 19-20：构建部署与协议文档（🟡 / 🟢）

| 微服务 | AI Agent |
|---|---|
| Maven / Gradle | pip / uv / Poetry |
| `pom.xml` 依赖 | `requirements.txt` / `pyproject.toml` |
| Dockerfile 多阶段构建 | 同 |
| K8s Deployment/Service | 同 |
| Swagger / OpenAPI | OpenAPI / **MCP Schema** / **Agent Card** |
| 接口文档（人读） | Agent Card（模型读）→ 描述是自然语言 |

---

## 三、🔴 全新领域清单（微服务没有，必须从零学）

| 新领域 | 是什么 | 对应章节 | 一句话 |
|---|---|---|---|
| **Prompt 工程** | 把提示词当接口契约设计 | ch01 | 新"接口定义"思维 |
| **RAG / 向量检索** | 给 LLM 开一扇查知识库的门 | ch06 | 新"数据访问层" |
| **上下文工程** | 上下文的表示/路由/存储/合并 | ch07 | 新"内存管理" |
| **Token 成本模型** | token 预算 / 轮次上限 / 模型分级 | ch08、ch12 | 新"资源计量"（一等公民） |
| **幻觉治理** | 置信度 / 自洽性 / 引用溯源 / 裁判模型 | ch03-09、ch13-11 | 新"数据质量"问题 |
| **内容安全审查** | 敏感词 + 多模态审核 + 审计留痕 | ch03-08 | 新"合规"要求 |
| **不确定性测试** | 断言结构+语义而非相等 | ch13 | 新"测试范式" |
| **模型即服务** | 模型供给/定制(LoRA)/协议/治理 | ch03 | 新"基础设施"品类 |

---

## 四、Java 生态 → Python AI 生态 库级对照

| 能力 | Java 生态 | Python AI 生态 |
|---|---|---|
| LLM 调用 SDK | （无标准，各家 SDK） | **dashscope**（阿里百炼）/ openai / anthropic |
| 模型编排框架 | （无） | **LangChain** / **LangGraph** / LlamaIndex |
| Agent 框架 | （无） | LangGraph / AutoGen / CrewAI / 本项目手写 |
| 向量库 | （无） | **FAISS** / Chroma / Milvus / Qdrant |
| Embedding | （无） | DashScopeEmbeddings / sentence-transformers |
| Web 框架 | Spring Boot | **FastAPI** / Flask |
| 数据校验 | Bean Validation / Hibernate Validator | **Pydantic** |
| HTTP 客户端 | RestTemplate / WebClient / OkHttp | requests / httpx / aiohttp |
| 并发 | java.util.concurrent | threading / asyncio / multiprocessing |
| 测试 | JUnit / Mockito | **pytest** / unittest |
| 可观测 | Micrometer / SkyWalking / Zipkin | OpenTelemetry / **Langfuse** / LangSmith |
| 限流熔断 | Sentinel / Hystrix / Resilience4j | 手写 / slowapi / tenacity |
| 依赖管理 | Maven / Gradle | pip / **uv** / Poetry |
| 序列化 | Jackson | json / orjson / **Pydantic** |
| 任务队列 | XXL-Job / Quartz | Celery / RQ / APScheduler |
| MCP 工具 | （Java SDK 有） | **mcp**（Anthropic 官方 SDK） |
| A2A 协议 | （Java SDK 有） | **a2a-sdk**（Google 官方 SDK） |

---

## 五、🟡 需要重构的 5 个关键点（重点理解）

1. **控制反转**：调用链从"代码写死"变成"模型运行时决定" → 必须靠 trace 才知道系统干了什么。
2. **错误哲学**：从"异常即故障"变成"**错误是数据**" → 工具永不抛异常，错误回传让模型自己调整。
3. **不确定性**：从"同输入同输出"变成"可能不同" → 测试断言结构+语义，幂等要显式做。
4. **无事务**：没有 `@Transactional` → 靠 Task 状态机 + 幂等 + 补偿模拟。
5. **DI → 注册表**：没有 IoC 容器 → 用注册表 dict 管理可插拔能力（声明即注册）。

---

## 六、给你的落地路线（按技术域优先级）

```
阶段 1  直接复用你的强项（1–2 周见效）
  域 12 限流熔断降级  → ch12-05/06（几乎照搬 Sentinel 思路）
  域 13 可观测        → ch12-01（接上你的 SkyWalking）
  域 2  Web 框架      → ch11（Flask ≈ SpringMVC，一天上手）
  域 8  消息事件      → ch10-05（Pub/Sub ≈ Kafka）
  域 14 鉴权安全      → ch12-02（API Key ≈ 你的网关鉴权）

阶段 2  重构你的编排经验（2–4 周）
  域 7  服务调用      → ch02/ch10（理解 Function Calling 反转）
  域 17 任务调度      → ch05/ch09（DAG ≈ 你的工作流引擎）
  域 9  缓存          → ch07/ch12（Redis 直接换进去）
  域 11 事务一致性    → ch10 Task 七态（≈ 订单状态机）

阶段 3  攻克新大陆（4–8 周）
  域 10 向量数据库    → ch06（FAISS/Chroma/Milvus）
  域 18 测试          → ch13（LLM-as-a-Judge）
  全新 RAG/上下文     → ch06/ch07
  全新 Prompt/成本    → ch01/ch08/ch12
```

---

## 七、一页速记（贴在显示器上）

```
┌─────────────────────────────────────────────────────────────┐
│  微服务（Java）           →   AI Agent（Python）              │
├─────────────────────────────────────────────────────────────┤
│  Spring Boot              →   FastAPI / Flask          🟢    │
│  Spring Cloud Gateway     →   Flask 中间件 + 反代       🟢    │
│  @Autowired / Spring IoC  →   注册表 dict（无容器）      🟡    │
│  Nacos / Eureka           →   A2A Agent Card            🟡    │
│  Feign 服务调用           →   Function Calling          🟡反转 │
│  Kafka / RocketMQ         →   A2A Pub/Sub / Redis Stream 🟢   │
│  Redis 缓存/会话/锁       →   memory / 语义缓存 / 隔离   🟡    │
│  MySQL / MyBatis          →   同 + 向量库(FAISS/Milvus)  🔴新增│
│  @Transactional / Seata   →   无 → Task 状态机 + 幂等    🔴    │
│  Sentinel / Hystrix       →   令牌桶 + 熔断 + 降级链     🟢    │
│  Micrometer / SkyWalking  →   OpenTelemetry / Langfuse   🟢    │
│  Spring Security / JWT    →   API Key / Bearer Token     🟢    │
│  Swagger / OpenAPI        →   OpenAPI / MCP / AgentCard  🟢    │
│  JUnit / Mockito          →   pytest / LLM-as-a-Judge    🔴    │
│  Maven / Gradle           →   pip / uv / Poetry          🟡    │
├─────────────────────────────────────────────────────────────┤
│  （无）                   →   Prompt 工程 / RAG / 上下文   🔴    │
│  （无）                   →   Token 成本 / 幻觉治理        🔴    │
└─────────────────────────────────────────────────────────────┘

记忆锚点：决策权在模型，执行权在本地。
         能平移的占 ~60%，要重构的 ~25%，全新的 ~15%。
```

---

*本手册配套 `arch/` 下全套架构图；技术细节回到各章 `arch_汇总说明.md` 与 `spec.md`。*
*第一版（分层视角）：`微服务到AI架构平移对照.md`；本手册（全技术域视角）为第二版。*
