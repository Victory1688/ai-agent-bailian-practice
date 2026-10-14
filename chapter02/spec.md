# 第 2 章 规范说明书（spec.md）——智能体系统的组成结构与运行机制

> **SDD 定位**：本文回答 *「一个智能体由哪几块组成、这些块在运行时如何协作」*。
> **上篇（意图与学习路径）**回答 *为什么学、学什么、怎么学*；
> **下篇（契约与验收）**回答 *每个文件到底承诺了什么、怎么验证、还缺什么*。
> **主线**：本章是全书的**「骨架章」**——它不追求单点功能强大，而是把智能体的
> **模型 / 工具 / 记忆 / 状态 / 生命周期 / 外部能力（API·DB·文件） / 对外接口** 这七件事拆开逐个演示。
> 后续章节的每一个「高级能力」，本质都是在这七块骨架上加装零件。
>
> 适用范围：`D:/AiWorkOut/aiAgentCode/chapter2/`（主文件 8 个 + `agent_ui_api.py` 副本 1 个 = 9 个 .py / 1462 行）。
> 契约字段一律**从代码事实反推**，不臆造；教材简化点与改写依据一并留痕。

---

# 上篇：意图与学习路径

## 1. 章意图（Why）

### 1.1 教材原版想解决什么

教材用一章讲「智能体系统由什么组成、怎么跑起来」，列出 8 个组成要素并各给一个例子：

| 教材概念 | 教材实现方式 | 想说明什么 |
|---|---|---|
| 启动过程 | `build_agent()` 拼装 Agent | 模型加载 + 工具注册 + 系统提示词 + 记忆注入 |
| 任务状态追踪 | `SimpleMemory` 存状态 | 多轮交互中保持「记忆」和「逻辑」 |
| 中断恢复 | `PersistentJSONMemory` | 上下文持久化，断点续传 |
| 注销机制 | `Agent.shutdown()` | 释放计算/存储资源，避免泄漏 |
| 调用外部 API | `WeatherAPITool` 调 wttr.in | 突破模型自身能力边界 |
| 数据库读写 | `AddEmployeeTool` 操作 SQLite | 结构化数据管理 |
| 文件与代码执行 | `ReadFileTool`/`WriteFileTool`/`ExecCodeTool` | 从「语言模型」进化为「自动化助手」 |
| 对外 API 接口 | FastAPI 包一层 | 把 Agent 变成可被网页调用的 HTTP 服务 |

### 1.2 教材原版的致命问题

**全章 8 个例子，无一能运行**——因为都依赖一个**虚构的 `qwen_agent` 框架**：

```python
from qwen_agent import Agent, Tool, ChatMessage      # ← 顶层无此导出
from qwen_agent.llm import QwenLLM                   # ← 无此类
from qwen_agent.memory import SimpleMemory           # ← 无此类
from qwen_agent.utils.schema import CompletionConfig # ← 无此类
from qwen_agent.tools.base import BaseTool           # ← 无此类
```

导入即 `ImportError`。教材把一套「想象出来的框架 API」当成了真实可用的 SDK。

### 1.3 本章改写要解决什么

**核心改写动作**：把每个 `qwen_agent` 概念映射到**百炼 dashscope 的真实能力**，同时**保留教材想教的原逻辑**。

| 教材虚构概念 | 改写后的真实实现 | 改写原则 |
|---|---|---|
| `Agent(name, llm, tools, memory, system_message)` | `config` 字典 + `agent_chat()` 函数（函数本身就是 Agent 循环） | 拆开显示，不再黑盒 |
| `QwenLLM(...)` + `CompletionConfig(...)` | `dashscope.Generation.call(model="qwen-plus", temperature=..., max_tokens=...)` | 参数一一对应 |
| `BaseTool` 子类（`run` + `description` + `parameters`） | 普通函数 + `tool_registry`（名→函数） + `tools`（给模型看的说明书） | **一个工具 = 执行体 + 声明**两部分 |
| `SimpleMemory` / `PersistentJSONMemory` / `BaseMemory` | 纯 Python 类，去掉继承（load/save 逻辑**原样保留**） | 教材这部分本就是标准 Python |
| `Agent.shutdown()` | 手写 `ManagedAgent.shutdown()`（保存→清理→写摘要） | 让注销步骤显式可见 |

### 1.4 本章最该带走的三句话

1. **一个工具 = 「本地执行函数」+「给模型看的 JSON 声明」两部分**——模型只发调用指令，本地负责真正执行。这是所有 Agent 工具机制的统一范式。
2. **`memory` 列表就是 Agent 的「记忆」**——每轮把 `(system + 历史 + 本轮输入)` 一起喂给模型，再把模型回复 append 回去。所谓「状态追踪」「持久化」「中断恢复」，都是在这个列表上做文章。
3. **模型的每次 `Generation.call` 只有两种结果**：返回 `tool_calls`（要执行工具）或返回 `content`（给出最终回答）。**Agent 循环 = 反复调用直到拿到 `content`**。

---

## 2. 学习路径（9 文件 / 1462 行）

按「骨架成型 → 状态记忆 → 生命周期 → 外部能力 → 对外接口」的顺序阅读：

| # | 文件 | 行数 | 核心机制 | 读完后你应能说出 |
|---|---|---|---|---|
| 01 | `01_智能启动过程展示.py` | 161 | 模型加载 + 工具注册 + 系统提示词 + **函数调用循环** + 多轮日志 | Agent 启动有哪四个环节、工具调用怎么闭环 |
| 02 | `02_自动追踪任务状态.py` | 138 | `task_state` 字典 + 工具写状态 + 多轮 memory 传递 | 「状态追踪」为什么就是「往字典里写 + 靠 memory 传递」 |
| 03 | `03_对话终端恢复功能.py` | 170 | `PersistentJSONMemory`（load/save）+ 同 session_id 恢复 | 中断恢复的两个关键动作（落盘时机 + 同 ID 重建） |
| 04 | `04_具备注销机制.py` | 193 | `ManagedAgent`（chat/shutdown）+ 保存→清理→摘要 | 注销为什么要「先留底再删」，而不是直接删 |
| 05 | `05_查询外部天气API.py` | 138 | 工具内 `requests.get` 调 wttr.in | 工具如何突破模型边界、API 失败如何兜底 |
| 06 | `06_sqlLite数据库的读写操作.py` | 183 | 工具内 `sqlite3` 增查 + `?` 占位符防注入 | Agent 如何做结构化数据管理、防 SQL 注入 |
| 07 | `07_读写本地文件.py` | 186 | `read_file` / `write_file` / `exec_code` | Agent 如何操作文件系统与执行代码（及风险） |
| 08 | `08_基于FastAPI的UI中间API接口系统.py` | 147 | FastAPI `/chat` POST + Pydantic + CORS | 如何把 Agent 包成 HTTP 服务、供网页调用 |
| 副本 | `agent_ui_api.py` | 146 | 与 08 完全同源的副本 | （用于 `uvicorn agent_ui_api:app` 的启动名） |

### 阅读路线建议

- **第一遍（骨架 4 篇）**：01 → 02 → 03 → 04。把「启动 / 状态 / 持久化 / 注销」这条**生命周期主线**走通。
- **第二遍（能力 3 篇）**：05 → 06 → 07。看「外部 API / 数据库 / 文件+代码」三种能力如何用**同一个工具范式**接入。
- **第三遍（接口 1 篇）**：08。看同一套 Agent 如何从「命令行脚本」变成「HTTP 服务」。
- **关键对照**：01 与 02~07 的关系是「样板 vs 变体」——后面每个例子都是 01 的 `agent_chat` 循环 + 换一套 `tools` / `tool_registry` / `memory`。**看懂 01，其余 7 篇是同一模式的不同装配**。

---

## 3. 四条工程主线（本章反复出现的设计决策）

### 主线一：工具三件套（`函数` + `tool_registry` + `tools`）

这是全章最统一的范式，7 个文件全部遵守：

```python
# ① 执行体：真正干活的普通函数
def get_weather(city: str) -> str: ...

# ② 注册表：运行时把「工具名 → 函数」映射起来（模型只给名字，靠它找到函数）
tool_registry = {"get_weather": get_weather}

# ③ 说明书：给模型看的 JSON Schema 声明（模型据此决定是否调用、怎么传参）
tools = [{"type": "function", "function": {"name": "get_weather", ...}}]
```

**为什么必须拆成三份**：
- **模型看不见 Python 函数**——它只能读 `tools` 里的 JSON 声明，据此产出 `tool_calls`（工具名 + JSON 参数）。
- **本地看不见模型意图**——它拿到 `tool_calls` 后，靠 `tool_registry` 把「工具名」翻译成「可调用对象」，再 `fn(**args)` 执行。
- **注册表是二者的「接头处」**——工具名的字符串是唯一的契约。

### 主线二：Agent 循环（`while True` + tool_calls 判定）

```python
while True:
    response = dashscope.Generation.call(model, messages=memory, tools=tools, result_format='message')
    message = response.output.choices[0].message
    tool_calls = getattr(message, 'tool_calls', None)
    if not tool_calls:                 # ← 模型给出最终回答，出口
        return message.content, memory
    memory = memory + [message]        # ← 把模型的「要调工具」这条也记进历史
    for call in tool_calls:            # ← 逐个执行工具
        fn_name = call['function']['name']
        fn_args = json.loads(call['function'].get('arguments') or '{}')
        tool_result = tool_registry.get(fn_name)(**fn_args)
        memory = memory + [{"role": "tool", "content": tool_result, "name": fn_name,
                            "tool_call_id": call.get('id', fn_name)}]
```

**两个必须记住的坑**：
- `call['function']['...']` 用**字典下标**取值，不是属性访问——dashscope 返回的 `tool_calls` 是 **dict 列表**，不是 OpenAI SDK 的对象。
- `arguments` 是**JSON 字符串**——必须 `json.loads(...)` 解析后才能 `**kwargs`；且要做 `or '{}'` 兜底（无参工具会返回空/None）。

### 主线三：记忆分层（三种 memory，三个层级）

| 层级 | 实现 | 存续范围 | 出现在 |
|---|---|---|---|
| 内存态 | 局部 `memory` 列表（参数传出传入） | 进程内、跨轮 | 01 / 02 / 05 / 06 / 07 / 08 |
| 持久态 | `PersistentJSONMemory`（load/save 到 `./memory/{sid}.json`） | 跨进程、跨设备 | 03 |
| 可注销态 | `LoggingMemory`（save/clear + 摘要日志） | 会话结束后清空 | 04 |

**一句话**：教材念叨的「记忆」，本质就是**同一个 `messages` 列表存在于哪个介质上**。

### 主线四：Agent 的「可替换性」——换零件不换骨架

7 个例子共用同一套 `agent_chat` 骨架，差异只在**换进来的零件**：

| 例子 | 换的是什么 | 骨架是否变 |
|---|---|---|
| 01 | 两个示例工具 | 不变 |
| 02 | 三个写 `task_state` 的工具 + 状态打印 | 不变 |
| 03 | memory 换成 `PersistentJSONMemory` | 不变 |
| 04 | memory 换成 `LoggingMemory` + 外套 `ManagedAgent` | 不变 |
| 05 | 换成一个真调 API 的工具 | 不变 |
| 06 | 换成两个操作 SQLite 的工具 | 不变 |
| 07 | 换成读/写/执行三个工具 | 不变 |
| 08 | 骨架外面再包一层 FastAPI | **不变** |

**这就是本章要教的最重要一件事**：Agent 的「智能」在模型里，Agent 的「能力」在工具里，Agent 的「编排」在那一圈 `while True` 里——三者解耦，所以可以自由装配。

---

## 4. 学习检查清单（读完自测）

- [ ] 能默写「工具三件套」，并说清为什么不能只写一个函数。
- [ ] 能解释 `tool_calls` 为什么用 `call['function']['name']` 而不是 `call.function.name`。
- [ ] 能说出 `arguments` 为什么要 `json.loads`，以及 `or '{}'` 兜底什么情况。
- [ ] 能说出「中断恢复」的两个关键动作（且知道 03 篇的落盘时机改在哪里）。
- [ ] 能解释 04 篇 `shutdown()` 为什么先 `save()` 再 `clear()`。
- [ ] 能说出 06 篇防 SQL 注入的关键写法（`?` 占位符）。
- [ ] 能指出 07 篇 `exec_code` 的安全风险，以及为什么教材只标「仅限受控环境」。
- [ ] 能画出 08 篇 `浏览器 → FastAPI /chat → agent_chat → dashscope` 的调用链。
- [ ] 能指出 08 篇的 `session_id` 为什么「预留但未使用」。

---

# 下篇：契约与验收

## 5. 全局技术约束（C-xx）

以下约束在 chapter2 全部 9 个文件中成立，是**改写后代码的公共契约**。

### C-01 禁止依赖虚构框架 `qwen_agent`

**约束**：任何文件**不得** `import` 或使用 `qwen_agent`、`QwenLLM`、`CompletionConfig`、`BaseTool`、`BaseMemory`。
**实现**：所有 `qwen_agent` 相关 import 均以注释保留在文件头，标注「虚构 API，运行报 ImportError」。
**验收**：9 个 .py grep `^from qwen_agent` / `^import qwen_agent` 应**零命中**（只允许出现在注释行）。

### C-02 LLM 调用统一走 dashscope 原生协议

```python
response = dashscope.Generation.call(
    model="qwen-plus",
    messages=memory,
    tools=tools,                  # 需要工具时携带
    temperature=0.2|0.3,
    max_tokens=256|512,
    result_format='message',      # ← 强制
)
content = response.output.choices[0].message.content
```
**约束**：
- 必须带 `result_format='message'`，否则 `response.output` 是字符串，`.choices[0]` 报错。
- 模型固定 `qwen-plus`；`temperature` 取 0.2（确定性任务：06/07/04）或 0.3（一般对话：01/02/03/05/08）。
**验收**：每个 `.Generation.call(` 均携带 `result_format='message'`。

### C-03 API Key 来自环境变量

```python
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key
```
**约束**：**不得**硬编码 key；所有文件从 `DASHSCOPE_API_KEY` 读取。
**已知风险**：`os.environ.get()` 未做空值校验——key 未设置时 `dashscope.api_key = None`，会在调用时报错（见缺口 G-03）。

### C-04 工具三件套齐备

**约束**：每个「工具」必须同时提供：
1. 执行体函数（普通 `def`，返回 `str`）；
2. 在 `tool_registry` 中登记（`名 → 函数`）；
3. 在 `tools` 列表中声明（`{"type":"function","function":{name,description,parameters}}`）。
**验收**：`set(tool_registry.keys()) == {t["function"]["name"] for t in tools}`（两集合必须相等）。

### C-05 工具函数永不抛异常

**约束**：所有工具执行体内部用 `try/except` 包裹，**失败时返回错误描述字符串**，绝不向上抛异常。
**理由**：工具结果会以 `role=tool` 回填给模型——它是一个**数据**，不是控制流异常；抛出会打断 Agent 循环。
**实例**：05 `get_weather`（`except Exception`）、06 `add_employee`/`query_employee`、07 `read_file`/`write_file`/`exec_code`。
**验收**：故意传入非法参数/不存在的路径，Agent 循环应继续并把错误信息交给模型，而非崩溃。

### C-06 工具结果回填格式固定

```python
memory = memory + [{
    "role": "tool",
    "content": tool_result,          # 字符串
    "name": fn_name,                 # 工具名
    "tool_call_id": call.get('id', fn_name)   # 关联调用（缺失时降级用工具名）
}]
```
**约束**：四个键都必须带；`tool_call_id` 必须有 `call.get('id', fn_name)` 兜底。
**理由**：模型需要 `tool_call_id` 把结果与它发出的调用对上号；降级兜底防止 `id` 缺失导致 KeyError。

### C-07 模型的「要调工具」那步也要记进历史

**约束**：在追加 `role=tool` 之前，必须先把模型返回的 `message`（含 `tool_calls`）append 进 `memory`。
**实现**：`memory = memory + [message]` 出现在每个 `for call in tool_calls` **之前**。
**理由**：否则历史里只有「工具结果」而没有「模型的调用指令」，消息序列不合法，下一轮模型会困惑。

### C-08 Agent 循环必须有终止出口

**约束**：`while True` 只能由「`tool_calls` 为空 → `return`」这一个出口退出。
**已知风险**：**无最大轮次上限**——若模型反复调工具将死循环（见缺口 G-04）。
**验收**：正常演示各篇均能在数轮内返回。

### C-09 `memory` 的两种传递约定需明确

| 约定 | 签名 | 用于 |
|---|---|---|
| **函数内自管** | `agent_chat(config, user_input, memory=None)` → `(reply, new_memory)` | 01/02/05/06/07/08 |
| **外部对象托管** | `agent_chat(config, user_input, memory_obj)` → `reply` | 03/04 |

**约束**：同一文件内必须**自洽**——返回 `(reply, memory)` 的必须由调用方接住并回传；托管对象的不应再返回 memory。
**验收**：03/04 篇 `agent_chat` 返回**单个字符串**（不是 tuple），调用处不接收 memory。

### C-10 「可重复运行」的清理约定

**约束**：涉及落盘的例子（03/04/06/07）在 `__main__` 或 `run_*()` 开头**主动清理上次残留**（删 JSON / 删 db / 删 test.txt）。
**理由**：教材例子需**幂等**——反复运行应得到一致结果（否则 03 篇的「中断恢复」演示会被旧文件污染）。
**验收**：连续运行两次同一文件，输出结构一致。

### C-11 所有示例默认打印可见过程

**约束**：关键步骤（用户输入、工具调用、工具结果、状态变化、最终回复）应通过 `print` 或 `logging` 输出。
**理由**：本章是**教学/学习**用途——过程可见比结果正确更重要。
**实现**：01 用 `logging` 写 `agent_startup.log`；其余用 `print`。

### C-12 教材原逻辑「能留则留」

**约束**：改写时**保留教材原本想教的核心逻辑**，只替换框架依赖部分。
**实例**：
- 03 篇的 `load/save` 逻辑**逐行保留**，只去掉 `BaseMemory` 继承；
- 05 篇 `requests.get(url, timeout=5)` + JSON 解析**原样保留**；
- 06 篇 `sqlite3` 操作 + `?` 占位符**原样保留**；
- 08 篇 FastAPI / Pydantic / CORS **原样保留**。
**验收**：对照教材原代码，核心业务逻辑行应能一一对应（仅签名/包装层改变）。

---

## 6. 逐文件契约（F-01 ~ F-08）

每份契约结构：**意图 / 输入 / 处理 / 输出 / 契约 / 验收标准 / 已知风险 / 教材问题（注释实录）**。

---

### F-01 `01_智能启动过程展示.py`（161 行）——样板篇

**意图**：演示 Agent 启动的四个环节（模型加载 / 工具注册 / 系统提示词 / 记忆注入）+ 函数调用工具调度 + 多轮日志。

**输入**：`run_startup_sequence()` 内的两轮硬编码输入（"请执行一次系统检查" / "请告诉我现在几点"）。

**处理**：
1. `build_agent()` → 返回 config（`name/model/temperature/max_tokens/system_message`）；
2. `agent_chat(config, user_input, memory)`：
   - `memory = [{"role":"system",...}] + [{"role":"user",...}]`（记忆注入）；
   - 循环 `Generation.call(messages=memory, tools=tools)`；
   - 有 `tool_calls` → 执行 → 回填 → 再循环；无 → 返回 `(reply, memory)`。

**两个工具契约**：

| 工具 | 签名 | 参数 | 返回 |
|---|---|---|---|
| `get_current_time` | `() -> str` | 无 | `"当前时间是：YYYY年MM月DD日 HH:MM:SS"` |
| `startup_check` | `() -> str` | 无 | `"系统初始化检查通过：模型加载完成，工具已注册，..."` |

**日志契约**：`logging.basicConfig(filename='agent_startup.log', level=INFO, format='%(asctime)s - %(levelname)s - %(message)s')`。

**输出**：两行 `>> ...响应：...` + `agent_startup.log` 落盘。

**验收标准**：
- V-01-A：`>> 系统检查响应：` 内容含「初始化检查通过」或模型对该工具结果的自然语言总结。
- V-01-B：`>> 当前时间响应：` 含今天的日期/时间。
- V-01-C：`agent_startup.log` 生成，含「启动Agent构建流程」「模型请求调用工具」「模型回复」等记录。
- V-01-D：第二轮对话能复用第一轮的 `memory`（虽无强依赖，但传参链路正确）。

**已知风险**：
- `tools` 中的 `parameters` 用 `{"type":"object","properties":{}}` ——无参工具的合法最小声明，但部分模型可能仍尝试传参。
- `memory = memory + [message]` 把**dashscope 的 Message 对象**（非 dict）混入列表——实际能跑（dashscope 接受），但类型上不纯（dict 与对象混存）。

**教材问题（文件头注释实录）**：
> 原写法：`qwen_agent` 的这些 API 是虚构的（真实 qwen-agent 包没有顶层 `Agent/Tool/ChatMessage` 导出，也没有 `QwenLLM` / `CompletionConfig` 类），运行会报 ImportError，无法执行。
> 改写：工具注册 = "可执行函数 + 给模型看的 function calling 声明" 两部分；`build_agent()` 内用 config 字典替代虚构类的拼装。

---

### F-02 `02_自动追踪任务状态.py`（138 行）——状态篇

**意图**：演示「状态追踪」——用显式 `task_state` 字典记录任务进度，让模型在多轮中读到累积信息。

**状态契约**：
```python
task_state = {"topic": None, "time": None, "attendees": None}
```
- 工具执行时**写入**该字典（副作用）；
- 每轮结束时 `print(f"[状态追踪] 当前任务状态: {task_state}")` **打印**演进。

**三个工具契约**：

| 工具 | 参数 | 副作用 | 返回 |
|---|---|---|---|
| `set_topic` | `topic: str` | `task_state["topic"] = topic` | `"会议主题已设置为：{topic}"` |
| `set_time` | `time: str` | `task_state["time"] = time` | `"会议时间已设置为：{time}"` |
| `set_attendees` | `attendees: str` | `task_state["attendees"] = attendees` | `"与会人员已设定为：{attendees}"` |

**处理**：4 轮对话（设主题 / 设时间 / 设人员 / 总结），每轮传入上一轮返回的 `memory`。

**验收标准**：
- V-02-A：第 1~3 轮结束后打印的 `task_state` 对应字段由 `None` 变为实际值。
- V-02-B：第 4 轮「请总结一下目前的会议信息」的回复能引用前述主题/时间/人员（证明状态被模型读到）。
- V-02-C：`arguments` 解析正确（`json.loads(... or '{}')`），带参工具能收到正确参数。

**已知风险 / 关键设计点**：
- ⚠️ **`task_state` 是模块级全局变量**——单进程单会话可用，多会话会互相污染（见缺口 G-05）。
- **真正的「状态传递」其实靠两条路**：① `task_state` 全局字典（工具间共享）；② `memory` 列表里的 `role=tool` 结果（模型读取）。二者**并存**——模型真正「看到」的是 `memory` 里的工具返回文本，`task_state` 主要服务于本地逻辑。
- ⚠️ 未重置 `task_state`——模块重载才归零；同进程重复调用 `run_tracking_test()` 会累积（见 C-10 的例外：本篇**未**做清理，因为它是内存态）。

**教材问题（文件头注释实录）**：
> 原写法用 `SimpleMemory()` 存状态；改写为显式的 `task_state` 字典——工具执行时把信息写进来，"总结会议信息"时模型从工具回传结果中读到，这就是状态追踪。
> 原写法三个继承虚构 `BaseTool` 的工具类（含 `params.get` 取参）→ 改写为普通函数（带参数）+ tools 说明书 + tool_registry 注册表。

---

### F-03 `03_对话终端恢复功能.py`（170 行）——持久化篇

**意图**：演示「中断恢复」——把上下文持久化到 JSON 磁盘文件，用同一 `session_id` 重建即可续上断点。

**`PersistentJSONMemory` 契约**：

| 方法 | 行为 |
|---|---|
| `__init__(session_id, path="./memory")` | `os.makedirs(path, exist_ok=True)`；`self.memory_file = path/{session_id}.json`；`self.messages = self.load()` |
| `load()` | 文件存在 → `json.load`（UTF-8）；否则返回 `[]` |
| `save()` | `json.dump(self.messages, ensure_ascii=False, indent=2)` |
| `add_message(msg)` | append + **立即 save** |
| `get()` | 返回 `self.messages` |

**工具契约**：`log_user_input(content: str) -> str` → `"记录完成：{content}"`。

**Agent 循环契约（与 01/02 的关键差异）**：
- `memory = list(memory_obj.get())`（**从持久层取**，而非自管）；
- 首轮为空时注入 system_message；
- 获得最终回答时：`memory_obj.messages = memory; memory_obj.save()`（**每轮结束统一落盘一次**）；
- 返回**单个字符串**（不是 tuple）。

**主流程契约（`simulate_session`）**：
1. `session_id = "user_20250501"`；
2. **先删旧文件**（保证演示可重复）；
3. 3 轮对话（订机票 / 时间 / 记录需求）→ 每次 `save()`；
4. 打印「模拟中断后重新启动...」；
5. **用同一 session_id 重新 `build_agent`** → `load()` 恢复全部历史；
6. 第 4 轮（"现在继续，出发地是北京"）能接续之前上下文。

**验收标准**：
- V-03-A：`./memory/user_20250501.json` 在第 3 轮后存在，内容为完整消息列表。
- V-03-B：`build_agent` 重建后的第 4 轮回复体现「记得」之前的机票/时间需求。
- V-03-C：连续运行两次，输出结构一致（`__main__` 内先删旧文件）。

**已知风险**：
- ⚠️ `add_message` 有 `save()`，但**主流程用的是 `memory_obj.messages = memory` 整体替换 + `save()`**——`add_message` 实际上**未被调用**（死代码，教材逻辑残留）。
- ⚠️ 持久化的是**完整 messages**（含 system），文件随轮次线性增长，无截断策略（见缺口 G-06）。
- ⚠️ `tool_registry` 里的 `log_user_input` 工具依赖模型主动调用；若模型不调，日志不落——不影响持久化（持久化在循环末尾无条件执行）。

**教材问题（文件头注释实录）**：
> 原写法：`qwen_agent` 的这些 API 是虚构的（真实包没有这些类），运行报 ImportError。
> 这部分原代码本身就是标准 Python（json 读写），只是继承了一个不存在的 `BaseMemory`——去掉继承、去掉 `add_message` 里的强制落盘时机调整，核心的 `load/save` 逻辑原样保留。

---

### F-04 `04_具备注销机制.py`（193 行）——生命周期篇

**意图**：演示「注销 = 安全、完整地释放资源」，尤其强调**不是简单删除，而是先留底再删**。

**`LoggingMemory` 契约**（注意与 F-03 的差异：字段名是 `logs` 不是 `messages`）：

| 方法 | 行为 |
|---|---|
| `__init__(session_id)` | `memory_file = {MEMORY_PATH}/{session_id}.json`；`self.logs = []` |
| `add_message(msg)` | `self.logs.append(msg)`（**不落盘**） |
| `get()` | 返回 `self.logs` |
| `save()` | `makedirs` + `json.dump(logs, ...)` |
| `clear()` | 文件存在则 `os.remove`（**释放存储**） |

**`ManagedAgent` 契约**：
- `__init__(session_id)`：建 `LoggingMemory` + config（`temperature=0.2`, `max_tokens=256`）；
- `chat(user_input) -> str`：内部调 `agent_chat`，返回回复；
- `shutdown()`：**三步**
  1. `self.memory.save()`（注销前留底 JSON）；
  2. `self.memory.clear()`（删 JSON 释放存储）；
  3. 写 `{sid}_log.txt`——逐条 `[{时间}] {role}: {content[:50]}`（**摘要审计日志**）。

**工具契约**：`handle_task(task: str) -> str` → `"任务『{task}』已完成"`。

**输出**：对话两轮 + 注销 + 两行验证 `JSON 文件存在=False` / `日志文件存在=True`。

**验收标准**：
- V-04-A：`shutdown()` 后 `{sid}.json` 不存在。
- V-04-B：`shutdown()` 后 `{sid}_log.txt` 存在，且含 role/content 摘要行。
- V-04-C：连续运行两次结果一致（`run_task_session` 开头清理 `.json` 与 `_log.txt`）。
- V-04-D：⚠️ **注意一个真实缺陷**——`shutdown()` 里先 `save()` 再 `clear()`，**但 `save()` 写出的 JSON 紧接着就被 `clear()` 删掉**。所以「留底」实际靠的是**第 3 步的 txt 摘要**，而非 JSON。**这是一个语义与实现不符的点**（注释宣称"先落盘一份日志供事后审计"，但 JSON 被删、txt 是另一份）。**建议**：要么 `save()` 到另一路径作为归档，要么删掉 `save()` 并把注释改为「直接生成摘要日志」。

**已知风险**：
- ⚠️ 上条 V-04-D（save 后即删，语义矛盾）。
- ⚠️ `agent_chat` 里 `memory_obj.logs = memory` **未调用 save()**——所以 `chat()` 期间**不落盘**，只在 `shutdown()` 落盘。若中途崩溃则日志全丢（与 03 篇的"每轮落盘"相反，是刻意的对比设计，但需读者注意）。
- `MEMORY_PATH = "./memory_cleanup"` 与 03 篇的 `./memory` 分开，避免互相干扰。

**教材问题（文件头注释实录）**：
> 原写法：`qwen_agent` 的这些 API 是虚构的（真实包没有这些类），运行报 ImportError。
> 改写：`chat()` 方法内部调 `agent_chat()`，注销逻辑全显式可见（原写法 `self.agent.chat()` 是框架黑盒）。

---

### F-05 `05_查询外部天气API.py`（138 行）——外部 API 篇

**意图**：演示工具如何**突破模型自身能力边界**——调用真实 Web API 获取实时数据。

**工具契约（`get_weather`）**：
```python
def get_weather(city: str) -> str
```
| 步骤 | 逻辑（**教材原逻辑保留**） |
|---|---|
| 1 | `city = city.strip()`；空 → 返回 `"请输入有效的城市名"` |
| 2 | `url = f"https://wttr.in/{city}?format=j1"`；`requests.get(url, timeout=5)` |
| 3 | `resp.status_code != 200` → 返回 `"查询失败，状态码：{code}"` |
| 4 | 解析 `data["current_condition"][0]` → `temp_C` / `humidity` / `weatherDesc[0].value` |
| 5 | 返回 `"{city}当前天气：{desc}，温度：{temp}℃，湿度：{humidity}%"` |
| 6 | `except Exception as e` → 返回 `"调用天气API出错：{e}"` |

**输出**：三行 `>>`（北京 / 上海 / 深圳），内容为模型对天气数据的自然语言陈述。

**验收标准**：
- V-05-A：至少一个城市返回含「温度」「℃」「湿度」字样的回复。
- V-05-B：`timeout=5` 生效——网络不可达时 5 秒内返回错误串而非挂起。
- V-05-C：传入空字符串/非法城市名，返回友好提示而非异常。

**已知风险**：
- ⚠️ **依赖外网可达性**——`wttr.in` 在国内可能不稳定/慢（见缺口 G-07）；建议离线时可换成国内天气 API。
- ⚠️ 无重试/无缓存——同一城市反复问会反复打 API（见缺口 G-07）。
- `requests` **无 `verify`/代理配置**——企业网络下可能失败。

**教材问题（文件头注释实录）**：
> 原写法：`qwen_agent` 的这些 API 是虚构的（真实包没有这些类），运行报 ImportError。
> 改写：普通函数（带参数）+ tools 说明书 + tool_registry 注册表；但 `run()` 里的 `requests.get` 真实 API 调用逻辑**原样保留**——这是"调用外部 API"的核心教学点。

---

### F-06 `06_sqlLite数据库的读写操作.py`（183 行）——数据库篇

**意图**：演示 Agent 如何做**结构化数据管理**（增 / 查），并示范 SQL 注入防护。

**DB 契约**：
```sql
CREATE TABLE IF NOT EXISTS employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    department TEXT,
    title TEXT
)
```
`DB_PATH = "./employee.db"`；`init_db()` 幂等建表。

**两个工具契约**：

| 工具 | 签名 | 关键实现 |
|---|---|---|
| `add_employee(name, department="", title="")` | 插入 | `cursor.execute("INSERT INTO employees (...) VALUES (?, ?, ?)", (name, department, title))` |
| `query_employee(name="")` | 查询 | `name` 非空 → `WHERE name = ?`；空 → 查全部；无结果 → `"未找到匹配员工"`；否则 `"n \| d \| t"` 逐行拼接 |

**安全契约**：**必须使用 `?` 占位符参数化查询，禁止字符串拼接 SQL**（06 篇注释明确此点）。

**输出**：三行 `>>`（添加王小明 / 查询王小明 / 查看全部）。

**验收标准**：
- V-06-A：添加后查询到「王小明 \| 技术部 \| 高级工程师」。
- V-06-B：查全部返回上述一行。
- V-06-C：传入 `name="' OR '1'='1"` 之类的注入串，**不会**返回全部数据（占位符使其被当作字面值）。
- V-06-D：连续运行两次结果一致（`run_demo` 开头删 `employee.db`）。

**已知风险**：
- ⚠️ **每次工具调用都 `connect`/`close`**——高频调用下开销大，且无连接池（见缺口 G-08）。
- ⚠️ `query_employee` 是**精确匹配**（`= ?`），无法模糊查（对 Agent 场景体验一般）。
- ⚠️ 无事务边界保护（单条 execute 后立即 commit，无回滚路径）——单条语句下影响有限。
- `title`/`department` 为 `TEXT` 无长度约束。

**教材问题（文件头注释实录）**：
> 原写法：`qwen_agent` 的这些 API 是虚构的（真实包没有这些类），运行报 ImportError。
> 改写：`AddEmployeeTool` + `QueryEmployeeTool` 两个工具类 → 普通函数 + tools 说明书 + 注册表；但 `run()` 里的 `sqlite3` 操作逻辑**原样保留**——这是"数据库交互"的核心教学点。使用 `?` 占位符是 SQL 注入防护的标准写法（绝不能用字符串拼接）。

---

### F-07 `07_读写本地文件.py`（186 行）——文件与代码执行篇

**意图**：演示 Agent 直接操作本地文件系统 + 执行代码，从「语言模型」进化为「自动化助手」。

**三个工具契约**：

| 工具 | 签名 | 行为 | 失败处理 |
|---|---|---|---|
| `read_file(filepath)` | → str | `os.path.exists` 检查 → `open(..., encoding="utf-8").read()` | 不存在 → `"文件不存在：{path}"`；异常 → `"读取失败：{e}"` |
| `write_file(filepath, content)` | → str | `open(..., "w", encoding="utf-8").write(content)` | 异常 → `"写入失败：{e}"`；成功 → `"内容已成功写入文件：{path}"` |
| `exec_code(code)` | → str | `local_vars={}; exec(code, {}, local_vars)` | 异常 → `"执行出错：" + traceback.format_exc(limit=2)`；成功 → `"执行成功，输出变量：" + str(local_vars)` |

**输出**：三行 `>>`（写 test.txt / 读 test.txt / 执行 `a=5;b=3;c=a*b`）。

**验收标准**：
- V-07-A：`test.txt` 内容为「你好，这是智能体写入的内容」。
- V-07-B：读文件回复复述该内容。
- V-07-C：执行代码的回复中出现 `c: 15`（`local_vars` 里的输出变量）。
- V-07-D：执行 `1/0` 之类的错误代码 → 返回精简堆栈（`limit=2`），不崩。

**已知风险（重要）**：
- 🔴 **`exec_code` 是任意代码执行（RCE）入口**——模型可被诱导执行 `os.system("rm -rf /")` 等。教材标注「仅限受控环境」，但**代码层面无任何沙箱**（见缺口 G-01）。**这是本章最高风险项**。
- `write_file` **无路径白名单**——可写任意路径（含系统文件）。
- `read_file` **无路径白名单**——可读任意可读文件（含密钥文件）。
- `traceback.format_exc(limit=2)` 会**泄漏本地路径/代码片段**给模型（进而可能回显给用户）。

**教材问题（文件头注释实录）**：
> 原写法：`qwen_agent` 的这些 API 是虚构的（真实包没有这些类），运行报 ImportError。
> 改写：`ReadFileTool` / `WriteFileTool` / `ExecCodeTool` 三个工具类 → 普通函数 + 说明书 + 注册表；但 `run()` 里的文件读写 / `exec` 逻辑**原样保留**——这是"操作本地文件与执行代码"的核心教学点。

---

### F-08 `08_基于FastAPI的UI中间API接口系统.py`（147 行）+ `agent_ui_api.py`（146 行副本）——对外接口篇

**意图**：把 Agent 从「命令行脚本」升级为「HTTP 服务」，供网页/第三方调用。

**HTTP 契约**：

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| `GET` | `/` | — | `{"message": "Agent API 运行中"}` |
| `POST` | `/chat` | `ChatRequest{session_id: str, message: str}` | `ChatResponse{session_id: str, reply: str}` |

**Pydantic 模型契约**：
```python
class ChatRequest(BaseModel):  session_id: str;  message: str
class ChatResponse(BaseModel): session_id: str;  reply: str
```

**CORS 契约**：`allow_origins=["*"]`, `allow_credentials=True`, `allow_methods=["*"]`, `allow_headers=["*"]`。

**工具契约**：`add_record(category: str, amount: str) -> str` → `"已记录消费：{category} - {amount}元"`。

**`/chat` 处理契约**：
```python
reply, _memory = agent_chat(agent_config, req.message)   # 注意：memory 未持久化
return ChatResponse(session_id=req.session_id, reply=reply)
```

**副本说明**：`agent_ui_api.py` 与 08 内容同源（仅注释多一行 `uvicorn` 启动说明）。**用途**：`uvicorn agent_ui_api:app --reload --port 8080`（模块名必须是合法 Python 标识符，中文文件名不适用，故另存一份英文名副本）。

**验收标准**：
- V-08-A：`uvicorn agent_ui_api:app --reload --port 8080` 能启动。
- V-08-B：`curl -X POST http://localhost:8080/chat -H "Content-Type: application/json" -d '{"session_id":"user123","message":"刚刚买菜花了20元"}'` 返回含 `reply` 的 JSON。
- V-08-C：`GET /` 返回 `{"message":"Agent API 运行中"}`。
- V-08-D：浏览器跨域调用不被拦截（CORS 生效）。

**已知风险 / 关键设计点**：
- ⚠️ **`session_id` 被接收但未使用**——`/chat` 里 `memory` 被丢弃（`_memory`），**每次请求都是全新对话**。注释明确：「`session_id` 原代码就预留而未用于记忆，这里同样先不使用」。这是**真实的未完成设计**（见缺口 G-02）——与 03 篇的持久化能力**没有对接**。
- ⚠️ `allow_origins=["*"]` **搭配 `allow_credentials=True`**：浏览器规范下 `*` 与 credentials 同时存在时 credentials 实际不生效（安全上等于未认证）；且 `*` 过于宽松（见缺口 G-09）。
- ⚠️ **无鉴权、无限流**——任何人都能调用（对比 chapter12 的 4 层防护）。
- `Request` / `Optional` **已导入但未使用**（无用 import）。
- `agent_config` 是**模块级单例**——多 worker 下各自持有一份（python 的 GIL 下无状态，问题不大）。

**教材问题（文件头注释实录）**：
> 原写法：`qwen_agent` 的这些 API 是虚构的（真实包没有这些类），运行报 ImportError。
> FastAPI / pydantic / CORS 是真实可用的第三方库，原样保留——这是"把 Agent 包成 HTTP 服务"的关键。
> `reply = agent_instance.chat(req.message)` ← 虚构框架的黑盒调用 → 改写为调 `agent_chat` 循环。

---

## 7. 全章验收清单（V-01 ~ V-12）

### 7.1 运行层验收（能否跑）

| 编号 | 验收项 | 期望 |
|---|---|---|
| V-01 | `python 01_...py` | 打印两轮响应 + 生成 `agent_startup.log` |
| V-02 | `python 02_...py` | 4 轮对话 + 状态字典逐步被填充 |
| V-03 | `python 03_...py` | 3 轮 + 中断 + 重建恢复第 4 轮 + `./memory/user_20250501.json` |
| V-04 | `python 04_...py` | 2 轮 + 注销 + 两行验证（JSON=False / log=True） |
| V-05 | `python 05_...py` | 3 城天气查询（需外网） |
| V-06 | `python 06_...py` | 增查员工 3 轮 + 生成 `employee.db` |
| V-07 | `python 07_...py` | 写/读/执行 3 轮 + 生成 `test.txt` |
| V-08 | `uvicorn agent_ui_api:app --port 8080` + `curl` | HTTP 服务可用，`/chat` 返回 reply |

### 7.2 契约层验收

| 编号 | 契约 | 对应 | 验证方式 |
|---|---|---|---|
| V-09 | 无 `qwen_agent` 实际 import（C-01） | 全章 | grep 只命中注释 |
| V-10 | 工具三件套键集相等（C-04） | 全章 | `set(registry) == {t.name for t in tools}` |
| V-11 | `.Generation.call` 均带 `result_format='message'`（C-02） | 全章 | grep 上下文 |
| V-12 | 工具函数不抛异常（C-05） | 05/06/07 | 传非法参数，循环继续 |

### 7.3 学习层验收（人能否讲清）

- [ ] 能不看代码写出 `agent_chat` 循环的骨架。
- [ ] 能说清「工具的 JSON 声明」与「工具的执行函数」各自被谁使用。
- [ ] 能指出 03 与 04 两篇在「落盘时机」上的相反设计及其取舍。
- [ ] 能说出 08 篇 `session_id` 为什么没用上，以及如果要用该怎么接 03 篇。

---

## 8. 已知缺口与后续改进（Gap Analysis）

按**风险等级**排序（🔴 高 / 🟠 中 / 🟡 低）。

| 编号 | 等级 | 缺口 | 影响 | 建议改进 | 对照章节 |
|---|---|---|---|---|---|
| G-01 | 🔴 | `exec_code` + `read_file`/`write_file` **无任何沙箱/路径白名单** | 任意代码执行、任意文件读写——可被提示注入利用 | 加路径白名单 + `exec` 禁用 `import`/`open`/`__builtins__` 白名单，或改用受限表达式求值 | chapter13（safe_eval AST 白名单） |
| G-02 | 🟠 | 08 篇 `session_id` 接收但**未与记忆对接** | HTTP 服务无多轮能力，每次请求从零开始 | 用 `session_id` 索引 03 篇的 `PersistentJSONMemory`（或 Redis） | chapter12（多层级缓存/记忆） |
| G-03 | 🟠 | `os.environ.get('DASHSCOPE_API_KEY')` **无空值校验** | key 未设置时报错信息晦涩 | 启动时校验并给出明确提示 | chapter12（配置校验） |
| G-04 | 🟠 | Agent 循环**无最大轮次上限**（C-08） | 模型反复调工具 → 死循环 | 加 `max_rounds`（如 10）+ 超限降级返回 | chapter13（`MAX_TOOL_ROUNDS`） |
| G-05 | 🟠 | 02 篇 `task_state` 是**模块级全局**，多会话污染 | 并发/多用户时状态串味 | 把状态挂在会话对象上（或按 `session_id` 分片） | chapter12 |
| G-06 | 🟠 | 03 篇持久化的 messages **随轮次线性增长**，无截断 | 长会话文件膨胀、超 token 上限 | 加窗口截断 / 摘要压缩 | chapter12（记忆分层） |
| G-07 | 🟠 | 05 篇依赖外网 `wttr.in`，**无重试/无缓存/无超时降级** | 网络差时演示失败 | 加指数退避重试 + 结果缓存 + 备用 API | chapter12（容错五件套） |
| G-08 | 🟡 | 06 篇每次工具调用**都重建 SQLite 连接** | 高频下开销大 | 连接复用 / 上下文管理器 | — |
| G-09 | 🟠 | 08 篇 CORS `*` + `allow_credentials=True`，且**无鉴权无限流** | 服务裸奔，任何人可调 | 限定 origins + API Key + 限流 | chapter12（4 层安全） |
| G-10 | 🟡 | 04 篇 `shutdown()` **`save()` 后立即 `clear()`**（语义与注释矛盾） | 「留底」实际靠 txt 摘要，JSON 白写一次 | 归档到另一路径，或删 `save()` 并改注释 | — |
| G-11 | 🟡 | 03 篇 `add_message()` 是**死代码**（未被调用） | 读者困惑「到底哪里落盘」 | 删掉或改为真正被调用 | — |
| G-12 | 🟡 | 07 篇 `traceback.format_exc(limit=2)` **泄漏本地路径**给模型 | 信息泄露风险 | 只回传异常类型与用户可见原因 | chapter13（结构化错误） |
| G-13 | 🟡 | `memory = memory + [message]` 把 **dashscope 对象混入 dict 列表** | 类型不纯（能跑但不规范） | 统一转为 dict（`message.model_dump()` 或手工转） | — |
| G-14 | 🟡 | 全章**无类型注解**（函数返回 `str` 有，但参数/中间量缺） | 可读性/可维护性一般 | 补齐类型注解 | — |

### 缺口优先级建议

- **P0（安全）**：G-01（沙箱）、G-09（服务安全）
- **P1（正确性/健壮性）**：G-02（会话对接）、G-03（配置校验）、G-04（轮次上限）、G-06（记忆截断）
- **P2（一致性/整洁）**：G-05、G-07、G-10、G-11、G-12
- **P3（细节）**：G-08、G-13、G-14

---

## 附录 A：Agent 循环标准模板（本章通用骨架）

```python
def agent_chat(config, user_input, memory=None):
    # ① 记忆注入
    if memory is None:
        memory = [{"role": "system", "content": config["system_message"]}]
    memory = memory + [{"role": "user", "content": user_input}]

    # ② 循环：模型决策 → 工具执行 → 回填 → 再决策
    while True:
        response = dashscope.Generation.call(
            model=config["model"], messages=memory, tools=tools,
            temperature=config["temperature"], max_tokens=config["max_tokens"],
            result_format='message',
        )
        message = response.output.choices[0].message
        tool_calls = getattr(message, 'tool_calls', None)

        # ③ 终止条件：无工具调用
        if not tool_calls:
            reply = message.content
            memory = memory + [{"role": "assistant", "content": reply}]
            return reply, memory

        # ④ 工具分支
        memory = memory + [message]                      # 先记下"模型要调工具"
        for call in tool_calls:
            fn_name = call['function']['name']           # dict 下标，不是属性
            fn_args = json.loads(call['function'].get('arguments') or '{}')
            fn = tool_registry.get(fn_name)
            tool_result = fn(**fn_args) if fn else f"未注册的工具: {fn_name}"
            memory = memory + [{"role": "tool", "content": tool_result,
                                "name": fn_name, "tool_call_id": call.get('id', fn_name)}]
```

## 附录 B：工具三件套速查

| 份 | 变量 | 谁用 | 作用 |
|---|---|---|---|
| ① 执行体 | `def foo(...) -> str` | 本地 | 真正干活 |
| ② 注册表 | `tool_registry = {"foo": foo}` | 本地 | 名字 → 函数 |
| ③ 说明书 | `tools = [{"type":"function","function":{name,description,parameters}}]` | **模型** | 决定调不调、传什么参 |

**三者靠「工具名字符串」对齐**——C-04 的键集相等检查就是验证这条契约。

## 附录 C：记忆三形态速查

| 形态 | 类/变量 | 落盘时机 | 存续 | 文件 |
|---|---|---|---|---|
| 内存列表 | `memory`（参数传递） | 从不 | 进程内 | 01/02/05/06/07/08 |
| JSON 持久 | `PersistentJSONMemory` | 每轮结束 | 跨进程 | 03 |
| 可注销 | `LoggingMemory` | 仅 shutdown 时 | 会话内 → 清空 | 04 |
