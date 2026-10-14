# 第 10 章 规范说明书（spec.md）——A2A 协议与多智能体通信

> **SDD 定位**：本文是「规范驱动」文档，不是教材摘要。
> **上篇（意图与学习路径）**回答 *为什么学、学什么、怎么学*；
> **下篇（契约与验收）**回答 *每个文件到底承诺了什么、怎么验证、还缺什么*。
> **主线**：把教材里用 `qwen_agent` 虚构框架 + 自定义消息类搭出来的「多智能体通信」，
> 落到 **A2A Protocol v1.0（Google 2025，已捐给 Linux Foundation）** 的真实规范上，
> 并厘清 **A2A vs MCP 的职责边界**。
>
> 适用范围：`D:/AiWorkOut/aiAgentCode/chapter10/`（6 个文件 / 2802 行）。
> 契约字段一律**从代码事实反推**，不臆造；教材简化点与改写依据一并留痕。

---

# 上篇：意图与学习路径

## 1. 章意图（Why）

### 1.1 教材原版想解决什么

教材用一章的篇幅讲「多智能体如何互相通信」，给出的是一组**自定义消息对象 + 虚构框架**：

| 教材出现的概念 | 教材实现 | 问题 |
|---|---|---|
| 智能体间消息 | `class A2AMessage(sender, receiver, type, payload)` | 名字叫 A2A，但字段全是自造，不是 A2A 规范 |
| 请求-响应 | `RequestAgent` / `ResponderAgent` / `Dispatcher` | 直接 `dashscope` 拼 prompt，没有协议层信封 |
| 发布订阅 | `PubSubMessage(topic, content)` + `subscribe(topic)` | topic 订阅 ≠ A2A 的 taskId 订阅 |
| 协商竞标 | `dispatch_task()` 里 `for` 循环 + `random.uniform()` 评分 | 拉模式、随机分，无法体现 Agent 自主性 |
| 智能体本体 | `from qwen_agent import Agent, Message, PromptEntry` | **该框架在标准 pip 源不可安装，属虚构** |

**教材的真正价值**：演示了「多智能体系统需要消息格式、需要请求响应、需要广播订阅、需要协商」这四类通信需求。
**教材的真正缺口**：没有落到任何**真实可互操作**的协议上——这些消息发不出去、别的 Agent 认不出。

### 1.2 本章改写要解决什么

把上述四类需求映射到 **A2A v1.0 的四类真实机制**，并补齐教材从未涉及的 **MCP 集成**：

```
教材的四类通信需求              →   A2A v1.0 的真实机制
──────────────────────────────────────────────────────────────
① 消息格式（怎么说话）          →   Message / Part（kind: text|file|data）
② 请求-响应（一问一答）         →   JSON-RPC 2.0 Request/Response + Task 生命周期
③ 广播订阅（一对多）            →   JSON-RPC 2.0 Notification + subscribeToTask
④ 协商竞标（多中选一）          →   Pub/Sub 广播 + message.send 投标（组合模式）
⑤ 智能体用什么干活（新增）      →   MCP Protocol（tools/resources/prompts）
⑥ 智能体怎么被发现（新增）      →   Agent Card + Registry + skills 匹配
```

### 1.3 本章最该带走的三句话

1. **A2A 管「Agent 之间说什么」，MCP 管「Agent 用什么工具干活」**——两个协议正交，不是二选一。
2. **JSON-RPC 2.0 只提供两种信封**：`Request`（有 `id`，要 Response）和 `Notification`（无 `id`，不要 Response）。所有 A2A 通信都是这两者的组合。
3. **A2A 没有专门的「竞标」方法**——竞标 = `Notification 广播` + `message.send 投标` + `Task 状态机` 组合出来的**应用层模式**。协议只给积木，不给成品。

---

## 2. 学习路径（6 文件 / 2802 行）

按「先协议格式 → 再身份能力 → 再跨协议集成 → 再三种交互模式」的递进顺序阅读：

| # | 文件 | 行数 | 核心机制 | 读完后你应能说出 |
|---|---|---|---|---|
| 01 | `01_a2a的消息格式与语义设计规范.py` | 498 | Message / Part / Task / Artifact / Agent Card + A2AServer / A2AClient | A2A 的核心对象长什么样、任务状态机有哪些状态 |
| 02 | `02_智能体身份认证与能力生命机制.py` | 451 | Agent Card 认证段 + skills 三级匹配 + Registry 发现 + 错误码 | Agent 怎么被认证、怎么被「按能力发现」 |
| 03 | `03_集成a2a与mcp协议的agent通信系统.py` | 514 | MCP Server（tools/resources）+ A2A Server 绑定 MCP + Orchestrator | A2A 与 MCP 如何各管一段、如何串起来 |
| 04 | `04_实现请求与响应的机制.py` | 458 | JSON-RPC 信封 + A2A Task + LLM 的**三层 Request-Response** | 一次「一问一答」在协议层/业务层/能力层各是什么 |
| 05 | `05_多智能体广播订阅系统.py` | 455 | JSON-RPC **Notification** + `subscribeToTask` + SSE 事件对象 | Request 与 Notification 的协议层区别 |
| 06 | `06_多智能体协商与竞标系统.py` | 426 | Pub/Sub 广播 + 多 Agent 投标 + Agent Card 匹配度评标 | 竞标是「广播+投标+评标」组合模式，不是协议特性 |

### 阅读路线建议

- **第一遍（主线 3 篇）**：01 → 04 → 05。抓住「消息对象 → 请求响应 → 广播订阅」这条协议主线。
- **第二遍（能力 2 篇）**：02 → 06。抓住「身份/能力 → 基于能力的协商」这条业务主线。
- **第三遍（集成 1 篇）**：03。唯一一篇讲 MCP 的，是本章的「跨协议」制高点。
- **对照读法**：04 与 05 成对读（Request vs Notification），02 与 06 成对读（能力声明 vs 能力竞价）。

---

## 3. 四条工程主线（本章反复出现的设计决策）

### 主线一：协议层 / 业务层 / 能力层三层分离

每一篇都严格分三层，这是全章的骨架：

| 层 | 载体 | 例 10-4 中的体现 |
|---|---|---|
| **L1 协议层** | JSON-RPC 2.0 信封（`jsonrpc/id/method/params`） | `build_request()` / `build_response()` / `build_error_response()` |
| **L2 业务层** | A2A 核心对象（Message / Task / Artifact） | `build_a2a_message()` / `build_a2a_task()` / `build_artifact()` |
| **L3 能力层** | `dashscope.Generation.call`（qwen-plus） | `ResponderAgent.handle_request()` 内的 LLM 调用 |

**为什么重要**：换掉 L3（比如从 qwen 换到别的模型）不影响 L1/L2；换掉 L1（比如 HTTP 换 gRPC）也不影响 L2 的业务语义。**分层 = 可替换**。

### 主线二：Task 状态机是响应的容器

A2A 不用「payload.answer」这种裸字段承载结果，而是用 **Task 生命周期**：

```
submitted ──→ working ──→ completed（含 Artifact）
                │
                ├──→ input-required（需要补充输入）
                ├──→ canceled
                ├──→ rejected
                └──→ failed
```

- **04**：同步短任务，直接 `working → completed` 两阶段（甚至一步跳到 `completed`）。
- **05**：异步长任务，`submitted → working → completed` 每次变化都广播。
- **Artifact** 是 Task 的**最终产出物**，取代教材的 `payload.answer`。

### 主线三：Request 与 Notification 的协议层二分

这是全章最容易混淆、也最关键的一点：

| | Request | Notification |
|---|---|---|
| 字段 | `{jsonrpc, id, method, params}` | `{jsonrpc, method, params}` |
| 有无 `id` | **有** | **无** |
| 是否要 Response | **要**（响应方必须原样回传 `id`） | **不要**（MUST NOT 回 Response） |
| 语义 | 一问一答 | 单向广播 |
| 本章用例 | 04 的 `message.send` | 05 的 `task.status`、06 的 `task.submitted` |

**一句话记忆**：**「缺 `id` 的就是广播」**。

### 主线四：A2A 与 MCP 的正交分工（只在 03 篇完整出现）

| | A2A | MCP |
|---|---|---|
| 解决的问题 | Agent **之间**说什么 | Agent **用什么工具**干活 |
| 对端 | 另一个 Agent（有 Agent Card） | 工具/资源服务器（有 tools/resources 清单） |
| 典型方法 | `message/send`、`tasks/get` | `tools/list`、`tools/call`、`resources/read` |
| 类比 | 人跟人打电话 | 人使用计算器 |

**在 03 篇的组合方式**：一个 `A2AServer`（对外是 Agent）**内部绑定**一个 `MCPServer`（对内是工具箱）——别的 Agent 通过 A2A 找它办事，它通过 MCP 调工具把事办成。

---

## 4. 学习检查清单（读完自测）

- [ ] 能写出 A2A 的 `Message`、`Task`、`Artifact` 三个对象的最小字段集。
- [ ] 能说出 Task 的 7 个状态，并指出哪两个是终态。
- [ ] 能解释为什么 `Notification` 不能有 `id`。
- [ ] 能说出 `-32001` / `-32002` / `-32601` / `-32602` 分别代表什么错误。
- [ ] 能画出「A2A 找 Agent → MCP 调工具」的两段式链路。
- [ ] 能解释「竞标为什么不是 A2A 的协议特性，而是组合模式」。
- [ ] 能说出 Agent Card 的 `skills` 里的 `inputModes` / `outputModes` 有什么用。
- [ ] 能指出教材原版至少有哪 3 处「名为 A2A、实非 A2A」的地方。

---

# 下篇：契约与验收

## 5. 全局技术约束（C-xx）

以下约束在 chapter10 全部 6 个文件中成立，是**改写后代码的公共契约**。

### C-01 JSON-RPC 版本常量唯一化

```python
JSONRPC_VERSION = "2.0"
```
**约束**：所有信封构造器（`build_request` / `build_notification` / `build_response` / `build_error_response` / `build_jsonrpc_request`）必须使用该常量，**不得硬编码字符串 "2.0"**。
**理由**：协议版本升级时单点修改。
**验收**：全文 grep `"2.0"` 只应出现在常量定义处。

### C-02 请求 `id` 原样回传

**约束**：响应方构造 Response 时，`id` 必须等于对应 Request 的 `id`（`build_response(req_id, ...)` 的第一个参数）。
**理由**：JSON-RPC 2.0 § Response Object——`id` 用于匹配请求-响应对。
**反例**：响应方自行生成新 `id` → 请求方无法匹配（04 篇明确打印提示此点）。
**验收**：04 篇 `RequestAgent._received_responses[resp_id]` 的键与发送时 `_sent_requests` 的键一致。

### C-03 错误走 `error.code`，不走 HTTP 状态码

**约束**：业务失败用 `{"error": {"code": <int>, "message": <str>}}` 表达，`code` 取 JSON-RPC 保留段或 A2A 自定义段。
**枚举**（04 篇常量处 + 02 篇使用）：

| code | 含义 | 段位 |
|---|---|---|
| -32700 | Parse Error（JSON 解析失败） | JSON-RPC 保留 |
| -32600 | Invalid Request（信封格式错误） | JSON-RPC 保留 |
| -32601 | Method Not Found（方法不存在） | JSON-RPC 保留 |
| -32602 | Invalid Params（参数错误） | JSON-RPC 保留 |
| -32603 | Internal Error（内部错误） | JSON-RPC 保留 |
| -32001 | Authentication Failed（认证失败） | A2A 自定义 |
| -32002 | Capability Validation Failed（能力不匹配） | A2A 自定义 |
| -32003 | Input Required（需要输入） | A2A 自定义 |

**验收**：04 篇错误路径演示能打印出 `-32601`（方法不存在）与 `-32602`（缺 message 字段）两种错误。

### C-04 成功响应与错误响应互斥

**约束**：一个 Response 对象**要么**含 `result`，**要么**含 `error`，**不得同时含**，也不得两者皆无。
**实现**：`build_response()` 只产出 `result` 版；`build_error_response()` 只产出 `error` 版。
**验收**：`if "error" in jsonrpc_response:` 是请求方判断成功/失败的唯一分支（04 篇 `handle_response`）。

### C-05 有 `id` 才叫 Request

**约束**：构造广播消息必须走 `build_notification()`（无 `id`），构造一问一答必须走 `build_request()`（有 `id`）。二者不可混用。
**验收**：05 篇 `build_notification()` 返回值不含 `"id"` 键。

### C-06 Task 状态取值受控

**约束**：Task `status.state` 只能取以下 7 值之一（A2A 规范 § Task States）：
`submitted` / `working` / `input-required` / `completed` / `canceled` / `rejected` / `failed`。
**终态**：`completed` / `canceled` / `rejected` / `failed`。
**验收**：05 篇用类常量 `TaskEventType` 枚举事件类型，避免裸字符串。

### C-07 Part.kind 受控

**约束**：Message/Artifact 的 `parts[i].kind` 只能取 `text` / `file` / `data`。
**本章实现**：全部 6 篇只用到 `{"kind": "text", "text": ...}`。
**缺口**：`file` / `data` 两种 kind 仅定义未实例化（见第 8 节缺口 G-02）。

### C-08 LLM 调用统一走 dashscope 原生协议

```python
response = dashscope.Generation.call(
    model="qwen-plus",
    messages=[...],
    temperature=0.3,
    max_tokens=<128|256|512>,
    result_format='message',      # ← 强制
)
text = response.output.choices[0].message.content
```
**约束**：
- 必须带 `result_format='message'`，否则 `response.output` 是字符串，`.choices[0]` 报错。
- `model` 本章固定 `qwen-plus`（未做 primary/backup 切换，见缺口 G-04）。
- `temperature` 统一 0.3（低随机性，适合确定性演示）。
**验收**：6 篇中每次 `.Generation.call(` 均携带 `result_format='message'`。

### C-09 时间戳统一 UTC ISO8601

```python
datetime.now(timezone.utc).isoformat()
```
**约束**：所有 `timestamp` 字段用 UTC ISO8601，不用本地时间、不用秒级整数。
**理由**：跨时区 Agent 协作时无歧义。
**验收**：04 `_sent_requests[...]["timestamp"]`、05 `build_task_status_event()["timestamp"]`、06 `bid["timestamp"]` 三处一致。

### C-10 标识符命名前缀约定

| 对象 | 前缀 | 生成方式 | 例 |
|---|---|---|---|
| JSON-RPC 请求 | `req-` | `uuid4().hex[:12]` | `req-a1b2c3d4e5f6` |
| A2A 消息 | `msg-` | `uuid4().hex[:12]` | `msg-...` |
| A2A 任务 | `task-` | `uuid4().hex[:12]` | `task-...` |
| 会话上下文 | `ctx-` | `uuid4().hex[:12]` | `ctx-...` |
| Artifact | `art-` | `uuid4().hex[:8]` | `art-...` |
| 投标 | `bid-` | `uuid4().hex[:8]` | `bid-...` |

**约束**：前缀必须与对象类型一致，便于日志辨识。
**验收**：04/05/06 生成处均符合上表。

### C-11 教材原代码以注释保留，不删除

**约束**：每篇文件头部以注释块保留教材原版结构（`# class A2AMessage: ...`），并注明 `# ← 虚构框架` / `# ← 自定义简化消息` 等判定。
**理由**：这是「学习型改写」——必须能对照看到「改了什么、为什么改」。
**验收**：6 篇文件均含 `# ===== 原代码（注释保留——教材简化版…）=====` 区块（05/06 篇有此段；01~04 篇以文件头「教材简化 vs 真实规范」注释块承载）。

### C-12 不使用虚构框架 `qwen_agent`

**约束**：改写后代码**不得** `import qwen_agent`。所有原 `qwen_agent.Agent` 能力由 `dashscope.Generation.call` + 自建类承接。
**理由**：`qwen_agent` 在标准源不可安装，是教材的「纸上框架」。
**验收**：6 篇 grep `qwen_agent` 只应命中注释块。

---

## 6. 逐文件契约（F-01 ~ F-06）

以下每份契约的结构：**意图 / 输入 / 处理 / 输出 / 契约 / 验收标准 / 已知风险 / 教材问题（注释实录）**。

---

### F-01 `01_a2a的消息格式与语义设计规范.py`（498 行）

**意图**：定义 A2A v1.0 的**核心数据对象**与其语义——这是全章的「类型字典」，后续 5 篇的构造器都可在此找到出处。

**核心对象契约**：

| 对象 | 必填字段 | 可选字段 | 说明 |
|---|---|---|---|
| **Agent Card** | `name`, `description`, `endpoint`, `skills[]` | `capabilities`, `authentication` | Agent 的「名片」，见 F-02 扩展 |
| **Message** | `messageId`, `role`, `parts[]` | `contextId`, `referenceTaskIds`, `taskId` | `role ∈ {user, agent}` |
| **Task** | `id`, `contextId`, `status`, `kind="task"` | `artifacts[]`, `history[]` | `status = {state, message?}` |
| **Artifact** | `artifactId`, `name`, `parts[]` | `description`, `metadata` | Task 的产出物 |
| **Part** | `kind` | `text` / `file` / `data` | 本章只用 `kind="text"` |

**类型字面量（Literal）契约**：
```python
TASK_STATES   = Literal["submitted","working","input-required","completed","canceled","rejected","failed"]
MESSAGE_ROLES = Literal["user", "agent"]
PART_KINDS    = Literal["text", "file", "data"]
```

**服务端/客户端契约**：

| 类 | 方法 | 语义 |
|---|---|---|
| `A2AServer` | `handle_message_send()` | 接收 Message → 建 Task → 返回 |
| `A2AServer` | `handle_task_get()` | 按 `taskId` 取 Task（不存在 → -32001 类错误） |
| `A2AServer` | `handle_task_list()` | 列出 Task（可按 contextId 过滤） |
| `A2AServer` | `handle_task_cancel()` | 取消 Task（迁到 `canceled` 终态） |
| `A2AClient` | `send_message()` / `get_task()` / `list_tasks()` / `cancel_task()` | 对应上述 4 个 RPC |

**输入 / 输出**：无外部文件输入；输出为构造出的 dict 与打印的演示链路。

**验收标准**：
- V-01-A：`build_message()` 产出的 Message 含 `messageId`/`role`/`parts` 且 `parts[0].kind == "text"`。
- V-01-B：`build_task()` 默认 `status.state == "submitted"`，`kind == "task"`。
- V-01-C：对不存在的 `taskId` 调 `task_get` 返回带 `error.code` 的响应（非抛异常）。

**已知风险**：
- 所有对象都在**内存 dict** 中，无持久化——进程退出即丢（见缺口 G-03）。
- `A2AServer` 无并发保护，多线程下 dict 操作非原子（对比 chapter12 的做法）。

**教材问题（文件头注释实录）**：
> 教材原版只模拟了 A2A 的「结构化消息格式」这一个最基础环节——用 `A2AMessage(sender, receiver, type, payload)` 自造字段，既没有 `contextId`（无法串多轮），也没有 `Task` 状态机（无法表达处理中），更没有被发现机制（Agent Card）。
> 改写后补齐：① 标准 Message/Part/Task/Artifact 四对象；② 7 态任务状态机；③ Agent Card；④ 服务端 4 个标准 RPC + 客户端封装。

---

### F-02 `02_智能体身份认证与能力生命机制.py`（451 行）

**意图**：在 F-01 的对象基础上，补上「Agent 怎么证明自己是谁」和「Agent 怎么被按能力发现」两块。

**认证契约**：
- Agent Card 增加 `authentication` 段，声明 scheme（如 `Bearer`）。
- `A2AServer.verify_auth(credentials)`：
  - 从 `Authorization: Bearer <token>` 提取 token；
  - 比对期望 token（`hashlib.sha256(agent_name).hexdigest()[:32]` 派生，见 04 篇同款）；
  - 不通过 → `-32001 Authentication Failed`。

**能力声明契约（`build_skill`）**：
```python
{
  "id": "macro_analysis",
  "description": "宏观经济形势分析",
  "tags": ["宏观", "GDP", "经济"],
  "inputModes":  ["text"],      # 该技能接受的输入形态
  "outputModes": ["text"]       # 该技能产出的形态
}
```
**`inputModes` / `outputModes` 的作用**：让调用方在**发请求前**就能判断「我的输入形态它收不收」，避免发了 file 却只支持 text 的浪费。

**能力匹配契约（`match_skill`，三级策略）**：
1. **优先**：`skill.description` 的中文字符与任务描述有交集 → 命中；
2. **其次**：`skill.tags` 任一命中任务描述 → 命中；
3. **兜底**：`skill.id` 出现在任务描述中 → 命中。
返回 `命中数 / 技能总数`（0.0~1.0）。

**发现契约（`A2ARegistry.discover_by_skill(query)`）**：遍历注册表，返回所有 `match_skill(query) > 0` 的 Agent Card。

**错误码分工**：
| 场景 | code |
|---|---|
| token 缺失/错误 | -32001 |
| 无任何 Agent 能匹配该能力 | -32002 |

**验收标准**：
- V-02-A：`verify_auth` 对无 token 请求返回 `-32001`，对正确 token 返回 `None`（放行）。
- V-02-B：`match_skill("分析人民币汇率")` 对含「汇率」tag 的 Agent 返回 > 0。
- V-02-C：`discover_by_skill("不存在的领域xyz")` 返回空列表，且上层据此产出 `-32002`。

**已知风险 / 代码疑点**：
- ⚠️ 第 51 行附近存在 `PART_KINDS = Literal_ = ["text", "file", "data"]` 这类可疑赋值（`Literal_` 被当成变量名而非 `typing.Literal`）。**这是一处代码坏味道**：后缀 `_` 的临时名泄漏到模块级，且丢失了 Literal 的类型约束语义。**建议**：改为 `PART_KINDS = Literal["text","file","data"]` 并确认 `from typing import Literal`。**当前不影响运行**（因为后续只当普通 list 用），但会让 F-01 的 C-07 契约在**类型层面**失效。
- token 派生用 `sha256(agent_name)[:32]` 是**确定性**的——只适合教学演示，真实场景需加随机 salt/密钥轮转（见缺口 G-05）。

**教材问题（文件头注释实录）**：
> 教材用一个 `capability_score` 浮点数表示 Agent 能力，Agent Card 概念完全缺失——既无法声明「我会什么」，也无法被别的 Agent 按需找到。
> 改写后补齐：① Agent Card 含 authentication + skills（含 inputModes/outputModes）；② 三级能力匹配；③ Registry 按技能发现；④ 认证/能力两类错误码。

---

### F-03 `03_集成a2a与mcp协议的agent通信系统.py`（514 行）

**意图**：本章唯一一篇讲 **MCP 集成**的，回答「A2A 找到了 Agent 之后，Agent 靠什么把活干完」。

**MCP 侧契约（`MCPServer`）**：

| 方法 | 语义 | 返回 |
|---|---|---|
| `tools_list()` | 列出可用工具 | `{"tools": [{"name","description","inputSchema"}]}` |
| `tools_call(name, arguments)` | 调用工具 | `{"content": [...], "isError": bool}` |
| `resources_list()` | 列出资源 | `{"resources": [{"uri","name","mimeType"}]}` |
| `resources_read(uri)` | 读资源 | `{"contents": [{"uri","text"}]}` |

**关键契约**：
- 工具**执行失败**时返回 `isError: true` + 错误内容，**不抛协议级异常**——这是 MCP 的「工具层错误 vs 协议层错误」分离（呼应 chapter13 的双层回退语义）。
- `inputSchema` 用 JSON Schema 描述参数，调用方据此构造 `arguments`。

**`create_financial_mcp_server()`**：构造一个金融领域的示例 MCP Server（含查询/计算类工具），是本章 MCP 的实例化样板。

**A2A 侧契约**：
- `A2AServer` **内部持有** 一个 `MCPServer` 实例（组合关系）。
- 处理 A2A Message 时，A2AServer 可调 `self.mcp_server.tools_call(...)` 完成实际工作，结果封装进 Task 的 Artifact。

**编排契约（`A2AMCPOrchestrator`）**：
```
调用方 Agent ──A2A(message/send)──→ A2AServer
                                       │  内部
                                       └──MCP(tools/call)──→ MCPServer ──→ 工具结果
A2AServer ──A2A(Task + Artifact)──→ 调用方 Agent
```

**验收标准**：
- V-03-A：`tools_list()` 返回的工具都带 `name` + `description` + `inputSchema`。
- V-03-B：调用不存在的工具名 → 返回 `isError: true`，**不抛异常**。
- V-03-C：`resources_read()` 对不存在的 uri 返回错误内容而非崩溃。
- V-03-D：能从一次 A2A `message/send` 的 Artifact 中看到 MCP 工具的执行结果，证明「A2A→MCP」串通。

**已知风险**：
- `MCPServer` 的工具是**本地 Python 函数**模拟，未走真实 JSON-RPC over stdio/HTTP（对比 chapter13 的真实 `McpClient`）。
- 无 tools 调用的**轮次上限**（对比 chapter13 的 `MAX_TOOL_ROUNDS`）——理论上模型可能无限循环调工具。

**教材问题（文件头注释实录）**：
> 教材原版的「MCP 格式」是对 MCP 的误解——只模仿了消息外观（`{jsonrpc, method, params}`），既没有 `tools/list` 的发现机制，也没有 `isError` 的工具级错误语义，更没有 `resources` 原语。
> 改写后补齐：① MCP 四方法（tools_list / tools_call / resources_list / resources_read）；② 工具层错误用 `isError` 而非协议异常；③ A2A Server 组合 MCP Server 的两段式链路；④ 编排器演示端到端。

> **注**：本章 MCP 使用的协议版本与 chapter13（`2025-06-18`）不同——本篇为简化版（约 `2025-03-26` 语义），见缺口 G-06。

---

### F-04 `04_实现请求与响应的机制.py`（458 行）

**意图**：把「一问一答」拆成**三层 Request-Response**，是三篇交互机制（04/05/06）的基准篇。

**三层契约**：

| 层 | Request | Response |
|---|---|---|
| **L1 协议层** | `build_request(method="message.send", params={message})` | `build_response(req_id, result=task)` 或 `build_error_response(...)` |
| **L2 业务层** | A2A `message.send`（含 Message + contextId） | A2A `Task`（`working` → `completed` + Artifact） |
| **L3 能力层** | `dashscope.Generation.call(...)` | LLM 文本 → 装进 Artifact |

**类契约**：

| 类 | 方法 | 契约 |
|---|---|---|
| `RequestAgent` | `build_request(question, context_id?, response_agent?)` | 返回 JSON-RPC Request；内部登记 `_sent_requests[req_id]` |
| `RequestAgent` | `handle_response(jsonrpc_response)` | 返回 `{"ok": True, "task": ...}` 或 `{"ok": False, "error": ...}`；登记 `_received_responses` |
| `ResponderAgent` | `verify_request(request)` | 格式错 → 返回已包装的 error Response；合法 → `None` |
| `ResponderAgent` | `handle_request(request)` | 验证 → 提取 text → 调 LLM → 构造 Task → 包装 Response |
| `RequestResponseDispatcher` | `run_single(question)` | 串起 requester→responder→requester 全流程 |

**验证契约（`verify_request` 三步）**：
1. `jsonrpc != "2.0"` → `-32600`；
2. `method not in ("message.send", "message/stream")` → `-32601`；
3. `params.message` 缺失 → `-32602`。

**输入 / 输出**：输入为问题字符串；输出为 JSON-RPC Response（内含 Task/Artifact）。

**验收标准**：
- V-04-A：`run_single("...")` 返回 `ok=True` 且 `task.status.state == "completed"`，`task.artifacts[0].parts[0].text` 非空。
- V-04-B：`method="nonexistent.method"` 的请求 → 响应的 `error.code == -32601`。
- V-04-C：`params={}`（缺 message）→ 响应的 `error.code == -32602`。
- V-04-D：Response 的 `id` 与 Request 的 `id` 严格相等（C-02）。

**已知风险**：
- LLM 调用**无 try/except**——网络/额度异常会直接崩，不进 error Response（对比 chapter12/13 的容错设计）。
- 响应是**同步阻塞**的，没有 `working` 中间态（Task 直接 `completed`），不适合长任务。

**教材问题（文件头注释实录）**：
> 教材原版 `RequestAgent` / `ResponderAgent` / `Dispatcher` 用手工拼 `[system, user, memory]` prompt 直接调 dashscope——没有协议层信封，因此「请求」和「函数调用」无法区分，也无法匹配请求-响应对。
> 改写后补齐：① L1 JSON-RPC 2.0 信封（含 id 原样回传）；② L2 A2A Task 封装响应；③ L3 能力层仍走 dashscope；④ Dispatcher 同时演示正常路径 + 2 条错误路径。

---

### F-05 `05_多智能体广播订阅系统.py`（455 行）

**意图**：演示 **Notification（单向广播）** 与 **subscribeToTask（订阅 Task 状态流）**，与 04 篇成对比。

**协议层契约**：

| 构造器 | 返回 | 关键差异 |
|---|---|---|
| `build_request(method, params, req_id?)` | `{jsonrpc, id, method, params}` | **有 id** |
| `build_notification(method, params)` | `{jsonrpc, method, params}` | **无 id**（MUST NOT 回 Response） |

**事件契约（`build_task_status_event`）**：
```python
{"taskId", "state", "timestamp", "message"?, "artifacts"?}
```
**事件类型枚举（`TaskEventType`）**：
`task.submitted` / `task.working` / `task.input_required` / `task.completed` / `task.failed` / `task.canceled`

**订阅管理契约（`A2ASubscriptionManager`）**：

| 方法 | 语义 |
|---|---|
| `subscribe(task_id, subscriber)` | 加入 `_subscriptions[task_id]`；去重 |
| `unsubscribe(task_id, subscriber)` | 从列表移除 |
| `get_subscribers(task_id)` | 返回订阅者列表 |
| `broadcast(task_id, notification)` | 向该 task 的所有订阅者逐个调 `on_notification`，**单个异常不中断其余**（try/except 包裹），返回结果描述列表 |

**发布者契约（`PublisherAgent`）**：
- `create_task(desc)` → 建 Task（`submitted`）+ 广播 `task.submitted`；
- `process_task(task_id, prompt)` → 广播 `task.working` → 调 LLM → 广播 `task.completed`（含 Artifact）。

**订阅者契约（`SubscriberAgent`）**：
- `on_notification(notification)` → 按 `event.state` 分派处理；
- `analyze_on_completed=True` 时，对 `completed` 事件**再调一次 LLM** 做二次摘要（演示订阅方的主动响应）。

**验收标准**：
- V-05-A：`build_notification()` 返回值**不含** `"id"` 键。
- V-05-B：`broadcast()` 对同一 task 的多订阅者都触发 `on_notification`，返回结果条数 == 订阅者数。
- V-05-C：`SubscriberAgent(analyze_on_completed=True)` 在 `completed` 事件时产生含「二次分析」字样的返回。
- V-05-D：一个订阅者抛异常不影响其余订阅者收到通知（容错广播）。

**已知风险**：
- 广播是**同步顺序**执行（`for sub in subscribers`），慢订阅者会阻塞整个广播——真实 SSE 需异步（见缺口 G-07）。
- Step 3.5 手工「重广播 submitted」是演示补丁（因订阅发生在 create_task 之后）——真实实现应支持**订阅后回放历史事件**。
- `broadcast()` 的 try/except 只包住单个订阅者调用，但**未记录/上报**失败（仅拼进返回字符串）。

**教材问题（文件头注释实录）**：
> 教材的 `PubSubSystem.subscribe("财经快讯")` 是按**主题字符串**订阅，而 A2A 是按 **taskId** 订阅——主题订阅需要先定义主题体系，taskId 订阅天然与任务生命周期对齐。
> 教材 `PubSubMessage(topic, content)` 是自定义消息；A2A 用 JSON-RPC Notification（无 id）作为广播载体，语义由协议规定。
> 改写后补齐：① Notification 无 id 的协议层语义；② subscribeToTask + SSE 事件对象；③ 断连恢复思路（Push Notification，注释说明）。

---

### F-06 `06_多智能体协商与竞标系统.py`（426 行）

**意图**：演示 A2A **没有专门竞标方法**时，如何用「Pub/Sub 广播 + message.send 投标 + Agent Card 匹配」**组合出**协商模式。

**投标方契约（`BidderAgent`）**：
- `__init__(name, skills, base_capability)`：持有 Agent Card；
- `match_skill(task_description)` → 0.0~1.0（三级匹配，同 F-02 思路）；
- `generate_bid_proposal(task_desc)` → 调 dashscope 生成 2-3 句策略；
- `create_bid(task_id, task_desc)` → 返回投标 dict 或 `None`：
  - `match_score < 0.25` → **主动放弃**（返回 None）；
  - 否则 `combined_score = round(base_capability * (0.5 + 0.5 * match_score), 2)`；
  - 投标 dict 含 `bid_id / bidder / taskId / proposal / score / match_score / agentCard / timestamp`。

**注册表契约（`BidderRegistry`）**：`register()` / `all_bidders()` / `get(name)`。

**编排器契约（`A2ANegotiationOrchestrator.run_negotiation(task_desc, dashscope_evaluation=True)`）**：

| Step | 动作 | 协议映射 |
|---|---|---|
| 1 | 建 Task + `build_notification("task.submitted", ...)` | 05 篇 Pub/Sub |
| 2 | 遍历所有 Bidder 调 `create_bid()` | 02 篇能力匹配 + LLM |
| 3 | `_evaluate_bids(bids, use_dashscope)` → 取 `max(score)` | 可选 LLM 辅助评标 |
| 4 | `build_notification("task.winner", ...)` | 05 篇广播 |

**评标契约（`_evaluate_bids`）**：
- `use_dashscope and len(bids) >= 2` → 调 LLM 给「一句话综合评估」（**仅打印意见**，不改变排序）；
- **最终排序始终按 `score` 降序**取第一（`max(bids, key=lambda b: b["score"])`）；
- LLM 异常 → 捕获后**退回 score 排序**（不崩）。

**验收标准**：
- V-06-A：对「人民币汇率对外贸影响」任务，含「汇率」tag 的 `agent:qwen_finance` 匹配度 > 0 且正常投标。
- V-06-B：不相关任务的 Agent `match_score < 0.25` 时 `create_bid()` 返回 `None`（不出现在 `all_bids`）。
- V-06-C：`run_negotiation()` 返回的 `winner` 等于 `all_bids` 中 `score` 最大者的 `bidder`。
- V-06-D：`dashscope_evaluation=False` 时不发起 LLM 评标调用（可断点验证），仍能正常选出 winner。
- V-06-E：`all_bids` 为空时返回 `{"winner": None, "reason": "无有效投标"}`，不崩。

**已知风险**：
- Step 2 是 **`for` 循环遍历 bidders 主动调 `create_bid()`**——这其实是**拉模式**（教材同款），并未真正让 Agent「主动投标」。注释里说改成「推模式」，但**代码实现仍是拉**（广播 `task.submitted` 后没让 Bidder 自己响应，而是编排器直接遍历）——这是**意图与实现的偏差**（见缺口 G-08）。
- LLM 评标结果**只打印不影响决策**，实际等价于「按自报 score 排序」——自报分可能失真。
- 无「落标通知」——未中标的 Agent 收不到结果。
- 无投标超时/截止机制——真实协商需要 `bid_deadline`。

**教材问题（文件头注释实录）**：
> 教材 `evaluate_score()` 用 `random.uniform(-0.3, 0.3)` 随机加减模拟评分——评分不可解释、不可复现。
> 教材 `dispatch_task()` 用 `for` 循环直接问每个 Agent，是**主动拉**；A2A 的协商应是**广播 → Agent 主动投标 → 评标**的推模式。
> 改写后改进：① 评分改为 `base_capability × (0.5 + 0.5 × match_score)`（可解释）；② 匹配度来自 Agent Card skills（可复现）；③ 引入 Registry 管理参与者；④ 可选 LLM 辅助评标。

---

## 7. 全章验收清单（V-01 ~ V-12）

按「能否独立跑通 + 契约是否成立」两层验收。**前置**：`export DASHSCOPE_API_KEY=sk-xxx`。

### 7.1 运行层验收（能否跑）

| 编号 | 验收项 | 期望 |
|---|---|---|
| V-01 | `python 01_...py` | 打印 Message/Task/Artifact 构造与 4 个 RPC 演示，无异常 |
| V-02 | `python 02_...py` | 打印认证通过/失败、能力匹配、Registry 发现，无异常 |
| V-03 | `python 03_...py` | 打印 MCP tools/resources 演示 + A2A→MCP 端到端，无异常 |
| V-04 | `python 04_...py` | 三层链路 + 2 条错误路径演示，无异常 |
| V-05 | `python 05_...py` | 广播/订阅全流程 + 二次分析，无异常 |
| V-06 | `python 06_...py` | 3 个 Bidder 投标 + 评标 + winner 展示，无异常 |

### 7.2 契约层验收

| 编号 | 契约 | 对应 | 验证方式 |
|---|---|---|---|
| V-07 | JSON-RPC 版本常量唯一（C-01） | 全章 | grep 硬编码 `"2.0"` |
| V-08 | 错误只用 `error.code`，且枚举符合 C-03 | 04/02/01 | 触发错误路径看 code |
| V-09 | 有 id = Request，无 id = Notification（C-05） | 04/05/06 | 检查构造器返回值键集 |
| V-10 | Task 状态取值在 7 态内（C-06） | 01/04/05 | grep `"state"` 赋值 |
| V-11 | LLM 调用必带 `result_format='message'`（C-08） | 全章 | grep `.Generation.call(` 上下文 |
| V-12 | 无 `import qwen_agent`（C-12） | 全章 | grep 应只命中注释 |

### 7.3 学习层验收（人能否讲清）

- [ ] 能不看代码画出 F-04 的三层 Request-Response。
- [ ] 能说出 04 与 05 在协议层的唯一关键区别（id 有无）。
- [ ] 能解释 03 篇 A2A Server 与 MCP Server 的组合关系。
- [ ] 能指出 06 篇「推模式」注释与「拉模式」实现的偏差。

---

## 8. 已知缺口与后续改进（Gap Analysis）

| 编号 | 缺口 | 影响 | 建议改进 | 对照章节 |
|---|---|---|---|---|
| G-01 | 所有对象**只在内存**，无持久化 | 进程退出 Task/订阅全丢，无法跨进程协作 | 引入 JSON 文件或 SQLite 落盘 Task/订阅表 | chapter12（cache.json） |
| G-02 | `Part.kind` 只用 `text`，`file`/`data` 仅定义 | 无法传文件/结构化数据，A2A 多模态能力未演示 | 增加一个 `file`/`data` 的构造与消费示例 | — |
| G-03 | 无并发保护 | 多线程下 dict 操作非原子 | 用 `threading.Lock` 保护 `_subscriptions` / `_bids` | chapter12（TokenBucket） |
| G-04 | 模型固定 `qwen-plus`，无 primary/backup | 单点失败即崩 | 引入 `MODEL_REGISTRY`（qwen-plus → qwen-turbo 切换） | chapter12/13 |
| G-05 | 认证 token 用 `sha256(name)[:32]` 确定性派生 | 只适合演示，不安全 | 加随机 salt + 密钥轮转 + 过期 | chapter12（API Key） |
| G-06 | MCP 版本为简化版，非 `2025-06-18` | 与真实 MCP 服务不互通 | 对齐 `MCP_PROTOCOL_VERSION="2025-06-18"` + `initialize` 握手 | chapter13（F-07） |
| G-07 | 广播**同步顺序**执行，无异步/无 SSE 真流 | 慢订阅者阻塞全体；非真流式 | 用队列/线程池异步投递 + SSE `text/event-stream` | chapter12（异步任务） |
| G-08 | 06 篇注释宣称「推模式」，实现仍是 `for` 循环拉模式 | 教学表述与代码不一致 | 改为「广播 → Bidder 的 `on_notification` 内自发投标」 | — |
| G-09 | 无 LLM 调用超时/重试/熔断 | 单次 LLM 失败即崩 | 引入 timeout + 指数退避 + CircuitBreaker | chapter12（容错五件套）/13 |
| G-10 | LLM 评标结果只打印不参与决策 | 评标形同虚设 | 让 LLM 意见作为 tie-breaker 或在 score 相近时介入 | — |
| G-11 | 无落标通知、无投标截止 | 协商闭环不完整 | 加 `bid_deadline` + 落标 Notification | — |
| G-12 | `02` 篇疑似 `PART_KINDS = Literal_ = [...]` 坏味道 | 类型约束失效（运行不受影响） | 修正为 `Literal["text","file","data"]` | — |
| G-13 | 无 `tasks/get` 的**订阅后回放**（05 Step 3.5 手工补广播） | 订阅者错过订阅前的事件 | 支持从 `history` 回放或 `lastEventId` | — |

### 缺口优先级建议

- **P0（影响正确性理解）**：G-08（推/拉表述）、G-12（类型坏味道）
- **P1（影响可扩展性）**：G-01（持久化）、G-03（并发）、G-04（模型回退）、G-07（异步）
- **P2（能力完整性）**：G-02（多模态）、G-06（MCP 版本）、G-09（容错）、G-11（协商闭环）
- **P3（细节）**：G-05、G-10、G-13

---

## 附录 A：A2A v1.0 核心对象最小示例

```jsonc
// Agent Card
{
  "name": "agent:responder",
  "description": "专业问答 Agent",
  "endpoint": "http://localhost:8080/a2a",
  "skills": [{"id": "qa", "description": "通用问答", "tags": ["qa"],
              "inputModes": ["text"], "outputModes": ["text"]}],
  "authentication": {"scheme": "Bearer"}
}

// Message（业务层）
{
  "messageId": "msg-abc123",
  "role": "user",
  "contextId": "ctx-def456",
  "parts": [{"kind": "text", "text": "当前欧洲通胀如何？"}]
}

// Task（业务层响应容器）
{
  "id": "task-xyz789",
  "contextId": "ctx-def456",
  "kind": "task",
  "status": {"state": "completed",
             "message": {"role": "agent", "parts": [{"kind":"text","text":"处理完成"}]}},
  "artifacts": [{"artifactId": "art-01", "name": "qa_answer",
                 "parts": [{"kind": "text", "text": "..."}]}]
}

// JSON-RPC Request（协议层）
{"jsonrpc": "2.0", "id": "req-001", "method": "message.send",
 "params": {"message": { /* Message */ }}}

// JSON-RPC Notification（协议层·广播）
{"jsonrpc": "2.0", "method": "task.status",
 "params": {"event": {"taskId": "task-xyz789", "state": "task.working"}}}
```

## 附录 B：三层 Request-Response 速查

| 层 | Request | Response | 失败表现 |
|---|---|---|---|
| L1 协议层 | `{jsonrpc,id,method,params}` | `{jsonrpc,id,result}` | `{jsonrpc,id,error:{code,message}}` |
| L2 业务层 | `message.send` + Message | Task（working→completed + Artifact） | Task.state = `failed`/`rejected` |
| L3 能力层 | `dashscope.Generation.call(...)` | `output.choices[0].message.content` | 本章未处理（抛异常） |

## 附录 C：协议层 Request vs Notification 判定口诀

```
信封里有 "id"  →  Request   →  对方必须回 Response（id 原样）
信封里无 "id"  →  Notification →  对方 MUST NOT 回 Response
```
