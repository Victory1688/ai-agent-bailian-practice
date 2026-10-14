# 第 4 章 规范说明书（spec.md）——LangChain 框架化：用声明换控制权

> **SDD 定位**：本文回答 *「手写 Agent 之后，为什么要用框架、用框架的代价是什么」*。
> **上篇（意图与学习路径）**回答 *为什么学、学什么、怎么学*；
> **下篇（契约与验收）**回答 *每个文件到底承诺了什么、怎么验证、还缺什么*。
> **主线**：char02 手写了 `agent_chat` 循环、工具注册表、记忆管理——**看透了原理**。
> char04 把这些**全部交给 LangChain 组件**——**享受效率**。
> 本章的核心命题是「**用声明换控制权**」：写得少了，但黑盒多了；
> 而本章最大的教学价值在于——**教材 7 篇里有 6 篇自带 bug，且涵盖 AI 应用代码的六类死法**。
>
> 适用范围：`D:/AiWorkOut/aiAgentCode/chapter04/`（7 个 .py / 678 行）。
> 契约字段一律**从代码事实反推**，不臆造；教材 bug 与修复现场一并留痕。

---

# 上篇：意图与学习路径

## 1. 章意图（Why）

### 1.1 教材原版想解决什么

教材用一章讲 LangChain 的「框架化开发」，把 Agent 的各个组件逐一交给框架托管：

| 教材概念 | 想说明什么 |
|---|---|
| Chains 链式构造器 | **固定流水线**——把复杂任务拆成有序步骤，变量在链间**自动接力** |
| Tools & Agent 集成 | **ReAct 循环**——模型自主「思考 → 行动 → 观察」，动态选工具 |
| Memory 记忆管理 | **框架托管记忆**——保留对话历史，让省略主语的追问成为可能 |
| 沙箱 Sandbox | **工具安全执行**——限时 + 字符白名单 + 空 `builtins` 三道防线 |
| 多工具调用顺序管理 | **模型自主规划**——多工具协同的调用顺序由模型现场决定 |
| 自定义提示词驱动 | **提示词即 Agent 的「灵魂」**——改 prompt 就是改人格 |
| 工具链动态规划 | **跨轮工具链**——搜书 → 记住第一本 → 查详情，靠记忆接力 |

### 1.2 教材原版的三大断点（结构性问题）

本章 7 个例子**全部无法直接运行**，卡在三处：

| 断点 | 涉及例子 | 具体表现 |
|---|---|---|
| 🔴 **`langchain` 0.x import 路径全部失效** | 全部 7 篇 | `from langchain.llms import OpenAI` / `from langchain.agents import ...` / `from langchain.memory import ...` / `from langchain.prompts import ...` / `from langchain.chat_models import ChatOpenAI` —— 1.x 已重组：经典链与 Agent 收纳进 **`langchain_classic`**，核心组件移到 **`langchain_core`**，`OpenAI` 类**已移除** |
| 🔴 **`OpenAI` / `ChatOpenAI` 模型类不可直连** | 全部 7 篇 | 需要 `OPENAI_API_KEY` 且国内无法访问 OpenAI 官方服务 |
| 🟠 **平台不兼容：`signal.SIGALRM` 是 Unix 专属** | 04 篇 | `signal.signal(signal.SIGALRM, ...)` 在 Windows 上抛 `AttributeError`（`SIGALRM` 属性不存在）。教材默认 Linux/Mac，**目标环境是 Windows 时必须替换限时方案** |

### 1.3 教材的六类「死法」（本章最大教学价值）

本章的**独有特色**：7 篇里有 6 篇**自带 bug**，且覆盖 AI 应用代码的**六类常见死法**。这些 bug 与版本迁移无关——**在教材原版 0.x 环境同样会出错**：

| # | 死法 | 篇目 | 现象 | 修复 |
|---|---|---|---|---|
| 1 | **import 断裂** | 全部 | `ImportError` | `langchain_classic` / `langchain_core` |
| 2 | **模型不可直连** | 全部 | 认证失败/超时 | `ChatTongyi` + 环境变量 |
| 3 | **API 误用（硬错误）** | 01 | `full_chain.run(...)` 多输出键必抛 `ValueError: run not supported when there is not exactly one output key` | 改 `invoke({...})` |
| 4 | **类型错配（硬错误）** | 02 | `"20" * 7.25` 必抛 `TypeError: can't multiply sequence by non-int of type 'float'` | 显式 `float(amount)` 转换 |
| 5 | **平台不兼容** | 04 | `SIGALRM` 在 Windows 抛 `AttributeError` | 线程限时（`Thread.join(timeout=)`） |
| 6 | **概念代码（最深）** | 06 | `custom_prompt` 覆盖**不生效**（0.x 同样错，**查框架源码实证**） | 改用官方 `prefix` / `suffix` 通道 |
| 7 | **静默失败（最隐蔽）** | 07 | `memory_key="history"` 与默认模板 `{chat_history}` **不匹配** → **不报错但「失忆」** | 改 `memory_key="chat_history"` |
| 8 | **无兜底网络调用** | 07 | `openlibrary.org` 国内不可达 → `ConnectTimeout` 从 `tool.run` 一路抛到顶层，**打崩 `AgentExecutor`** | `try/except` + `timeout=5` + 模拟数据 |

⚠️ **03 与 05 篇无隐藏 bug** —— 改写后即可运行。

### 1.4 本章改写要解决什么

| 教材原实现 | 改写后 | 教学点 |
|---|---|---|
| `from langchain.llms import OpenAI` | 删除 + `ChatTongyi(model="qwen-plus")` | 模型适配层统一 |
| `from langchain.prompts import PromptTemplate` | `from langchain_core.prompts import PromptTemplate` | 1.x 新家 |
| `from langchain.chains import LLMChain, SequentialChain` | `from langchain_classic.chains import ...` | 经典链收纳 |
| `from langchain.agents import Tool, initialize_agent` | `from langchain_classic.agents import ...` | 经典 Agent 收纳 |
| `from langchain.agents.agent_types import AgentType` | `from langchain_classic.agents import AgentType`（或 `langchain_classic.agents.agent_types`） | 同上门 |
| `from langchain.memory import ConversationBufferMemory` | `from langchain_classic.memory import ConversationBufferMemory` | 同上门 |
| `from langchain.tools import tool` | `from langchain_core.tools import tool` | 同门 |
| `langchain.chat_models.ChatOpenAI` | `langchain_community.chat_models.ChatTongyi` | 同门 |
| `signal.alarm(3)`（Unix） | `Thread.join(timeout=3)`（跨平台） | 教学点不丢失 |
| `full_chain.run(topic=...)` | `full_chain.invoke({"topic": ...})` | 修教材 API 误用 |
| `round(amount * rate, 2)` | `round(float(amount) * rate, 2)` | 修教材类型错配 |
| 教材 `custom_prompt` | `agent_kwargs={"prefix": ..., "suffix": ...}` | 修教材概念代码 |
| `memory_key="history"`（07） | `memory_key="chat_history"` | 修教材静默失败 |
| `openlibrary.org` 真实 API | 本地模拟书库（原版注释保留） | 修无兜底网络调用 |

**改写纪律**：本章是「**最小改动 + 修 bug**」的章节——**业务逻辑一字不动**（工具函数、prompt 模板文本、Agent 组装、测试任务），只做两件事：
① **import 换路径 + 模型换 `ChatTongyi`**；② **修复教材自带 bug（bug 现场也注释保留）**。

### 1.5 本章最该带走的三句话

1. **ReAct 与 Function Calling 是两代工具调用范式**——ReAct（02/03/04/07）用**文本协议**（"Thought:/Action:/Action Input:/Observation:"），模型输出的是**要解析的文本**，工具入参**永远是字符串**，函数内部必须自己 `float()` 转换；Function Calling（char02 系列）模型输出 **JSON**，框架自动解析类型。**02 篇的类型 bug 正是这个差异的活证据**。
2. **LangChain 的模型抽象兑现了「换模型不动 Agent 代码」**——7 篇统一 `ChatTongyi(qwen-plus) + DASHSCOPE_API_KEY`，从 `OpenAI` 换到百炼，**Agent 组装代码一行未改**。这是 char03-05「协议即标准」的框架层体现。
3. **「模型的拒绝」不能当安全防线**——04 篇的沙箱是**代码层**的硬约束（字符白名单 + 空 builtins），而不是指望模型「不去执行危险命令」。**安全必须在代码里保证，不能靠提示词祈祷**。

---

## 2. 学习路径（7 文件 / 678 行）

按「编排 → Agent → 记忆 → 安全 → 多工具 → 定制 → 综合」的顺序阅读：

| # | 文件 | 行数 | 核心机制 | 读完后你应能说出 |
|---|---|---|---|---|
| 01 | `01_langchain多段链式处理.py` | 79 | `SequentialChain` + 三段 `LLMChain` + `output_key` 接力 | 链的变量流向、`run()` vs `invoke()` 的差异 |
| 02 | `02_tools与agent集成调度.py` | 85 | `initialize_agent` + `AgentType.ZERO_SHOT_REACT_DESCRIPTION` | ReAct 四要素、工具入参为何永远是字符串 |
| 03 | `03_具备对话以及功能的agent.py` | 75 | `ConversationBufferMemory(memory_key="chat_history", input_key="input")` | 记忆如何让「那广州呢？」成为可能 |
| 04 | `04_tool执行环境与沙箱控制.py` | 104 | `safe_eval` **三道防线**（限时 + 白名单 + 空 `builtins`） | 为什么 `eval` 危险、三道防线各挡什么 |
| 05 | `05_多工具调用顺序管理.py` | 72 | **`@tool` 装饰器**（新式）+ 三工具协同 | 新旧工具定义方式的差异 |
| 06 | `06_自定义提示词驱动agent.py` | 134 | `agent_kwargs={"prefix": ..., "suffix": ...}` + `CONVERSATIONAL_REACT_DESCRIPTION` | ReAct 模板的四段组装与可定制区 |
| 07 | `07_工具链动态规划逻辑.py` | 129 | `Memory` + 多工具 **跨轮接力**（搜书 → 记住第一本 → 查详情） | `memory_key` 与模板变量名必须匹配 |

### 阅读路线建议

- **第一遍（编排对比 2 篇）**：01 → 02。**这是本章最重要的对照**——01 是**固定流水线**（SequentialChain，顺序写死），02 是**模型现场规划**（ReAct Agent，顺序由模型决定）。**「工作流 vs Agent」的选型论证从这两篇开始**。
- **第二遍（能力增量 2 篇）**：03 → 04。在 02 的骨架上各加一个组件：03 加**记忆**（省略主语成为可能），04 加**沙箱**（工具安全执行）。
- **第三遍（工具定义 + 定制 2 篇）**：05 → 06。05 展示**新式 `@tool` 装饰器**（与 02-04 的旧式 `Tool(name=, func=, description=)` 对照）；06 讲**提示词定制**（Agent 的「灵魂」）。
- **第四遍（综合 1 篇）**：07。**05 + 03 合体收官**——两个工具 + 记忆 + 跨轮接力。
- **关键呼应**：
  - **02/03/04/05/06/07 六篇共用一个骨架**：`llm + tools + memory + initialize_agent + run`。每篇只**增量学一个新概念**。
  - **03 与 07 的 `memory_key` 差异是本篇最大的坑**——03 用 `"chat_history"`（正确）、07 教材用 `"history"`（**静默失忆**）。
  - **04 的沙箱是 char02-07 `exec` 警示的落地实现**。

---

## 3. 三条工程主线（本章反复出现的设计决策）

### 主线一：一个骨架，六篇增量（最容易被忽略的教学设计）

| 篇 | llm | tools | memory | agent 类型 | **新增概念** |
|---|---|---|---|---|---|
| 02 | ChatTongyi(0.3) | `Tool` × 2 | ❌ | `ZERO_SHOT_REACT_DESCRIPTION` | **ReAct 循环 + 工具调度** |
| 03 | ChatTongyi(0.4) | `Tool` × 1 | `ConversationBufferMemory` | `zero-shot-react-description` | **记忆** |
| 04 | ChatTongyi(0) | `Tool` × 1（沙箱） | `ConversationBufferMemory()` | `zero-shot-react-description` | **沙箱安全** |
| 05 | ChatTongyi(0) | **`@tool` × 3** | `ConversationBufferMemory()` | `zero-shot-react-description` | **新式工具定义** |
| 06 | ChatTongyi(0.5) | `Tool` × 2 | `ConversationBufferMemory(memory_key="history")` | `CONVERSATIONAL_REACT_DESCRIPTION` | **prefix/suffix 定制** |
| 07 | ChatTongyi(0) | `Tool` × 2 | `ConversationBufferMemory(memory_key="chat_history")` | `CONVERSATIONAL_REACT_DESCRIPTION` | **跨轮工具链** |

**核心认识**：**框架的价值在于「骨架稳定 + 组件可插拔」**——六篇的 `initialize_agent(tools, llm, memory, agent, verbose)` 调用方式**完全一致**，只是参数不同。

### 主线二：两种工具定义方式并存（新旧对照）

| 维度 | 旧式 `Tool` 类 | 新式 `@tool` 装饰器 |
|---|---|---|
| 写法 | `Tool(name="X", func=f, description="...")` | `@tool` + 函数 + **docstring** |
| 说明书来源 | **显式 `description` 参数** | **函数 docstring** |
| 篇目 | 02/03/04/06/07 | **05** |
| 装饰结果 | `Tool` 对象 | `StructuredTool` 对象 |
| import | `langchain_core.tools.Tool` | `langchain_core.tools.tool` |
| LangChain 1.x 推荐 | ❌ 已废弃 | ✅ **推荐** |

**新式示例（05 篇）**：
```python
@tool
def search_web(query: str) -> str:
    """根据用户输入执行Web搜索，并返回摘要结果"""    # ← docstring 就是说明书
    ...
tools = [search_web, summarize_text, translate_to_zh]   # ← 装饰后已是 StructuredTool，可直接进列表
```

⚠️ **注意 05 篇的三个工具函数返回的都是硬编码字符串** —— 这是**哑工具（dummy tools）**，教学重点在「**模型如何规划调用顺序**」，而非工具本身。

### 主线三：ReAct 模板的四段组装（06 篇查源码实证）

`CONVERSATIONAL_REACT_DESCRIPTION` 的默认 prompt 由四段拼成：

```
[prefix]              ← 可定制：角色设定（教材想改的就是这里）
    ↓
[工具清单]             ← 框架自动注入（预格式化字符串，**不是 `{tools}` 变量**）
    ↓
[ReAct 格式指令]       ← 框架自动注入（"Thought:/Action:/Final Answer:"）
    ↓
[suffix]              ← 可定制：结尾流程（含 {history} / {input} / {agent_scratchpad}）
```

**教材的错误**：把 `custom_prompt` 当成**整个模板**替换，但：
1. `agent_kwargs={"prompt": ...}` 不被 `CONVERSATIONAL_REACT_DESCRIPTION` 支持——查源码可知 `from_llm_and_tools` **没有 `prompt` 参数**；
2. 教材模板缺 `{tools}`/`{tool_names}`（框架靠这两个占位符注入工具清单）；
3. 教材模板缺 `{agent_scratchpad}`（框架靠它回传 Thought/Action/Observation 中间轨迹）；
4. 教材模板缺 ReAct 格式指令（模型不知道输出格式 → `AgentOutputParser` 解析失败 → `OutputParserException`）。

**改写方案**：用官方支持的「**部分定制**」通道 `prefix` + `suffix`，工具清单与格式指令仍由框架自动组装（**这是 `ConvoOutputParser` 能解析的前提**）。

---

## 4. 学习检查清单（读完自测）

- [ ] 能画出 `SequentialChain` 三段链的**变量流向图**（01）。
- [ ] 能说出 `full_chain.run()` 为什么在 3 个输出键时必抛 `ValueError`（01）。
- [ ] 能背诵 ReAct 四要素（Thought/Action/Action Input/Observation）并说明谁产生、谁消费（02）。
- [ ] 能解释「为什么 ReAct 工具的入参永远是字符串」（02）并对照 Function Calling 的差异。
- [ ] 能说出 `memory_key` 与 `input_key` 各自的作用（03）。
- [ ] 能说出沙箱三道防线各挡什么（04）。
- [ ] 能解释「为什么『模型的拒绝』不能当安全防线」（04）。
- [ ] 能说出 `@tool` 装饰器与 `Tool(name=, func=, description=)` 的三个差异（05）。
- [ ] 能画出 ReAct 模板的四段组装图，并指出哪两段可定制（06）。
- [ ] 能解释 `agent_kwargs={"prompt": ...}` 为什么不起作用（06）。
- [ ] 能说出 `memory_key="history"` 不匹配为什么是**静默失败**（07）。
- [ ] 能说明「工作流（Chain）vs Agent」的选型原则（01 vs 02）。

---

# 下篇：契约与验收

## 5. 全局技术约束（C-xx）

### C-01 LangChain 1.x 导入路径（全章统一映射表）

| 对象 | 正确路径（1.x） | 教材旧路径（失效） |
|---|---|---|
| `PromptTemplate` | `langchain_core.prompts` | `langchain.prompts` |
| `LLMChain` / `SequentialChain` | `langchain_classic.chains` | `langchain.chains` |
| `initialize_agent` / `Tool` / `AgentType` | `langchain_classic.agents` | `langchain.agents` |
| `AgentType`（07 篇路径） | `langchain_classic.agents.agent_types` | `langchain.agents.agent_types` |
| `ConversationBufferMemory` | `langchain_classic.memory` | `langchain.memory` |
| `Tool`（core 版） | `langchain_core.tools` | — |
| `@tool` 装饰器 | `langchain_core.tools` | `langchain.tools` |
| `ChatTongyi` | `langchain_community.chat_models` | —（教材用 `langchain.llms.OpenAI`） |

**约束**：必须使用 1.x 路径。
**验收**：grep `from langchain\.` 应只出现在**注释块**。

### C-02 模型统一 `ChatTongyi(model="qwen-plus")`

**统一写法**：
```python
llm = ChatTongyi(
    model="qwen-plus",
    temperature=...,                              # 见下表
    dashscope_api_key=os.environ.get("DASHSCOPE_API_KEY"),
)
```
**温度契约（逐篇保留教材原值）**：

| 篇 | temperature | 理由 |
|---|---|---|
| 01 | 0.5 | 教材原值（`OpenAI(temperature=0.5)`） |
| 02 | 0.3 | 教材原值 |
| 03 | 0.4 | 教材原值 |
| 04 | **0** | 数学计算要**确定性** |
| 05 | **0** | 顺序规划要**确定性** |
| 06 | 0.5 | 教材原值（`ChatOpenAI(temperature=0.5)`） |
| 07 | **0** | 工具链规划要**确定性** |

**约束**：温度必须与教材原值一致（**语义不变**）；不得统一改成同一个值。

### C-03 API Key 来自环境变量（全篇统一）

```python
dashscope_api_key=os.environ.get("DASHSCOPE_API_KEY")
```
**已知风险**：无空值校验（见缺口 G-01）。

### C-04 业务逻辑一字不动（最小改动原则）

**约束**：以下内容**逐字保留**，不得重构：

| 保留项 | 涉及篇 |
|---|---|
| `PromptTemplate` 的模板文本与 `input_variables` | 01 |
| 三段链的组装方式与 `output_key` 命名 | 01 |
| 工具函数体（含 `requests` 调用、字典查表、硬编码返回） | 02/03/05/06/07 |
| `Tool` 包装的 `name` / `description` 文本 | 02/03/04/06/07 |
| `initialize_agent` 的 `agent=` / `verbose=True` / `memory=` | 02-07 |
| 测试任务字符串（`agent.run("...")` 的参数） | 02-07 |
| 沙箱的三道防线结构 | 04 |

**理由**：本章教学价值在「**框架结构 + 教材 bug**」，业务逻辑改动会掩盖这两点。

### C-05 六类教材 bug 必须修复 + bug 现场注释保留

**约束**：每一处 bug 修复都要在紧邻位置保留：
1. `# 原写法：...`（原代码）；
2. `# 注意：...`（bug 说明：现象 + 原因 + 为什么不是版本问题）；
3. `# 修复：...`（修复方式）。

**实例（02 篇）**：
```python
# 原写法：def convert_usd_to_cny(amount: float) -> str:  …  converted = round(amount * rate, 2)
# 注意：原代码这里还藏着一个 bug——ReAct 型智能体的工具输入是从文本协议
#       （"Action Input: 20.0"）解析出的【字符串】，直接乘浮点数会抛
#       TypeError: can't multiply sequence by non-int of type 'float'
#       原代码运行必然报错，不是版本迁移问题；这也是 ReAct 时代的经典坑：
#       工具输入永远是字符串，函数内部必须自己做类型转换
#       （对比 char02 系列：Function Calling 模型输出 JSON，框架已自动解析类型）
# 修复：加 float() 显式转换
def convert_usd_to_cny(amount) -> str:
    rate = 7.25
    converted = round(float(amount) * rate, 2)
```

### C-06 平台不兼容必须跨平台替换（04 篇）

**约束**：Unix 专属 API（`signal.SIGALRM` / `signal.alarm`）必须替换为 Windows 可用方案，**但教学点（限时）不能丢**。
**替换契约**：
```python
EVAL_TIMEOUT_SECONDS = 3  # 与原写法 signal.alarm(3) 的 3 秒限制一致

thread = threading.Thread(target=worker, daemon=True)
thread.start()
thread.join(timeout=EVAL_TIMEOUT_SECONDS)   # 等价于原 signal.alarm(3) 的限时
if thread.is_alive():
    return "执行超时"                        # 等价于原 except TimeoutException 分支
```
**原写法注释保留**（含 `TimeoutException` / `timeout_handler` / `signal.signal(...)` 三行）。
**说明**：教材默认 Linux/Mac；目标环境是 Windows 时**必须**替换。

### C-07 不可达外部依赖必须加兜底（07 篇）

**约束**：外部 API 调用必须 `try/except` + `timeout`；国内不可达的站点应改为**本地模拟数据**，原始 HTTP 版本以注释保留。
**实例（07 篇）**：
```python
# 原写法：openlibrary.org 真实 API。实测在国内网络环境连接超时（openlibrary.org 不可达），
#   且原函数没有 try/except 兜底——ConnectTimeout 异常从 tool.run 一路抛到顶层，
#   直接把 AgentExecutor 打崩（对照 06 篇：维基百科超时有兜底，模型能优雅降级）。
```
**改写**：本地 `LOCAL_BOOKS` 模拟书库，**返回格式与原版一致**（`"序号. 书名 by 作者"`）。
**为什么可接受**：与 05 篇的哑工具同理——**工具实现是假的，工具链动态规划才是本篇灵魂**。

### C-08 哑工具（dummy tools）必须显式标注

**约束**：返回硬编码字符串的工具，必须在注释中说明「这是哑工具」+「教学重心在别处」。
**实例（05 篇）**：`search_web` / `summarize_text` / `translate_to_zh` 均返回固定字符串（`"智能体是一种基于大模型的自主系统。"`）。
**实例（04 篇）**：`get_weather` 用字典查表（北京/上海/广州三个城市）。

### C-09 每个文件头注释必须包含三要素

**约束**：头部注释块必须包含：
1. **教材概念**（1-3 行）；
2. **改写前的两条/三条问题**（import 断裂 + 模型不可直连 + 平台/逻辑问题）；
3. **改写策略**（保留了什么、替换了什么）。

### C-10 「原写法（注释保留）」必须紧贴改写点

**约束**：每处改写都要在紧邻位置保留 `# 原写法：...`。

### C-11 实测发现写入注释（ReAct 轨迹 / 双保险拦截）

**约束**：能实测验证的结论必须在注释中留痕。
**实例**：
- 05 篇：**双路径实测**——（1 工具时模型抄近路）/（2 工具时理性跳过第 3 步）；
- 04 篇：**沙箱双保险拦截**——`3*(5+2)` 正常计算，`import os; os.system('rm -rf /')` 被白名单拦截。

### C-12 教材描述与实现不符必须指认

**约束**：教材中「描述与实现有落差」的地方必须在注释中明确指认。
**实例（06 篇）**：
> `agent_kwargs={"prompt": ...}` 不被 `CONVERSATIONAL_REACT_DESCRIPTION` 支持——查框架源码可知：该 Agent 的工具清单是"预格式化"拼进模板字符串的（不存在 `{tools}` 变量），`from_llm_and_tools` 根本没有 `prompt` 参数，传入只会被丢弃或报错。

---

## 6. 逐文件契约（F-01 ~ F-07）

---

### F-01 `01_langchain多段链式处理.py`（79 行）——链式编排篇

**意图**：回答「**怎么把复杂任务拆成有序步骤，且变量自动接力**」——`SequentialChain` 是**固定流水线**的最小实现。

**导入契约（1.x）**：
```python
from langchain_core.prompts import PromptTemplate
from langchain_classic.chains import LLMChain, SequentialChain
from langchain_community.chat_models import ChatTongyi
```

**模型契约**：`ChatTongyi(model="qwen-plus", temperature=0.5, dashscope_api_key=...)`（**温度 0.5 保留教材原值**）。

**三段子链契约（变量接力链）**：

| 链 | `input_variables` | 模板 | `output_key` |
|---|---|---|---|
| `chain1` | `["topic"]` | `"请列出与“{topic}”相关的三个细分研究方向，用逗号分隔。"` | `subtopics` |
| `chain2` | `["subtopics"]` | `"以下是子主题：{subtopics}，请为每个子主题提出一个具挑战性的研究问题。"` | `questions` |
| `chain3` | `["questions"]` | `"以下是若干研究问题：{questions}，请简要分析其对于推动社会发展的意义。"` | `impact` |

**变量接力契约（本篇核心）**：
```
topic ──chain1──> subtopics ──chain2──> questions ──chain3──> impact
       (output_key)          (input_variables 自动消费上一个 output_key)
```
**关键机制**：`SequentialChain` 靠 **`output_key` → 下一个链的 `input_variables`** 的**名字匹配**自动接力——**链之间不需要显式传递变量**。

**组装契约**：
```python
full_chain = SequentialChain(
    chains=[chain1, chain2, chain3],
    input_variables=["topic"],
    output_variables=["subtopics", "questions", "impact"],
    verbose=True
)
```

**🔴 教材 bug 契约（API 误用，必须标注）**：
```python
# 原写法：response = full_chain.run(topic="人工智能伦理")
# 注意：原代码这里还藏着一个 bug——.run() 只支持"恰好一个输出键"的链，
#       而 SequentialChain 声明了 3 个输出变量，即使在 0.x 旧版同样会抛出
#       ValueError: `run` not supported when there is not exactly one output key
# 改写：统一用 1.x 的标准入口 invoke，传入变量字典、返回包含全部输出变量的字典
result = full_chain.invoke({"topic": "人工智能伦理"})
```

**输出契约（分三段打印，链式拆解可见）**：
```
== 子主题 subtopics ==
== 研究问题 questions ==
== 社会价值 impact ==
```

**验收标准**：
- V-01-A：`verbose=True` 打印三段链的执行轨迹（每次 LLM 调用与中间输出）。
- V-01-B：打印 `== 子主题 subtopics ==` / `== 研究问题 questions ==` / `== 社会价值 impact ==` 三段。
- V-01-C：`result["subtopics"]` 含 3 个细分方向（逗号分隔）。
- V-01-D：`result["questions"]` 内容与 `subtopics` **语义连贯**（证明变量接力成功）。

**已知风险 / 诚实标注**：
- 🔴 **`.run()` 是教材的 API 误用 bug** —— 3 个输出键必抛 `ValueError`。**这不是版本迁移问题**，0.x 同样报错。**本篇最有价值的教训之一**（见缺口 G-02）。
- ⚠️ **`PromptTemplate` 用中文引号 `“{topic}”`** —— 模板里的中文引号是**字面文本**（不是变量），不会影响 `{topic}` 的替换，但视觉上易混淆。
- ⚠️ **`LLMChain` / `SequentialChain` 在 LangChain 2.0 将移除** —— 教材用的是**经典链 API**（`langchain_classic`），生产应迁移到 **LCEL**（`prompt | llm | parser`）（见附录 B）。
- ⚠️ **无错误处理** —— 任一子链失败则整个链中断。
- ⚠️ **`verbose=True` 输出冗长** —— 生产应关掉或改为日志级别控制。

**教材问题（文件头注释实录）**：
> 组织任务流程的骨架，将复杂任务拆解为有序步骤，实现多步骤任务的自动化执行。
> 原写法：langchain 0.x 的 import 路径 + OpenAI 模型类，在当前环境无法运行，原因有二：1) LangChain 1.x 中这三个模块路径已拆分：prompts 移入 `langchain_core.prompts`，经典链（LLMChain/SequentialChain）收纳进 `langchain_classic.chains`，`langchain.llms.OpenAI` 类已移除；2) OpenAI 类需要 `OPENAI_API_KEY` 且国内无法直连 OpenAI 官方服务。
> 改写（参照 char01-02_提示词驱动的Agent.py 的方式）：三段子链 + SequentialChain 的链式结构**一字不动**——这是本篇的教学核心。

---

### F-02 `02_tools与agent集成调度.py`（85 行）——ReAct 集成篇

**意图**：回答「**怎么让模型自主决策调工具**」——`initialize_agent` + `ZERO_SHOT_REACT_DESCRIPTION` 是 **ReAct 循环**的最小实现。

**导入契约（1.x）**：
```python
import requests
from langchain_classic.agents import AgentType, initialize_agent
from langchain_core.tools import Tool
from langchain_community.chat_models import ChatTongyi
```

**模型契约**：`ChatTongyi(model="qwen-plus", temperature=0.3, ...)`。

**工具契约（2 个）**：

| 工具名 | 函数 | 实现 | description |
|---|---|---|---|
| `WebSummaryTool` | `fetch_summary(url)` | `requests.get(url, timeout=10)` → `resp.text[:1000]` → 返回前 300 字 + `"..."`；失败返回 `"无法访问网页内容"` 或 `str(e)` | `"根据提供的网址提取网页摘要，适用于阅读网页内容"` |
| `USDToCNYConverter` | `convert_usd_to_cny(amount)` | `rate = 7.25`；`round(float(amount) * rate, 2)` | `"将美元金额转换成人民币金额，适用于财务相关查询"` |

**🔴 教材 bug 契约（类型错配，必须标注）**：
```python
# 原写法：def convert_usd_to_cny(amount: float) -> str:  …  converted = round(amount * rate, 2)
# 注意：原代码这里还藏着一个 bug——ReAct 型智能体的工具输入是从文本协议
#       （"Action Input: 20.0"）解析出的【字符串】，直接乘浮点数会抛
#       TypeError: can't multiply sequence by non-int of type 'float'
#       原代码运行必然报错，不是版本迁移问题；这也是 ReAct 时代的经典坑：
#       工具输入永远是字符串，函数内部必须自己做类型转换
#       （对比 char02 系列：Function Calling 模型输出 JSON，框架已自动解析类型）
# 修复：加 float() 显式转换
def convert_usd_to_cny(amount) -> str:
    rate = 7.25
    converted = round(float(amount) * rate, 2)
    return f"{amount}美元 ≈ {converted}人民币（按汇率7.25）"
```

**Agent 组装契约**：
```python
agent = initialize_agent(
    tools,
    llm,
    agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
    verbose=True
)
response = agent.run("请帮我把20美元换算成人民币")
```

**ReAct 四要素契约（教学核心）**：

| 要素 | 谁产生 | 谁消费 |
|---|---|---|
| `Thought:` | **模型** | 模型自己（链式思考） |
| `Action:` | **模型**（工具名） | 框架（查工具表） |
| `Action Input:` | **模型**（**字符串**） | 工具函数（**必须自己转类型**） |
| `Observation:` | **工具函数**（返回值） | 框架（拼回 prompt） |

**验收标准**：
- V-02-A：`verbose=True` 打印完整 ReAct 轨迹（`Thought` / `Action: USDToCNYConverter` / `Action Input: 20` / `Observation: ...` / `Final Answer`）。
- V-02-B：`==== 输出结果 ====` 后输出换算结果（含 `20美元 ≈ 145.0人民币（按汇率7.25）` 之类）。
- V-02-C：**`float()` 转换生效**——无 `TypeError`。
- V-02-D：模型**只调用 `USDToCNYConverter`**（不调 `WebSummaryTool`）。

**已知风险 / 诚实标注**：
- 🔴 **类型错配 bug** —— 教材原代码必抛 `TypeError`。**这是「ReAct 工具入参永远是字符串」的活教材**（见缺口 G-03）。
- ⚠️ **`fetch_summary` 的截取逻辑可疑** —— `resp.text[:1000]` 再 `[:300]`（**先截 1000 再截 300 = 实际 300**），第一步 `[:1000]` 是**冗余的**（除非原意是先解析再截，但没解析 HTML）。
- ⚠️ **`fetch_summary` 把整个网页 HTML 当摘要** —— 未做正文提取（对比 char06 的 `clean_text`），返回的是 HTML 标签混杂的文本（**可能剧透 prompt**）。
- ⚠️ **`rate = 7.25` 硬编码** —— 汇率是实时变化的（虚构值）。
- ⚠️ **`Tool` 类是旧式 API** —— 1.x 推荐 `@tool` 装饰器（见 05 篇）。
- ⚠️ **`ZERO_SHOT_REACT_DESCRIPTION` 无记忆** —— 单轮任务（03 篇才加 memory）。

**教材问题（文件头注释实录）**：
> 赋予模型行动能力，连接外部工具与知识库，让AI能够自主决策并与外部世界交互。
> 【改写说明】两个工具函数、Tool 包装、`initialize_agent` 的 `ZERO_SHOT_REACT_DESCRIPTION` 结构**一字不动**（ReAct 智能体"思考->行动->观察"的循环是本篇教学核心）。

---

### F-03 `03_具备对话以及功能的agent.py`（75 行）——记忆篇

**意图**：回答「**怎么让 Agent 记得住上一轮**」——`ConversationBufferMemory` 让「那广州呢？」成为可能。

**导入契约（1.x）**：
```python
from langchain_classic.agents import initialize_agent
from langchain_classic.memory import ConversationBufferMemory
from langchain_core.tools import Tool
from langchain_community.chat_models import ChatTongyi
```

**模型契约**：`ChatTongyi(model="qwen-plus", temperature=0.4, ...)`。

**工具契约（1 个，哑工具）**：
```python
def get_weather(city: str) -> str:
    dummy_weather = {"北京": "晴，25°C", "上海": "多云，23°C", "广州": "雷阵雨，29°C"}
    return dummy_weather.get(city, "当前城市暂无天气数据")

weather_tool = Tool(name="WeatherTool", func=get_weather, description="查询城市天气，如输入：北京")
```
⚠️ **哑工具** —— 字典查表，无真实天气 API（C-08 约束：已在注释中标注）。

**记忆契约（本篇核心）**：
```python
memory = ConversationBufferMemory(
    memory_key="chat_history",     # ← 记忆在 prompt 里的变量名
    input_key="input"              # ← 用户输入的变量名
)
agent = initialize_agent(
    tools=[weather_tool], llm=llm, memory=memory,
    agent="zero-shot-react-description", verbose=True
)
```

**`memory_key` 与 `input_key` 语义契约**：

| 参数 | 作用 | 为什么重要 |
|---|---|---|
| `memory_key="chat_history"` | 记忆内容注入 prompt 时用的**变量名** | **必须与模板里的变量名匹配**——不匹配则**静默失忆**（07 篇的 bug 正是这个） |
| `input_key="input"` | 从输入字典里取哪个键作为「本轮输入」 | Agent 的 `run()` 内部会包装成 `{"input": ...}` |

**三轮对话契约（教材核心演示）**：

| 轮 | 用户输入 | 记忆的作用 |
|---|---|---|
| 1 | `"我想知道北京天气如何？"` | 无记忆（首次） |
| 2 | `"那广州呢？"` | **「那...呢」的省略主语靠记忆补全**（知道上一轮在问天气） |
| 3 | `"那明天去哪旅游好？"` | 靠记忆知道在讨论**北京/广州的天气** → 推荐城市 |

**验收标准**：
- V-03-A：三轮 `agent.run()` 均成功返回，`verbose=True` 打印三轮 ReAct 轨迹。
- V-03-B：第 2 轮 `verbose` 输出的 prompt 里**含第 1 轮的问答**（记忆注入的证据）。
- V-03-C：第 2 轮的回答指向**广州天气**（不是「我不知道你在问什么」）。
- V-03-D：第 3 轮回答**结合天气信息**给出旅游建议（如「广州有雷阵雨，建议去北京」）。

**已知风险 / 诚实标注**：
- ⚠️ **`ConversationBufferMemory` 无上限** —— 对话越长，prompt 越大，**最终超出模型上下文**（生产应用 `ConversationSummaryBufferMemory` 或滑动窗口）（见缺口 G-04）。
- ⚠️ **进程内记忆** —— 进程重启即丢失（生产需持久化 + `session_id` 隔离）（见缺口 G-05）。
- ⚠️ **无会话隔离** —— 多个用户共用一个 `memory` 实例会串台（生产需按 `session_id` 分桶，对比 char09-06 的 `ContextScope`）。
- ⚠️ **`get_weather` 是哑工具** —— 三个城市硬编码，其他城市返回「暂无数据」。
- ⚠️ **`memory_key` 用的是 `"chat_history"`（正确）** —— 与 07 篇教材的 `"history"` 形成对照。
- ⚠️ **无错误处理** —— `agent.run()` 失败会中断脚本。
- ⚠️ **03 篇无隐藏 bug** —— 改写后即可运行（本章仅 03/05 两篇如此）。

**教材问题（文件头注释实录）**：
> 赋予模型长期记忆，保留对话历史与上下文信息，实现具备连贯性的智能对话体验。
> 【改写说明】天气模拟函数、Tool 包装、ConversationBufferMemory 配置、三轮对话测试**一字不动**（"记忆让省略主语的追问成为可能"是本篇教学核心）。

---

### F-04 `04_tool执行环境与沙箱控制.py`（104 行）——沙箱安全篇

**意图**：回答「**怎么让 `eval` 安全**」——沙箱三道防线：**限时 + 字符白名单 + 空 `builtins`**。

**导入契约（1.x）**：
```python
import os
import threading                                # ← 替换 Unix 的 signal
from langchain_classic.agents import initialize_agent
from langchain_classic.memory import ConversationBufferMemory
from langchain_core.tools import Tool
from langchain_community.chat_models import ChatTongyi
```

**模型契约**：`ChatTongyi(model="qwen-plus", temperature=0, ...)` —— **温度 0（数学计算要确定性）**。

**🔴 平台不兼容契约（必须替换）**：
```python
# 原写法（Unix/Linux 专属，Windows 上 signal.SIGALRM 属性不存在直接报错）：
# class TimeoutException(Exception):
#     pass
# def timeout_handler(signum, frame):
#     raise TimeoutException("执行超时")
# signal.signal(signal.SIGALRM, timeout_handler)

# 改写：Windows 可用的限时方案——在后台线程里执行、主线程最多等 3 秒，
#       效果与原 signal.alarm(3) 一致（限时教学点不丢失），且跨平台
EVAL_TIMEOUT_SECONDS = 3  # 与原写法 signal.alarm(3) 的 3 秒限制一致
```

**三道防线契约（本篇核心教学资产）**：

| 防线 | 实现 | 挡什么 |
|---|---|---|
| **① 字符白名单** | `allowed_chars = "0123456789+-*/(). "` + `all(c in allowed_chars for c in expression)` | **最硬的一道**——连 `import` / `os` / `;` / 字母都进不来 |
| **② 空 builtins** | `eval(expression, {"__builtins__": {}})` | 即使表达式混入名字，也找不到内置函数（`__import__` 等） |
| **③ 限时** | `thread.join(timeout=3)` + `thread.is_alive()` 判断 | 挡死循环 / 超长计算（如 `9**9**9`） |

**`safe_eval` 契约**：
```python
def safe_eval(expression: str) -> str:
    outcome = {}
    def worker():
        try:
            allowed_chars = "0123456789+-*/(). "
            if not all(c in allowed_chars for c in expression):
                outcome["reply"] = "非法表达式，包含禁止字符"
                return
            result = eval(expression, {"__builtins__": {}})
            outcome["reply"] = f"结果为：{result}"
        except Exception as e:
            outcome["reply"] = f"执行失败：{str(e)}"

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout=EVAL_TIMEOUT_SECONDS)
    if thread.is_alive():
        return "执行超时"
    return outcome.get("reply", "执行失败：未知错误")
```

**工具契约**：
```python
safe_calc_tool = Tool(name="SafeCalculator", func=safe_eval,
                      description="用于安全计算加减乘除表达式，如：3*(5+2)")
```

**双路径验证契约（教材设计）**：

| 轮 | 输入 | 期望结果 |
|---|---|---|
| 1 | `"计算表达式 3*(5+2)"` | **正常计算** → `结果为：21` |
| 2 | `"执行表达式 import os; os.system('rm -rf /')"` | **被拦截** → `非法表达式，包含禁止字符` |

**验收标准**：
- V-04-A：第 1 轮输出含 `结果为：21`。
- V-04-B：第 2 轮输出含 `非法表达式，包含禁止字符`（**白名单拦截**）。
- V-04-C：**两轮均无 Python 异常抛出**（沙箱把异常都转成了字符串回复）。
- V-04-D：`verbose=True` 显示模型确实尝试调用了 `SafeCalculator` 工具。

**已知风险 / 诚实标注（本篇最有价值的安全教训）**：
- 🔴 **「模型的拒绝」不能当安全防线** —— 教材设计第 2 轮是**故意让模型去执行危险命令**，但安全性**完全依赖 `safe_eval` 的代码约束**，而非模型「会不会拒绝」。**如果模型真去执行了，也是被 `safe_eval` 挡住的**（见风险说明）。
- ⚠️ **白名单里的 `.` 和 ` ` 有隐患** —— `.` 在纯算术表达式里其实用不上（除非允许 `1.5` 小数），而 `.` 是**属性访问符**（`().__class__` 之类）——**虽然白名单阻止了字母，但 `.` 本身留在白名单里是宽松的**（当前因无字母/下划线仍安全，但不够严谨）。
- ⚠️ **`eval` 依然存在（白名单过滤后）** —— 更安全的做法是 **AST 白名单解析**（`ast.parse` + 只允许 `BinOp`/`Num` 节点），**完全不用 `eval`**（见缺口 G-06）。
- ⚠️ **线程限时无法真正终止线程** —— `thread.join(timeout=3)` 超时后**线程仍在后台运行**（`daemon=True` 只能保证主进程退出时被杀）。真正的限时应使用 `multiprocessing` + `terminate()`（见缺口 G-07）。
- ⚠️ **`outcome` 是跨线程共享的 dict** —— 严格说需要加锁，但 CPython 下单键赋值原子，**实践上安全**。
- ⚠️ **沙箱仅在进程内** —— 无 OS 级隔离（生产需 `subprocess` / Docker / seccomp）。
- ⚠️ **`memory = ConversationBufferMemory()` 无参数** —— 此处不指定 `memory_key`（用默认）。

**教材问题（文件头注释实录）**：
> 一种关键的安全机制，通过创建独立的隔离执行环境，严格限制外部工具的运行权限和资源使用范围，从根本上防止恶意操作或程序故障对主系统造成破坏或数据泄露。
> 【本篇独立的平台问题】`signal.SIGALRM` / `signal.alarm` 是 Unix/Linux 专属 API，在 Windows 上根本不存在（`signal.signal(signal.SIGALRM, ...)` 直接抛 `AttributeError`）——教材默认 Linux/Mac 环境，目标环境是 Windows 时必须替换限时方案。
> 【改写说明】沙箱三层防线（限时 + 字符白名单 + 空 builtins）的教学核心**全部保留**，仅把 Unix 专属的 `signal` 限时替换为 Windows 可用的线程限时。

---

### F-05 `05_多工具调用顺序管理.py`（72 行）——新式工具 + 多工具协同篇

**意图**：回答「**多个工具怎么协同**」——模型自主规划 `搜索 → 摘要 → 翻译` 的调用顺序。

**导入契约（1.x）**：
```python
from langchain_classic.agents import initialize_agent
from langchain_classic.memory import ConversationBufferMemory
from langchain_core.tools import tool           # ← 新式装饰器
from langchain_community.chat_models import ChatTongyi
```
**原代码注释**：`# from typing import List        # 原代码导入了但从未使用，改写后一并省略` —— **教材的无用 import**。

**模型契约**：`ChatTongyi(model="qwen-plus", temperature=0, ...)` —— **温度 0（顺序规划要确定性）**。

**三个工具契约（新式 `@tool`，docstring 即说明书）**：

| 工具 | docstring（= description） | 返回 |
|---|---|---|
| `search_web` | `"""根据用户输入执行Web搜索，并返回摘要结果"""` | 含 `"AI Agent"` 时返回定义句；否则 `f"未找到关于：{query} 的相关信息"` |
| `summarize_text` | `"""对给定文本执行摘要处理"""` | `"智能体是一种基于大模型的自主系统。"`（**硬编码**） |
| `translate_to_zh` | `"""将英文摘要翻译成中文"""` | `"智能体是一种基于大模型的自主系统。"`（**硬编码**） |

**工具集成契约**：
```python
# @tool 装饰后函数已变为 StructuredTool 对象，可直接进列表
tools = [search_web, summarize_text, translate_to_zh]
```

**新旧工具定义契约对照**（本章主线二）：

| 维度 | 旧式（02/03/04/06/07） | 新式（05） |
|---|---|---|
| 定义 | `Tool(name="X", func=f, description="...")` | `@tool` + 函数 + docstring |
| 说明书 | 显式 `description` | **docstring** |
| 对象类型 | `Tool` | `StructuredTool` |
| 进列表 | `[tool_obj]` | `[func]`（装饰后已是对象） |

**任务契约**：
```python
output = agent.run("用中文总结AI Agent的基本定义")
```

**双路径实测契约（本篇最有价值的观察）**：

| 路径 | 现象 |
|---|---|
| **抄近路（1 工具）** | 模型发现 `search_web` 已返回中文定义，**跳过 `summarize_text` 和 `translate_to_zh`**，直接输出 |
| **理性跳过（2 工具）** | 若模型先调 `search_web` 再调 `summarize_text`，会**发现摘要已是中文**，跳过 `translate_to_zh` |

**验收标准**：
- V-05-A：`verbose=True` 打印 ReAct 轨迹，**含 `Action: search_web`**。
- V-05-B：`用户输入：用中文总结AI Agent的基本定义` + `模型输出：...`。
- V-05-C：最终回答**含「AI Agent 是一种基于大语言模型的自主任务执行单元...」**（来自 `search_web`）。
- V-05-D：**三个工具不必全被调用**（模型自主决定调用几个）——这是「动态规划」的直接证据。

**已知风险 / 诚实标注**：
- ⚠️ **三个工具都是哑工具** —— 返回硬编码字符串，无真实搜索/摘要/翻译（**教学重心是「模型如何规划顺序」**，见 C-08）。
- ⚠️ **`search_web` 用 `"AI Agent" in query` 精确子串匹配** —— 若模型把 query 改写成「AI智能体」则命中失败（**关键字匹配的脆弱性**）。
- ⚠️ **`translate_to_zh` 名不副实** —— 输入是「英文摘要」，但 `summarize_text` 返回的是**中文**，所以翻译工具的输入实际已是中文（**教材的逻辑瑕疵**，也正因此模型会「理性跳过」）。
- ⚠️ **无工具调用次数上限** —— ReAct 可能陷入循环（`max_iterations` 默认值未显式设置）（见缺口 G-08）。
- ⚠️ **05 篇无隐藏 bug** —— 改写后即可运行（与 03 篇并列）。

**教材问题（文件头注释实录）**：
> 许多复杂任务需要多个工具按特定顺序协同工作。显式地管理调用顺序，可以消除执行歧义，显著提高系统的稳定性和结果的可控性。
> 【改写说明】`@tool` 装饰器从 `langchain_core.tools` 导入（新式工具定义，与 `Tool(name=..., func=...)` 旧式包装并存）；三个工具函数、docstring（即工具说明书）、工具列表、Agent 组装、测试任务**一字不动**（"模型自主规划 搜索->摘要->翻译 的调用顺序"是本篇教学核心）。

---

### F-06 `06_自定义提示词驱动agent.py`（134 行）——提示词定制篇（最深 bug）

**意图**：回答「**怎么定制 Agent 的『灵魂』**」——提示词即指令集，改 prompt 就是改人格。

**导入契约（1.x）**：
```python
import os
import requests
from langchain_classic.agents import initialize_agent, Tool, AgentType
from langchain_classic.memory import ConversationBufferMemory
from langchain_core.prompts import PromptTemplate
from langchain_community.chat_models import ChatTongyi
```

**模型契约**：`ChatTongyi(model="qwen-plus", temperature=0.5, ...)`。

**工具契约（2 个，真实 HTTP）**：

| 工具名 | 函数 | 实现 |
|---|---|---|
| `GetWeather` | `get_weather(city)` | `https://wttr.in/{city}?format=3` → `response.text.strip()`；失败 `f"查询失败：{str(e)}"`（⚠️ **无 `timeout`**） |
| `GetCityIntro` | `get_city_intro(city)` | `https://en.wikipedia.org/api/rest_v1/page/summary/{city}` → `.json().get("extract", "未找到该城市简介")`；失败 `f"查询失败：{str(e)}"`（⚠️ **无 `timeout`**） |

**🔴 教材 bug 契约（概念代码，必须标注）**：

**教材原 `custom_prompt`（注释保留）**：
```python
# custom_prompt = PromptTemplate(
#     input_variables=["input", "history"],
#     template="""
# 你是一位知识渊博的智能助理，可以调用两种工具：GetWeather用于查询天气，GetCityIntro用于提供城市简介。
# 用户的问题如下：{input}
# 历史对话记录如下：{history}
# 请根据问题内容选择合适的工具进行调用，并用自然语言回答。
# """
# )
```

**教材的三重错误（查框架源码实证）**：
1. **`agent_kwargs={"prompt": ...}` 不被 `CONVERSATIONAL_REACT_DESCRIPTION` 支持** —— 查框架源码可知：该 Agent 的工具清单是「**预格式化**」拼进模板字符串的（**不存在 `{tools}` 变量**），`from_llm_and_tools` **根本没有 `prompt` 参数**，传入只会被丢弃或报错；
2. **教材模板缺 `{tools}` / `{tool_names}`** —— 框架靠这两个占位符注入工具清单；
3. **教材模板缺 `{agent_scratchpad}`** —— 框架靠它回传 Thought/Action/Observation 中间轨迹；
4. **教材模板缺 ReAct 格式指令** —— 模型不知道 `Thought:/Action:/Final Answer:` 输出格式 → `AgentOutputParser` 解析失败 → `OutputParserException`。

**结论（06 篇注释原文）**：
> 教材展示的是"自定义提示词"的"概念示意"，而非可运行代码。

**改写契约（官方「部分定制」通道）**：
```python
custom_prefix = """你是一位知识渊博的智能助理，可以调用两种工具：GetWeather用于查询天气，GetCityIntro用于提供城市简介。
请根据问题内容选择合适的工具进行调用，并用自然语言回答。"""

custom_suffix = """开始！

历史对话记录如下：
{history}

用户的问题如下：{input}
{agent_scratchpad}"""

memory = ConversationBufferMemory(memory_key="history")     # ← 与 suffix 的 {history} 对齐

agent = initialize_agent(
    tools=tools, llm=llm,
    agent=AgentType.CONVERSATIONAL_REACT_DESCRIPTION,
    memory=memory, verbose=True,
    agent_kwargs={"prefix": custom_prefix, "suffix": custom_suffix}
)
```

**改写策略契约（三点）**：
- `prefix` = 教材 persona 原文（**教学核心完整保留**）；
- `suffix` 用中文重写结尾流程，`{history}` 与教材 `memory_key="history"` 对齐，`{agent_scratchpad}` 保留；
- `format_instructions` **不定制**（保留框架默认英文版）——最终回答格式 `"AI: ..."` 是**解析器协议**。

**三轮对话契约**：
```python
print(agent.run("介绍一下上海"))
print(agent.run("那现在上海的天气如何？"))
print(agent.run("北京天气怎么样？"))
```

**验收标准**：
- V-06-A：`====== 实际对话示例 ======` 后输出三轮回答。
- V-06-B：第 1 轮触发 `GetCityIntro`（城市百科）。
- V-06-C：第 2 轮触发 `GetWeather`（**「那...呢」靠记忆补全**）。
- V-06-D：第 3 轮切换城市（北京）成功，**无 `OutputParserException`**（证明 prefix/suffix 注入生效）。
- V-06-E：`verbose` 输出的 prompt **含中文 persona**（`"你是一位知识渊博的智能助理"`）。

**已知风险 / 诚实标注**：
- 🔴 **教材 bug 是本章「最深」的一个** —— `custom_prompt` 是**概念代码**，在 0.x 环境同样跑不通（作者查源码实证）。**这比 import 断裂更难发现**（因为报错信息指向解析失败，而非配置错误）（见缺口 G-09）。
- ⚠️ **`memory_key="history"` 本篇正确** —— 因为 `custom_suffix` 里用的就是 `{history}`（**自定义 suffix 时可以自由命名，只要前后一致**）。这与 07 篇的**默认模板**场景不同（默认模板固定用 `{chat_history}`）。
- ⚠️ **两个工具函数无 `timeout`** —— `wttr.in` 与维基百科在国内可能超时（对比 07 篇的教训）（见缺口 G-10）。
- ⚠️ **`get_weather` 返回原始文本** —— `wttr.in?format=3` 返回单行简洁格式（如 `Beijing: ⛅️ +25°C`），但含 emoji（可能影响模型解析）。
- ⚠️ **`get_city_intro` 用英文维基百科** —— 中文城市名（「上海」）能命中（维基有重定向），但**结果可能是英文**（教学上无妨）。
- ⚠️ **无 `max_iterations`** —— ReAct 可能循环（同 05 篇）。

**教材问题（文件头注释实录）**：
> 提示词即"指令集"——在 LangChain 框架中，Agent 的行为逻辑完全依赖大模型的推理能力，而提示词就是引导推理方向的"核心指令集"，是实现 Agent 能力定制化的最关键手段。
> 【本篇还有一个比 import 更深的问题——教材的自定义模板跑不通（原版 0.x 环境同样报错）】教材的 `custom_prompt` 只是一个普通对话模板，缺少 `CONVERSATIONAL_REACT_DESCRIPTION` 驱动所必需的三样东西：① `{tools}` 与 `{tool_names}` 变量；② `{agent_scratchpad}` 变量；③ ReAct 格式指令。
> **结论：教材展示的是"自定义提示词"的"概念示意"，而非可运行代码。**

---

### F-07 `07_工具链动态规划逻辑.py`（129 行）——跨轮工具链篇（综合收官）

**意图**：回答「**跨轮工具链怎么接力**」——搜书 → **记住第一本** → 查详情（第二轮「第一本书」完全靠记忆）。

**导入契约（1.x）**：
```python
import os
import requests
from langchain_classic.agents import initialize_agent, Tool
from langchain_classic.agents.agent_types import AgentType
from langchain_classic.memory import ConversationBufferMemory
from langchain_community.chat_models import ChatTongyi
```

**模型契约**：`ChatTongyi(model="qwen-plus", temperature=0, ...)`。

**🔴 教材 bug 契约（静默失败，必须标注）**：
```python
# 原代码 memory_key="history"，而 CONVERSATIONAL_REACT_DESCRIPTION 默认模板里的
# 历史变量名是 {chat_history}（06 篇已查源码实证）——变量名不匹配会导致记忆静默丢失，
# 第二轮"请介绍第一本书的详细信息"时模型根本不知道"第一本书"是谁，
# 工具链的跨轮接力（搜书 -> 记住第一本 -> 查详情）就断了。改写修正为 "chat_history"。
memory = ConversationBufferMemory(memory_key="chat_history")
```
⚠️ **这是「最隐蔽」的死法** —— **不报错、不警告，只是「失忆」**。表现为第二轮回答「我不知道你指哪本书」，让人误以为模型能力不足。

**🔴 教材 bug 契约（无兜底网络调用，必须标注）**：
```python
# 原写法：openlibrary.org 真实 API。实测在国内网络环境连接超时（openlibrary.org 不可达），
#   且原函数没有 try/except 兜底——ConnectTimeout 异常从 tool.run 一路抛到顶层，
#   直接把 AgentExecutor 打崩（对照 06 篇：维基百科超时有兜底，模型能优雅降级）。
#   真实 API 版本原样注释保留，网络可达的环境可直接切回（建议补上 timeout=5）：
# def search_books(keyword: str) -> str:
#     """调用公开API搜索图书标题"""
#     url = f"https://openlibrary.org/search.json?q={keyword}"
#     res = requests.get(url, timeout=5)
#     docs = res.json().get("docs", [])[:3]
#     return "\n".join([f"{i+1}. {doc.get('title')} by {doc.get('author_name', ['N/A'])[0]}" for i, doc in enumerate(docs)])
```

**改写契约（本地模拟书库）**：
```python
LOCAL_BOOKS = [
    {"title": "人工智能：一种现代方法", "author": "Stuart Russell", "year": 2020},
    {"title": "深度学习", "author": "Ian Goodfellow", "year": 2017},
    {"title": "生命3.0", "author": "Max Tegmark", "year": 2018},
]
```
**返回格式与原版一致**：`f"{i+1}. {b['title']} by {b['author']}"`。

**输入清洗契约（模拟版特有，真实 API 不需要）**：
```python
def get_book_details(title: str) -> str:
    # 清洗模型传入的书名（实测模型会带书名号《》或拼上" by 作者"后缀——
    # 真实 API 用 HTTP 参数化查询天然健壮，模拟版需要自己做解析清洗）
    t = title.strip().strip("《》").strip()
    if " by " in t:
        t = t.split(" by ")[0].strip()
    ...
```
⚠️ **这是一个深刻的教学点** —— **真实 API 靠「参数化查询」天然健壮；模拟版必须自己做字符串清洗**。模型实测会传 `《人工智能：一种现代方法》 by Stuart Russell`。

**两个工具契约**：

| 工具名 | 函数 | description |
|---|---|---|
| `SearchBooks` | `search_books(keyword)` | `"根据关键词搜索图书，适合用于确定书名"` |
| `GetBookDetails` | `get_book_details(title)` | `"根据书名获取图书详细信息"` |

**两轮跨轮接力契约（本篇灵魂）**：
```python
response_1 = agent.run("我想查几本关于人工智能的书")
response_2 = agent.run("请介绍第一本书的详细信息")
```
**关键**：
- 第二轮输入里**没有「第一本书」的具体书名**；
- 书名完全来自**第一轮存进 `memory` 的搜索结果**；
- **`memory_key` 配错 = 静默断忆 = 教学目标落空**。

**验收标准**：
- V-07-A：第 1 轮 `verbose` 显示 `Action: SearchBooks` + `Observation: 1. 人工智能：一种现代方法 by Stuart Russell ...`。
- V-07-B：**实测会出现「加戏」** —— 模型第 1 轮自主继续调 `GetBookDetails`（**动态规划**）。
- V-07-C：第 2 轮 `Action: GetBookDetails`，`Action Input` 是**书名**（从记忆解析）。
- V-07-D：第 2 轮输出含书名/作者/出版时间（如 `人工智能：一种现代方法` / `Stuart Russell` / `2020`）。
- V-07-E：**两轮均无异常**（`openlibrary` 已被本地模拟替代）。

**已知风险 / 诚实标注**：
- 🔴 **`memory_key` 静默失败 bug** —— **最隐蔽的死法**，无报错只有「失忆」（见缺口 G-11）。
- 🔴 **无兜底网络调用打崩 AgentExecutor** —— `ConnectTimeout` 从 `tool.run` 一路抛到顶层（见缺口 G-12）。
- ⚠️ **`search_books` 的关键词匹配有 bug 倾向** —— `hits = [b for b in LOCAL_BOOKS if any(k in b["title"] for k in [...])]` 用**固定关键词列表**（不是 `keyword` 参数！），`keyword` 只在「未命中时退化为全量返回」的判断里用到（`if keyword not in ("", None) and not hits`）。
- ⚠️ **`LOCAL_BOOKS` 只有 3 本且全是 AI 相关** —— 搜其他主题会「全量返回」（教学上保证链路不中断）。
- ⚠️ **输入清洗是模拟版的补丁** —— 真实 API 不需要，但暴露了「**ReAct 工具入参是脏字符串**」的真相（同 02 篇的类型问题）。
- ⚠️ **`response_1` / `response_2` 无前缀打印** —— 输出两段文本难以区分（可读性问题）。
- ⚠️ **无 `max_iterations`** —— 同 05/06 篇。

**教材问题（文件头注释实录）**：
> 动态规划逻辑是智能体的核心能力之一。它让智能体不再被动执行单一指令，而是能够理解任务的上下文和目标，动态判断调用的工具类型与顺序，从而将复杂的任务自动拆解为可执行的步骤序列，完成端到端的自主规划与执行。
> 【本篇还有一个隐蔽的逻辑 bug（即使 import 与模型修好也会"跑得通但教学目标落空"）】原代码 `memory_key="history"`，而 `CONVERSATIONAL_REACT_DESCRIPTION` 默认模板里的历史变量名是 `{chat_history}`（06 篇已查源码实证）——变量名不匹配会导致记忆静默丢失。

---

## 7. 全章验收清单（V-01 ~ V-15）

### 7.1 运行层验收

| 编号 | 验收项 | 期望 |
|---|---|---|
| V-01 | `python 01_...py` | 三段链全通，`== 子主题/研究问题/社会价值 ==` 三段输出 |
| V-02 | `python 02_...py` | ReAct 轨迹完整，换算结果正常（**无 `TypeError`**） |
| V-03 | `python 03_...py` | 三轮递进，第 2 轮「那广州呢」正确理解 |
| V-04 | `python 04_...py` | 第 1 轮 `结果为：21`；第 2 轮 `非法表达式，包含禁止字符` |
| V-05 | `python 05_...py` | ReAct 轨迹含 `Action: search_web`，模型自主决定调用几个工具 |
| V-06 | `python 06_...py` | 三轮全通（上海百科 / 上海天气 / 北京天气），无解析异常 |
| V-07 | `python 07_...py` | 两轮跨轮接力成功，第 2 轮拿到「第一本书」详情 |

### 7.2 契约层验收

| 编号 | 契约 | 对应 | 验证方式 |
|---|---|---|---|
| V-08 | 无 `from langchain.` 旧路径（C-01） | 全章 | grep 只命中注释 |
| V-09 | 模型统一 `ChatTongyi` + `qwen-plus` + 环境变量（C-02/C-03） | 全章 | grep `ChatTongyi(` 命中 7 处，`DASHSCOPE_API_KEY` 命中 7 处 |
| V-10 | 温度与教材原值一致（C-02） | 全章 | 逐篇核对（0.5/0.3/0.4/0/0/0.5/0） |
| V-11 | 六类教材 bug 均已修复 + 现场注释保留（C-05） | 01/02/04/06/07 | grep `# 注意：` / `# 原写法：` |
| V-12 | 04 篇无 `signal.SIGALRM` 可执行代码（C-06） | 04 | grep `SIGALRM` 只命中注释 |
| V-13 | 07 篇 `memory_key="chat_history"`（C-05） | 07 | grep `memory_key=` |
| V-14 | 每个文件头含「改写前的问题」+「改写策略」（C-09） | 全章 | grep 关键词 |
| V-15 | 哑工具已显式标注（C-08） | 03/05/07 | grep 「模拟」/「哑工具」 |

### 7.3 学习层验收

- [ ] 能画出 01 篇三段链的变量接力图（`topic → subtopics → questions → impact`）。
- [ ] 能解释 `.run()` 为什么在多输出键时抛 `ValueError`。
- [ ] 能背诵 ReAct 四要素并说明谁产生谁消费。
- [ ] 能解释「为什么 ReAct 工具入参是字符串」以及 Function Calling 的差异。
- [ ] 能说出 `memory_key` 与 `input_key` 的作用与匹配要求。
- [ ] 能说出沙箱三道防线各挡什么。
- [ ] 能说出「模型的拒绝不能当安全防线」的原因。
- [ ] 能说出旧式 `Tool` 与新式 `@tool` 的三个差异。
- [ ] 能画出 ReAct 模板四段组装图并指出可定制区（`prefix` / `suffix`）。
- [ ] 能解释教材 `custom_prompt` 的四重问题。
- [ ] 能说出 `memory_key="history"` 为什么是「静默失败」。
- [ ] 能完成「工作流（Chain）vs Agent」的选型论证。

---

## 8. 已知缺口与后续改进（Gap Analysis）

| 编号 | 等级 | 缺口 | 影响 | 建议改进 | 对照章节 |
|---|---|---|---|---|---|
| G-01 | 🟠 | 全章 `os.environ.get("DASHSCOPE_API_KEY")` **无空值校验** | key 未设时报错晦涩 | 启动时校验并友好提示 | chapter12 |
| G-02 | 🔴 | 01 篇教材 **`.run()` API 误用**（多输出键必抛 `ValueError`） | 原代码必崩 | `invoke({...})`（已修复，现场保留） | — |
| G-03 | 🔴 | 02 篇教材 **工具入参类型错配**（`"20" * 7.25` 必抛 `TypeError`） | 原代码必崩 | `float(amount)`（已修复） | char02（Function Calling 对照） |
| G-04 | 🟠 | 03/04/05 篇 `ConversationBufferMemory` **无上限** | 长对话超模型上下文 | `ConversationSummaryBufferMemory` / 滑动窗口 | char07（动态合并） |
| G-05 | 🟠 | 记忆**进程内、无会话隔离** | 重启丢失 + 多用户串台 | 持久化 + `session_id` 分桶 | char09-06（ContextScope） |
| G-06 | 🟠 | 04 篇沙箱**仍用 `eval`**（白名单过滤后） | 白名单有疏漏即危险 | 改 **AST 白名单**（`ast.parse`，完全不用 `eval`） | char02-07 / 13 |
| G-07 | 🟠 | 04 篇**线程限时无法真正终止线程** | 超时后线程仍在后台跑 | `multiprocessing` + `terminate()` | — |
| G-08 | 🟠 | 05/06/07 篇**无 `max_iterations`** | ReAct 可能无限循环 | 显式设 `max_iterations=5`~`10` | — |
| G-09 | 🔴 | 06 篇教材 **`custom_prompt` 是概念代码**（查源码实证，0.x 同样错） | 原代码必崩且报错难懂 | `prefix` / `suffix`（已修复） | — |
| G-10 | 🟠 | 06 篇两个工具函数**无 `requests` 的 `timeout`** | 国内网络可能挂起 | 加 `timeout=5` | 07 篇教训 |
| G-11 | 🔴 | 07 篇教材 **`memory_key` 静默失败**（不报错只失忆） | 教学目标落空且难排查 | 改 `"chat_history"`（已修复） | 06 篇源码实证 |
| G-12 | 🔴 | 07 篇 **无兜底网络调用打崩 `AgentExecutor`** | 一处超时全盘崩溃 | `try/except` + `timeout` + 模拟数据（已修复） | 06 篇（有兜底的对照） |
| G-13 | 🟡 | 07 篇 `search_books` 的 `keyword` **几乎未使用**（固定关键词列表） | 参数形同虚设 | 用 `keyword` 做真实匹配 | — |
| G-14 | 🟡 | 02 篇 `fetch_summary` 的 `[:1000]` 后 `[:300]` **冗余** | 先截 1000 再截 300 | 去掉第一步 | — |
| G-15 | 🟡 | 02 篇 `fetch_summary` **把 HTML 当摘要** | 返回标签混杂文本 | 接正文提取 | char06-04（clean_text） |
| G-16 | 🟡 | 全章 `Tool`（旧式）**已废弃** | 1.x 推荐 `@tool` | 逐步迁移到 `@tool` | 05 篇 |
| G-17 | 🟡 | 全章 **`initialize_agent` / 经典链将在 2.0 移除** | 未来不兼容 | 迁移到 **LCEL** + `create_agent` | 附录 B |
| G-18 | 🟡 | 全章 **无错误处理**（`agent.run()` 失败即中断） | 单点失败全盘中断 | 加 try/except + 重试 | chapter08（降级） |
| G-19 | 🟡 | 全章 `verbose=True` **输出不可控** | 生产冗长 | 改日志级别 | — |
| G-20 | 🟡 | 07 篇两轮输出**无前缀标识** | 难区分 `response_1` / `response_2` | 加前缀 | — |

### 缺口优先级建议

- **P0（正确性）**：G-02、G-03、G-09、G-11、G-12（**五个教材 bug，均已修复并留痕**）
- **P1（安全）**：G-06（AST 替代 eval）、G-07（进程级限时）
- **P2（健壮性）**：G-01、G-04、G-05、G-08、G-10、G-18
- **P3（迁移与整洁）**：G-13、G-14、G-15、G-16、G-17、G-19、G-20

---

## 附录 A：LangChain 1.x 导入路径映射表（全章共用）

```python
# ===== 教材原写法（0.x，全部失效） =====
from langchain.llms import OpenAI
from langchain.chat_models import ChatOpenAI
from langchain.prompts import PromptTemplate
from langchain.chains import LLMChain, SequentialChain
from langchain.agents import Tool, initialize_agent
from langchain.agents.agent_types import AgentType
from langchain.memory import ConversationBufferMemory
from langchain.tools import tool

# ===== 改写后（1.x） =====
from langchain_core.prompts import PromptTemplate                       # prompts → core
from langchain_classic.chains import LLMChain, SequentialChain          # chains → classic
from langchain_classic.agents import Tool, initialize_agent, AgentType  # agents → classic
from langchain_classic.memory import ConversationBufferMemory           # memory → classic
from langchain_classic.agents.agent_types import AgentType              # 07 篇路径
from langchain_core.tools import Tool, tool                             # tools → core
from langchain_community.chat_models import ChatTongyi                  # OpenAI → 百炼
```

## 附录 B：教材六类「死法」速查

| # | 死法 | 篇目 | 现象 | 修复 |
|---|---|---|---|---|
| 1 | import 断裂 | 全部 7 篇 | `ImportError` | `langchain_classic` / `langchain_core` |
| 2 | 模型不可直连 | 全部 7 篇 | 认证失败/超时 | `ChatTongyi` + 环境变量 |
| 3 | **API 误用（硬错误）** | 01 | `run()` 多输出键 `ValueError` | 改 `invoke()` |
| 4 | **类型错配（硬错误）** | 02 | `"20" * 7.25` `TypeError` | 显式 `float()` |
| 5 | **平台不兼容** | 04 | `SIGALRM` 在 Windows `AttributeError` | 线程限时 |
| 6 | **概念代码（最深）** | 06 | `custom_prompt` 覆盖不生效（0.x 同样错） | `prefix` / `suffix` |
| 7 | **静默失败（最隐蔽）** | 07 | `memory_key` 不匹配 → 不报错但失忆 | 改 `"chat_history"` |
| 8 | **无兜底网络调用** | 07 | 超时异常打崩 `AgentExecutor` | `try/except` + `timeout` + 模拟数据 |

> **03 与 05 篇无隐藏 bug** —— 改写后即可运行。

## 附录 C：ReAct 工具调用 vs Function Calling（02 篇 bug 的理论背景）

| 维度 | ReAct（02/03/04/05/06/07） | Function Calling（char02 系列） |
|---|---|---|
| 协议 | **文本**（`Thought:/Action:/Action Input:/Observation:`） | **JSON**（`tool_calls` 数组） |
| 模型输出 | 需**解析**的文本 | 结构化 JSON |
| 工具入参类型 | **永远是字符串** | 框架自动解析类型 |
| 类型转换责任 | **工具函数自己**（`float(amount)`） | 框架 |
| 解析失败风险 | 高（`OutputParserException`） | 低 |
| 代表 bug | **02 篇 `TypeError`** | —— |

**核心认识**：02 篇的类型 bug **不是偶然**——它是 ReAct 时代工具调用的**结构性特征**。理解了这一点，再看 07 篇的「输入清洗」（去掉书名号 / `by` 后缀）就顺理成章：**ReAct 的工具入参永远是「脏字符串」**。

## 附录 D：沙箱三道防线（04 篇）

```python
# ① 字符白名单（最硬的一道）
allowed_chars = "0123456789+-*/(). "
if not all(c in allowed_chars for c in expression):
    return "非法表达式，包含禁止字符"

# ② 空 builtins 命名空间
result = eval(expression, {"__builtins__": {}})

# ③ 限时（线程版，跨平台）
thread = threading.Thread(target=worker, daemon=True)
thread.start()
thread.join(timeout=EVAL_TIMEOUT_SECONDS)
if thread.is_alive():
    return "执行超时"
```

**挡什么**：① 挡 `import os; ...`（字母/分号不在白名单）；② 挡 `__import__("os")`（空 builtins）；③ 挡 `9**9**9`（超时）。

**⚠️ 关键认识**：**安全必须在代码层保证，不能靠提示词祈祷模型「不去执行危险命令」**。

## 附录 E：教学版 vs 生产版差距

| 教学版特征 | 生产要求 |
|---|---|
| `initialize_agent` / `ConversationBufferMemory`（2.0 将移除） | `create_agent` + LangGraph checkpointing / Store API |
| Buffer 记忆无上限、进程内、无会话隔离 | 摘要记忆/滑动窗口 + 持久化 + `session_id` 隔离 |
| 进程内线程级沙箱 | `subprocess` / Docker 容器隔离 + **AST 白名单**替代 `eval` |
| 外部依赖不可达即演示失败 | 可达数据源 + `timeout` + 降级策略（07 篇教训） |
| 工具入参靠字符串猜测与清洗 | **Function Calling JSON Schema 结构化参数** |
| 无输出审计 | 输入/输出双层过滤（char03-08）+ 置信度预警（char03-09） |
| 无 `max_iterations` | 显式迭代上限 + 超限降级 |

## 附录 F：六条跨章关联

| 本篇 | 关联章节 | 关联点 |
|---|---|---|
| 01 三段链 | char05 LangGraph 图编排 | **固定流水线 → 有向图**（Chain vs Graph） |
| 02 ReAct 循环 | char02 手写 `agent_chat` | **手写循环 vs 框架托管**（同一件事的两种实现） |
| 03 Memory | char07 上下文工程 | `ConversationBufferMemory` → 01/05/07 篇的段/日志/合并 |
| 04 沙箱 | char02-07 `exec` 警示 / char03-08 敏感词 | 安全观的落地实现 |
| 05 `@tool` | char05-04 `@tool`（同款） | LangGraph 里同样的装饰器 |
| 06 `prefix`/`suffix` | char02 全系列的 `system_message` | system prompt 概念在 ReAct 模板中的入口迁移 |
