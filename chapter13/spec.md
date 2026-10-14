# chapter13 规范（Spec）—— 从零实现一个复合智能体系统

> **文件性质**：SDD（Specification-Driven Development）规范文档
> **对应源码**：`chapter13/` 下 11 个 `.py` 文件（共 5172 行，全书最大章节）
> **编写依据**：逐文件通读源码后提炼，契约字段均来自代码事实，未臆造
> **状态**：v1.0 ｜ 2026-10-14
> **配套文档**：[arch_汇总说明.md](arch_汇总说明.md)（架构总览）｜ [index_汇总说明.html](index_汇总说明.html)（网页版）

---

# 上篇：意图与学习路径

## 1. 本章意图（Why）

第 13 章是全书**收官章**。前 12 章把智能体的零件——提示词、工具调用、记忆、状态机、RAG、协议——一件件拆开讲；本章的目标只有一个：**把这些零件组装成一台完整的、可验证的复合智能体系统，并用测试证明它真的能跑、扛得住、不说谎。**

本章与第 1 章构成一对极端：
- **第 1 章**：最小闭环，6 个文件 260 行，证明"提示词进、文本出"能跑通；
- **第 13 章**：完整系统，11 个文件 5172 行，证明"这套工程做法在真实约束下站得住"。

本章最有价值的不是代码规模，而是贯穿 11 个文件的**同一条工程主线**——**把教材里"看起来能跑"的简化写法，逐条替换成生产级的"确实跑得通"的写法**。每个文件头部都注释保留了教材原版问题清单，这份清单本身就是一套"AI Agent 工程反模式目录"。

> 📌 与五模块架构的对应：本章实现了完整的**接口模块**（13-01）、**认知模块**（13-02/13-08）、**执行模块**（13-03/13-04/13-06/13-07）、**记忆模块**（13-05/13-08），以及**横切支撑层**的全部四项——编排调度（04）、安全对齐（02/03）、可观测评估（08/09/10/11）、成本限流（05 向量缓存 / 10 并发控制）。

## 2. 学习路径（按源码顺序）

| 顺序 | 文件 | 行数 | 学什么 | 掌握后应该能回答 |
|---|---|---|---|---|
| 1 | `01_先定义标准的Agent接口层和数据结构.py` | ~383 | 接口层三件套：`Message` / `ConversationContext` / `ModelAdapter` | 为什么"构造时校验"比"使用时校验"好？适配器池解决什么问题？ |
| 2 | `02_用户意图识别与入口解析.py` | ~391 | 安全 JSON 解析（替代 `eval`）+ schema 校验 + 主备兜底链 | 为什么 `eval(LLM输出)` 是远程代码执行漏洞？ |
| 3 | `03_工具调用链与异常回退机制.py` | ~476 | AST 白名单求值 + 工具注册表 + **双层回退语义** | 工具级失败与模型级失败为什么要分开处理？ |
| 4 | `04_子状态管理与任务调度.py` | ~424 | 状态机白名单迁移 + 单一注册表 + 完整快照 | "idle → success"直接跳步为什么必须拦截？ |
| 5 | `05_RAG检索问答子系统.py` | ~487 | 轻量 RAG 三段流水线 + 向量落盘缓存 + 多轮记忆 | 向量缓存为什么能证明"零二次计费"？ |
| 6 | `06_MCP协议的上下文路由器.py` | ~568 | **真实 MCP 规范**（JSON-RPC 2.0 + 生命周期 + 标准错误码） | MCP 是协议还是传输方式？ |
| 7 | `07_A2A消息协议的模块注入.py` | ~552 | **真实 A2A 规范**（Agent Card + Task 生命周期 + 能力发现） | A2A 的 Task 与 MCP 的 tool call 有何本质差别？ |
| 8 | `08_LangChain的通用Agent主控链条.py` | ~458 | 主控三件套：工具循环 × 主备回退 × 多轮记忆 | 教材的"假回退"为什么完全没生效？ |
| 9 | `09_Test工具调用正确率测试框架.py` | ~511 | 三项指标：工具名准确率 / 参数提取率 / 返回一致性 | 教材的测试为什么正确率永远是 0%？ |
| 10 | `10_Test多用户并发测试与系统压测.py` | ~469 | 并发安全 + 分位数指标（P50/P95）+ 串话检测 | 为什么 LLM 压测不能只看平均值？ |
| 11 | `11_Test模型幻觉率与用户满意度评估.py` | ~464 | LLM-as-a-Judge 幻觉评估（替代字符相似度） | 字符相似度为什么测不出幻觉？ |

**建议学习方式**：
1. **先读每个文件的头部注释块**——那是"问题清单 + 解决清单"，信息密度最高；
2. 再读主代码，重点看被注释掉的教材原版（它是"反面对照"）；
3. 最后跑 `python <file>` 看 self-test，再跑 `--demo` 亲手体验；
4. 13-01 到 13-08 是**逐层搭积木**，建议严格按顺序读；13-09/10/11 是测试，可独立看但依赖 13-08。

## 3. 本章的工程主线：十一条改写规则

11 个文件共享同一套"教材问题 → 生产改写"的对照逻辑。把这条主线抽出来，就是一份 **AI Agent 工程反模式清单**：

| # | 反模式（教材写法） | 生产写法（本章改写） | 出现在 |
|---|---|---|---|
| 1 | **虚构类**：`Qwen2Chat` / `DeepSeekChat` | `dashscope.Generation.call` 原生协议（或 OpenAI 兼容） | 全部 |
| 2 | **过时 import**：`langchain.schema` / `langchain.llms` / `langchain.document_loaders` | `langchain_core.*`、或用 dashscope 原生绕过 LangChain | 01/02/05 |
| 3 | **`eval(LLM输出)`**：把解析写成远程代码执行 | `extract_json` / `safe_eval` 白名单，数据永不当代码 | 02/03 |
| 4 | **错误字符串混流**：`"[ERROR] ..."` 与正常输出同通道 | 结构化契约 `{"success", ...}`，调用方可程序化判断 | 02/05/06/07/08 |
| 5 | **堆栈外泄**：`traceback.format_exc()` 返回给调用方 | 错误信息止于日志，堆栈不出函数边界 | 01/03/08 |
| 6 | **每轮重建**：每次调用都 `new` 适配器 / Agent / Chain | 适配器池复用、装配一次全程复用 | 01/03/05/08 |
| 7 | **平行映射**：`if/elif` 链与注册表两份维护 | 单一注册表（`MODEL_REGISTRY` / `TASK_REGISTRY` / `INTENT_ROUTES`） | 04/06 |
| 8 | **假回退**：回退代码写了但没接进调用链 | 回退内嵌模型调用层，逐轮真实生效 | 03/04/08 |
| 9 | **借壳命名**：自造结构却叫 "MCP" / "A2A" | 按真实协议规范重构（JSON-RPC 2.0 / Agent Card / Task） | 06/07 |
| 10 | **裸 except**：`except:` 吞掉一切（含 KeyboardInterrupt） | `except Exception` + 日志 + 结构化返回 | 03/08 |
| 11 | **无 self-test**：正确性全靠肉眼 | 每文件 5~6 项 self-test，`main()` 按结果 `sys.exit` | 全部 |

> ⚠️ **最值得记住的两条**：
> 1. **错误是数据，不是故障**（规则 4 + 8 的合成）。工具查不到城市时，不是让整个请求失败，而是把"查不到"作为结果回填给模型，让模型自己向用户解释。这条语义在第 3 / 5 / 8 章反复出现，是本章最重要的设计决策。
> 2. **协议 ≠ 传输**（规则 9）。MCP / A2A 是**协议规范**，`handle(dict)` 的进程内调用只是教学期的最小传输实现；换 stdio / HTTP 时协议层零改动。

## 4. 学习检查清单

- [ ] 能说清 `Message` 为什么在**构造时**就校验 role，而不是在序列化时
- [ ] 能解释 `eval('{"a": 1}')` 与 `json.loads('{"a": 1}')` 在安全上的本质差异
- [ ] 能说出 `safe_eval` 为什么**刻意拒绝幂运算** `9 ** 9`
- [ ] 能画出 `idle → running → success → running` 这条合法迁移链，并说明为什么成功后可重派
- [ ] 能解释 `cache.json` 与 `api_calls` 计数器如何配合证明缓存的真实性
- [ ] 能说清 MCP 的 `-32601` 与 A2A 的 `-32001` 分别代表什么
- [ ] 能解释为什么并发压测里"每个请求新建独立 `AgentCore`"是**正确**的（而非浪费）
- [ ] 能说明 LLM-as-a-Judge 相比 `difflib` 相似度，在"编造答案"检测上的优势

---

# 下篇：契约与验收

## 5. 统一技术约束（Global Constraints）

本章 11 个文件共享同一套硬约束，任一文件偏离即为违约：

```
C-01  模型接入协议：dashscope 原生协议为主（dashscope.Generation.call）
C-02  跨模型演示：OpenAI 兼容协议，base_url = https://dashscope.aliyuncs.com/compatible-mode/v1
C-03  模型名：主力 qwen-plus / 备胎 qwen-turbo（DeepSeek 托管未开通，槽位保留可改回）
C-04  密钥来源：环境变量 DASHSCOPE_API_KEY，禁止硬编码
C-05  必需参数：result_format='message'（不传则 response.output 是字符串）
C-06  响应路径：resp.output.choices[0].message.content（原生协议）
C-07  状态码校验：每次调用必须检查 resp.status_code != 200 → 抛 RuntimeError
C-08  错误处理：结构化返回优先，堆栈止于日志，绝不外泄给调用方
C-09  日志：logging 统一格式 "%(asctime)s [%(levelname)s] %(message)s"
C-10  入口：main() 跑 self-test，--demo 进手动体验，sys.exit(0/1)
C-11  回归安全：临时改 MODEL_REGISTRY 必须在 finally 中还原
C-12  运行前置：DASHSCOPE_API_KEY 已设置，dashscope 与 openai 包已安装
```

统一调用骨架（原生协议，全章通用）：

```python
import os
import dashscope
dashscope.api_key = os.environ.get("DASHSCOPE_API_KEY")

resp = dashscope.Generation.call(
    model="qwen-plus",
    messages=messages,
    max_tokens=256,
    result_format="message",       # C-05：必需
)
if resp.status_code != 200:        # C-07：必需
    raise RuntimeError(f"{resp.code} {resp.message}")
return resp.output.choices[0].message.content
```

## 6. 逐文件契约

### F-01 `01_先定义标准的Agent接口层和数据结构.py`（接口模块）

| 项 | 契约 |
|---|---|
| **意图** | 定义系统的公共语言：消息单元、会话上下文、模型适配器，为后续 10 篇提供统一数据结构底座 |
| **核心组件** | `Message` / `ConversationContext` / `ModelAdapter` / `get_adapter()` 适配器池 |
| **Message 契约** | 构造时校验：`role ∈ ("user","assistant","system")`，非法即抛 `ValueError`（**fail fast**）；`to_dict()` 导出 `{"role","content"}` |
| **Context 契约** | `ConversationContext(session_id=None)`；`session_id` 缺省自动生成 uuid（长度 36）；`as_dict()` 导出 dashscope 原生 messages 列表 |
| **Adapter 契约** | 注册表驱动：`MODEL_REGISTRY = {"qwen": {model:"qwen-plus", protocol:"native"}, "deepseek": {model:"qwen-turbo", protocol:"openai"}}`；未注册类型抛 `ValueError` |
| **call() 返回契约** | 成功 `{"success": True, "model", "response"}`；失败 `{"success": False, "error"}`——**不含 traceback 字段** |
| **适配器池** | `get_adapter(model_type)` 同类型全程复用（修复教材"每轮 new"） |
| **验收标准** | self-test 5 项：role 白名单拦截 / 上下文结构与 uuid / 未注册模型拒绝 / qwen 真实调用 / 跨模型共享上下文（"它"指代接上） |
| **教学要点** | 这是全章**唯一的适配器模块**，其余 10 篇的模型调用都是它的简化内联版。生产中应 `from 01_... import ModelAdapter` |

### F-02 `02_用户意图识别与入口解析.py`（入口层 · 安全对齐）

| 项 | 契约 |
|---|---|
| **意图** | 用户请求进系统的第一道关：识别意图 → 解析参数 → 校验结构，坏数据在此止步 |
| **核心组件** | `extract_json` / `validate_intent` / `ModelInvoker` / `IntentParser` |
| **extract_json 契约** | 三步清洗：剥 ```json 围栏 → 括号配对定位首个 `{...}` → `json.loads` 严格解析。**任何失败返回 `None`，绝不执行模型输出** |
| **validate_intent 契约** | `intent` 白名单 `("查询","执行","对话","工具调用","未知")`，精确匹配 → 模糊包含归一化 → 兜底"未知"；`domain` 非字符串归"未知"；`parameters` 非 dict 归 `{}` |
| **兜底链契约** | `IntentParser.parse()` 永不抛异常：主模型 → 备用模型 → 结构化"未知"`{"intent":"未知","domain":"未知","parameters":{}}` |
| **⚠️ 踩坑（代码注释实录）** | 模板填充必须用 `str.replace("{query}", q)` 而非 `.format()`——模板内嵌 JSON 示例的 `{"intent": ...}` 花括号会被 `format` 误当占位符（`KeyError: '"intent"'`） |
| **验收标准** | self-test 5 项：干净 JSON 直解 / 围栏+噪声清洗 / **恶意输出拒绝**（`__import__('os').system(...)` 必须返回 None）/ 真实意图识别 / 多查询批量（清晰样本精确断言，模糊样本只验白名单契约） |
| **安全要点** | 对照教材 `eval(response.content.strip())`——那是把"解析"写成"远程代码执行"。提示注入可让模型输出恶意语句并被原样执行 |

### F-03 `03_工具调用链与异常回退机制.py`（执行层 · 工具链）

| 项 | 契约 |
|---|---|
| **意图** | 给模型装上"手"：通过 function calling 调用真实工具，并建立**双层回退语义** |
| **核心组件** | `safe_eval` / `query_weather` / `calculate_expression` / `TOOLS_SCHEMA` / `execute_tool` / `ToolAgentManager` |
| **safe_eval 契约** | AST 白名单求值：仅允许 `int/float` 常量 + `Add/Sub/Mult/Div/Mod` + `UAdd/USub`。**幂运算 `ast.Pow` 刻意拒绝**（`9**9**9` 可毫秒级打爆内存 → DoS）；`__import__` / `lambda` 全部拒绝 |
| **工具返回契约** | 所有工具返回 JSON 字符串 `{"success": True/False, "result"/"error": ...}`；`query_weather("未知")` 返回 `success=False` 而**不是 raise** |
| **execute_tool 契约** | 统一入口，**永不抛出**：工具名白名单校验 → 参数 JSON 解析 → 异常兜底，错误一律结构化返回 |
| **双层回退语义（核心）** | ① **工具级失败** → `{"success": False, ...}` 以 `role=tool` 回填给模型（错误是**数据**，链路不中断、不触发模型回退）；② **模型级失败** → 主备回退 `qwen-plus → qwen-turbo` |
| **循环上限** | `MAX_TOOL_ROUNDS = 4`，超限抛 `RuntimeError`（防模型无限调工具） |
| **⚠️ 实测踩坑（注释实录）** | `_extract_tool_calls` 必须兼容两种形态：模型未调工具时 Message **没有** `tool_calls` 属性（AttributeError）；调工具时它是**元素为 dict 的列表**（非 ToolCall 对象） |
| **消息回填契约** | assistant 消息（含 tool_calls）**以原生 dict 原样回传**，不用 SDK 对象——避免二次序列化的形态不确定性 |
| **验收标准** | self-test 6 项：safe_eval 白名单（含 3 条恶意表达式拒绝）/ 工具级错误结构化 / 真实天气工具链 / 真实计算工具链 / 模型级回退实测（注入坏模型名，校验 `attempted_slots == ["primary","backup"]`）/ 非工具问题直答 |

### F-04 `04_子状态管理与任务调度.py`（编排调度）

| 项 | 契约 |
|---|---|
| **意图** | 复杂任务的"指挥官"：按任务类型调度不同子 Agent，并保证状态迁移合法 |
| **核心组件** | `AgentState` / `AgentController` / `STATUS_TRANSITIONS` / `TASK_REGISTRY` |
| **状态机契约** | `VALID_STATUSES = ("idle","running","success","failed")`；`STATUS_TRANSITIONS = {idle→{running}, running→{success,failed}, success→{running}, failed→{running}}`；非法状态值或非法迁移**一律 `ValueError`**（教材 `update()` 接受任意字符串） |
| **任务注册表契约** | `TASK_REGISTRY = {intent/qa/tool/dialog → {name, prompt}}` **单一映射**（消灭教材 `if/elif` 链与 agents 字典的平行维护）；模板填充用 `replace`（承接 13-02 花括号坑） |
| **快照契约** | `get_status_snapshot()` 返回 `{task: {"name","status","last_result","last_error"}}`，`last_result` 超 80 字符截断（教材快照只有 status，失败后查不到原因） |
| **异常链契约** | 全败时 `raise RuntimeError(...) from last_err`——**携带原始异常链**（教材抛出时不带原因，排查无从下手） |
| **验收标准** | self-test 5 项：状态机白名单（含 `idle→success` 跳步与 `flying` 非法值拦截）/ 未注册类型不影响现有状态 / 真实调度与重派（success→running）/ 快照字段完整 / 模型级回退实测 |

### F-05 `05_RAG检索问答子系统.py`（能力层 · 检索增强）

| 项 | 契约 |
|---|---|
| **意图** | 给模型接上"外部知识"：检索 → 增强 → 生成三段流水线，并按需缓存降低计费 |
| **核心组件** | `JSONCache` / `EmbeddingClient` / `split_text` / `KnowledgeBase` / `RAGAgent` |
| **嵌入契约** | `text-embedding-v3`（1024 维）；`EMBED_BATCH = 10`（单批上限，超批需分批）；缓存键为文本 **md5** |
| **缓存契约** | `JSONCache` 落盘 `cache.json`；`EmbeddingClient.api_calls` 计数器——**重建知识库时 `api_calls == 0` 即证明缓存生效、零二次计费** |
| **分块契约** | `split_text(text, chunk_size=200, overlap=20)`：按段落切，超长段落滑窗兜底（保留教材切分语义，但粒度更细） |
| **检索契约** | `KnowledgeBase.search(query, k=2)`：纯 Python 余弦相似度 top-k（替代 Chroma，概念一致）；`TOP_K = 2`（教材 `k=2` 语义保留） |
| **ask() 返回契约** | 成功 `{"success": True, "answer", "sources"}`；失败 `{"success": False, "answer": "", "sources": [], "error"}`——**错误不再混进回答文本** |
| **多轮记忆契约** | 对话历史存 `self.history`，注入 `messages`（替代废弃的 `ConversationBufferMemory`） |
| **⚠️ 教材问题（注释实录）** | 教材 `data/ai_knowledge.txt` 凭空出现（不存在直接崩）、`HuggingFaceEmbeddings` 需下 90MB 本地模型、`vectorstore.persist()` 新版 Chroma 已移除、每次 `ask()` 重建 Chain |
| **验收标准** | self-test 5 项：检索命中（Transformer）/ 向量缓存复用（`api_calls==0`）/ 真实 RAG 问答 / 多轮指代（"它"接上）/ 主备回退实测 |

### F-06 `06_MCP协议的上下文路由器.py`（协议层 · MCP）

| 项 | 契约 |
|---|---|
| **意图** | 按**真实 MCP 规范**（Anthropic 2024-11 发布，2025-06-18 修订）实现最小服务端与客户端路由器 |
| **核心组件** | `McServer` / `MCPContext` / `MCPRouter` / `build_servers()` |
| **协议常量** | `MCP_PROTOCOL_VERSION = "2025-06-18"`；错误码 `PARSE_ERROR=-32700` / `METHOD_NOT_FOUND=-32601` / `INVALID_PARAMS=-32602` / `INTERNAL_ERROR=-32603` |
| **生命周期契约** | 客户端调任何方法前必须 `initialize`；服务端返回 `{"protocolVersion","capabilities","serverInfo"}`；版本不兼容抛 `-32602`；`notifications/*` **无响应**（返回 None） |
| **原语契约** | `tools/list` 返回 `{name, description, inputSchema}`；`tools/call` 参数缺失/工具不在能力列表抛 `-32602` |
| **错误分层契约（关键）** | **协议错误**（方法/参数问题）用 JSON-RPC 标准错误码；**工具执行错误**按 MCP 规范用 `isError: True` 标记，**不占用协议错误码** |
| **路由契约** | `INTENT_KEYWORDS` 与 `INTENT_ROUTES` 注册表化；`route()` 返回 `{"success","intent","server","response"}` |
| **⚠️ 教材 bug 修正（重点）** | 教材 `get_last_intent` **倒序扫描全部历史**——旧消息关键词会劫持当前意图（最后说"今天天气不错"，却命中更早的"执行"→ 误路由）。修正：**只看最后一条 user 消息** |
| **职责复位** | 教材"路由器名字叫路由却亲自调模型"是职责越界；本章路由器只决定"发给谁"，执行由目标 server 的 tool 完成 |
| **验收标准** | self-test 5 项：生命周期握手 / 协议错误码 / **意图修正对照（教材 bug 实证）** / 真实路由问答 / tool+dialog 路由与结构化契约 |

### F-07 `07_A2A消息协议的模块注入.py`（协议层 · A2A）

| 项 | 契约 |
|---|---|
| **意图** | 按**真实 A2A 规范**（Google 2025 发布）实现 Agent 间协作：能力发现 + 任务生命周期 |
| **核心组件** | `AgentCard` / `A2AMessage` / `A2AServer` / `A2ARouter` / `build_agents()` |
| **协议常量** | `A2A_PROTOCOL_VERSION = "1.0"`；错误码 `METHOD_NOT_FOUND=-32601` / `INVALID_PARAMS=-32602` / `INTERNAL_ERROR=-32603` / **`TASK_NOT_FOUND=-32001`（A2A 特有）** |
| **AgentCard 契约** | 对应规范 `/.well-known/agent.json`：`{name, description, url, version, protocolVersion, skills[{id,name,description,tags}]}` |
| **消息契约** | `to_a2a_message()` 导出规范结构 `{role, messageId, parts, metadata}`；**TextPart** 承载正文，**DataPart** 承载 metadata（教材的 `task_type`/`tool` 魔法字段有了标准容器） |
| **Task 生命周期契约** | `message/send` 创建 Task：`working → completed/failed`；结果放 `artifacts`；技能执行失败是**任务级失败**（`state=failed`），**不是协议错误** |
| **能力发现契约** | `find_agent(skill_tag)` 按 skill 标签匹配目标（替代教材硬编码 receiver 字符串）；无匹配返回 `None` |
| **dispatch 返回契约** | `{"success", "taskId", "state", "response"}`；未注册目标返回 `{"success": False, "error"}`（**修复教材错误混流**） |
| **⚠️ 教材问题（注释实录）** | 教材 `A2AMessage` 是自造 `sender/receiver/payload/metadata` 四字段结构，与真实 A2A 毫无关系（借壳命名，同 13-06 的 MCP 借壳）；`default_handler` 定义了但从未注册——死代码 |
| **验收标准** | self-test 5 项：Agent Card 与 skill 发现 / Task 生命周期（tool_call，无 LLM）/ 真实 qa 生成 / 失败路径与 `tasks/get` / 协议错误码（`-32001`） |

### F-08 `08_LangChain的通用Agent主控链条.py`（认知层 · 主控）

| 项 | 契约 |
|---|---|
| **意图** | 全章**主控中枢**：把工具、回退、记忆、可观测串成一条可跑的主链条 |
| **核心组件** | `AgentCore` / `_extract_tool_calls` / `execute_tool` / `TOOL_IMPLS` |
| **主控三件套** | ① 工具循环（`MAX_TOOL_ROUNDS=5`）；② 主备回退**内嵌在模型调用层**（`_chat_with_fallback`，每轮 LLM 调用都受保护）；③ 多轮记忆 `self.history` |
| **run() 返回契约** | 成功 `{"success": True, "reply", "steps"}`；失败 `{"success": False, "steps", "error"}`。**`steps` 记录每轮工具调用** `{"round","tool","args","result"}`（替代教材 `verbose=True` 布尔开关） |
| **工具契约** | `get_temperature(city)`：月球抛 `ValueError("未找到对应城市")`；`multiply(a,b)`：`str(float(a)*float(b))`。`execute_tool` 捕获一切异常，返回 `"工具执行失败：{e}"` 文本 |
| **⚠️ 教材"假回退"（最严重）** | 教材 `initialize_agent(llm=self.model.qwen, ...)` 用的是**裸 qwen 实例**——AgentExecutor 内部调模型不经过 `ModelWithFallback.invoke`，**回退代码写了等于没写**。本章把回退内嵌调用层，逐轮真实生效 |
| **messages 格式契约** | `tools` 参数必须是外层 `{"type":"function","function":{...}}` 包装格式；**实测传 OpenAI 风格裸 function 列表会被静默忽略**——模型看不到工具定义，凭先验自造工具名 |
| **记忆契约** | 终答时写入 `user` 原话 + `assistant` 终答（教材依赖废弃的 `ConversationBufferMemory`） |
| **⚠️ LLM 非确定性处理** | self-test 对"月球"场景**只验契约**：路径A（调工具→错误回填→致歉）与路径B（模型直答月球无天气）**均为合理行为**。回填机制本身由 Test 1 的确定性单测覆盖 |
| **验收标准** | self-test 5 项：工具单测与错误回填 / 温度链路（`steps` 留痕）/ 乘法+多轮记忆（"再"接续）/ 月球场景（双路径）/ 主备回退实测（逐对校验 `(primary,backup)`） |

### F-09 `09_Test工具调用正确率测试框架.py`（可观测评估 · 正确率）

| 项 | 契约 |
|---|---|
| **意图** | 让"工具调用准不准"变成可测量的数字，实现教材声称但未实现的三项指标 |
| **核心组件** | `TEST_CASES` / `_extract_actual_tools` / `_check_tool_name` / `_check_params` / `_check_result_pattern` / `run_tool_test` / `run_multi_model_compare` |
| **被测主体** | 通过 `importlib` 动态加载 13-08 的 `AgentCore`（避免硬编码绝对路径） |
| **三项指标契约** | ① `tool_name_rate`：预期工具名序列 vs `steps` 里的实际序列；② `param_rate`：必需参数是否存在且值匹配；③ `return_rate`：工具返回是否匹配正则 `expected_result_pat` |
| **测试集契约** | `TEST_CASES` 每条含 `{id, input, expected_tools, expected_params, expected_result_pat}`——**三项指标各有对位点**（教材只有 `expected_tool` 一个字段） |
| **⚠️ 教材核心 bug（最严重）** | 教材 `if case["expected_tool"] in output` —— `expected_tool` 是内部工具名（`weather_tool`），`output` 是**自然语言回复**（"北京天气为晴，温度25°C"），工具名永远不会出现在回复里，**正确率永远 0%**。教材评论还写"故意触发错误"——其实测试逻辑本身就是错的 |
| **metrics 契约** | `{model, total_cases, tool_name_rate, param_rate, return_rate, details, overall}`；`details` 每条含 `{id, input, expected_tools, actual_tools, tool_ok, param_ok, return_ok, reply}` |
| **回归安全** | 临时改 `MODEL_REGISTRY["primary"]["model"]` 必须 `finally` 还原 |
| **验收标准** | self-test 5 项：三项指标单测（含**反向验证**：错误工具名/参数/模式都被识别为 False）/ 真实链路（≥0.8）/ 月球多工具场景 / metrics 结构化契约 / 多模型对比（qwen-plus vs qwen-turbo） |

### F-10 `10_Test多用户并发测试与系统压测.py`（可观测评估 · 并发）

| 项 | 契约 |
|---|---|
| **意图** | 验证系统在多用户并发下的稳定性，输出**生产级指标**（分位数而非只有平均值） |
| **核心组件** | `_percentile` / `compute_metrics` / `run_single_request` / `_detect_cross_talk` / `run_concurrent_test` / `format_report` |
| **并发安全契约** | **每个请求新建独立 `AgentCore` 实例**——独立会话 = 多用户真实语义，天然规避 `history` 串话（dashscope SDK 本身线程安全） |
| **单请求返回契约** | `{"user_id","input","success","reply","duration","tool_hits"}`；`success` 为**布尔值**（替代教材 `"[ERROR]" not in output` 字符串匹配） |
| **指标契约** | `compute_metrics(results, total_time)` **纯函数**：`{total, success_count, failed_count, error_rate, avg_time, p50_time, p95_time, max_time, qps}` |
| **分位数契约** | `_percentile` 线性插值法（与 `numpy.percentile` 默认语义一致）——LLM 响应是**长尾分布**，平均值会被掩盖，必须看 P95 |
| **串话检测契约** | `_detect_cross_talk`：input 含"天气/温度/气温"→ `tool_hits` 应含 `get_temperature`；含"乘/计算/*"→ 应含 `multiply`。不一致即串话信号 |
| **可复现契约** | `random.seed(42)` 固定；结果**按 `user_id` 排序**输出（完成顺序 ≠ 展示顺序） |
| **⚠️ 教材问题（注释实录）** | ① 共享单实例并发 → 串话；② 字符串判错脆弱；③ 指标残缺（无错误率%、无分位数）；④ `random.choice` 无种子不可复现；⑤ 20 并发直接打 API 必触发限流（429）且无说明 |
| **成本约束** | `SELF_TEST_USERS = 3`（真实 LLM 调用，控制成本与限流）；`DEMO_USERS = 6` |
| **验收标准** | self-test 5 项：指标纯函数单测（手工计算值比对，P50=2.5 / P95=3.85）/ 单请求冒烟 / 小并发压测 / 契约与串话检测 + 可复现 / 分位数序合理性（P50 ≤ P95 ≤ max） |

### F-11 `11_Test模型幻觉率与用户满意度评估.py`（可观测评估 · 幻觉）

| 项 | 契约 |
|---|---|
| **意图** | 用 **LLM-as-a-Judge** 真实评估事实一致性，替代教材"字符相似度冒充幻觉检测" |
| **核心组件** | `_clean_json` / `generate_answer` / `judge_answer` / `text_similarity` / `evaluate_case` / `run_evaluation` |
| **被测/裁判契约** | `EVAL_MODEL = "qwen-plus"`（生成）；`JUDGE_MODEL = "qwen-plus"`（判定，**生产建议用更强模型**） |
| **裁判输出契约** | `{"faithful": bool, "score": 1~5 int, "reason": str}`；`_clean_json` 三步清洗（剥围栏 → 首尾括号定位 → 严格 `json.loads`，**不 eval**） |
| **判定标准契约** | 关键事实（数值/主体/时间/名单）不矛盾即为一致，**即使表述完全不同**；补充参考答案外的正确信息不影响判定；关键事实错误/编造判不一致 |
| **⚠️ 教材核心 bug（最严重）** | `difflib.SequenceMatcher` 字符相似度 < 0.6 判幻觉——**字符相似度与事实一致性是两个维度**：事实正确的回答（表述不同）相似度可能低于阈值 → **误判幻觉**；编造数值的回答大部分字符相同 → **漏判**。用文本相似度冒充事实校验，测出的"幻觉率"方向都可能是反的 |
| **相似度语义纠正** | `text_similarity` 保留为**辅助指标**单独报告（正可通过实测对照展示"相似度 ≠ 事实一致性"） |
| **None vs False 契约** | `faithful=None` 表示"**没判成**"（裁判调用失败），`False` 表示"**判定为不一致**"——两者严格区分 |
| **metrics 契约** | `{total, hallucinated, halluc_rate, avg_score, avg_similarity, judge_failures, details}`；`halluc_rate` 只对裁判成功的条目计算 |
| **验收标准** | self-test 5 项：JSON 清洗单测（三种形态）/ 相似度单测 / **裁判判别力实测**（构造正确"蓝鲸"vs 编造"非洲象"验证裁判能区分）/ 全量真实评估 / metrics 七键契约 |

## 7. 全章验收清单

| # | 验收项 | 判定方式 |
|---|---|---|
| V-01 | 11 个文件均可独立执行（`python <file>`） | 无 ImportError / NameError，`sys.exit(0)` |
| V-02 | 均使用 dashscope 原生协议 + `result_format='message'` | 静态检查源码 |
| V-03 | 均含 `status_code != 200` 校验（F-01 起） | 静态检查源码 |
| V-04 | 均无 `eval(` 执行 LLM 输出 | 静态检查（F-02 `extract_json` / F-03 `safe_eval` 替代） |
| V-05 | 均无 `traceback` 外泄到返回结构 | 静态检查 |
| V-06 | 均无错误字符串混流（返回均为结构化契约） | 静态检查 |
| V-07 | 均含 `logging` 日志 + `main()` 入口 + `--demo` | 静态检查 |
| V-08 | 均通过 self-test 全部项目（5~6 项） | 实跑观察 |
| V-09 | 所有临时改 `MODEL_REGISTRY` 处均在 `finally` 还原 | 静态 + 实跑（F-03/04/05/08/09） |
| V-10 | F-05 二次构建知识库 `api_calls == 0`（缓存生效） | 实跑观察 |
| V-11 | F-10 串话检测为空（`cross_talk_suspects == []`） | 实跑观察 |
| V-12 | F-11 裁判能区分正确"蓝鲸"与编造"非洲象" | 实跑观察 |

## 8. 已知缺口（Gap Analysis）

本章作为收官章，**已实现的**是"单机教学版完整系统"。以下能力刻意未包含，属"生产化"范畴：

| 缺口 | 说明 | 生产中应补 |
|---|---|---|
| **真实传输层** | MCP/A2A 均用 `handle(dict)` 进程内传递（教学边界） | 换 stdio / HTTP / SSE，协议层零改动 |
| **真实持久化** | 仅 `cache.json` 落盘向量；会话/任务全在内存 | 接数据库 / Redis |
| **真实鉴权** | 无用户身份、无 API Key 校验 | 网关层加认证授权 |
| **真实工具集** | `query_weather` / `run_script` 均为模拟实现 | 接真实 API |
| **真实满意度** | 满意度由裁判模型代理评估（内容质量），非用户真实打分 | 从产品埋点采集 |
| **更强裁判模型** | `JUDGE_MODEL` 与 `EVAL_MODEL` 同为 qwen-plus | 用更强模型做裁判，降低自评偏差 |
| **DeepSeek 槽位空置** | 账号未开通 DeepSeek 托管（`deepseek-*` 404） | 开通后改注册表 `model` 字段即可 |
| **向量库** | 纯 Python 余弦相似度（概念等价，非生产级） | 换 Chroma / Milvus + rerank |

> 📌 **写作纪律**：本章 spec 严格以**代码事实**为准。凡代码注释中明确记录的"实测踩坑"（花括号 `format` 坑、`tool_calls` 双形态、`tools` 参数包装格式、LLM 非确定性），均如实收录——这些是本章最高价值的知识点，也是教材完全没有的。

---

**版本记录**

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-10-14 | 首版：11 文件全覆盖，上篇意图/学习路径 + 下篇契约/验收 |
