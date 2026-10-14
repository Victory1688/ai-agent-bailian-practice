# 第 5 章 规范说明书（spec.md）——LangGraph 智能体编排与任务流管理

> **SDD 定位**：本文回答 *「多个步骤/多个智能体，如何用「图」来编排」*。
> **上篇（意图与学习路径）**回答 *为什么学、学什么、怎么学*；
> **下篇（契约与验收）**回答 *每个文件到底承诺了什么、怎么验证、还缺什么*。
> **主线**：本章是**「编排」篇**——chapter02 讲 Agent 单体怎么组装，chapter03/06 讲模型与检索，
> 本章讲**把多个步骤/多个 Agent 串成一张有向图**：
> **节点（Node）= 干活的函数**，**边（Edge）= 流转顺序**，**状态（State）= 在图里流转的共享字典**。
> 前 7 篇是「单图任务流」（顺序边 / 条件边 / 四~五节点流水线 / 真实数据库），
> 后 3 篇是「多 Agent 通信」（MCP 名对照 / A2A 消息传递 / 消息总线广播）。
>
> 适用范围：`D:/AiWorkOut/aiAgentCode/chapter05/`（10 个 .py / 1129 行）。
> 契约字段一律**从代码事实反推**，不臆造；教材简化点与改写依据一并留痕。

---

# 上篇：意图与学习路径

## 1. 章意图（Why）

### 1.1 教材原版想解决什么

教材用一章讲 LangGraph，从「两个节点」一路搭到「多 Agent 通信」：

| 教材概念 | 想说明什么 |
|---|---|
| 两个节点的图 | 节点 + 边的最小骨架 |
| 条件边 | 从「固定流水线」走向「动态任务流」 |
| 检索工具集成 | 把 LangChain 链作为节点塞进图 |
| 函数调用工具集成 | 把 LangChain 工具作为节点 |
| 简单任务流 | 四节点业务流水线 |
| 科研助手多步骤任务 | 五节点串行链 |
| 访问外部数据库 | 工位从字典模拟升级为真 SQL |
| LangGraph 与 MCP 映射 | 跨节点持久化上下文 |
| A2A 多 Agent 通信 | Agent 之间靠消息协作 |
| 消息总线广播 | 一对多广播 + 并行分支汇聚 |

### 1.2 教材原版的四大问题

**这 10 个例子在本机全部跑不出正确结果**，卡在四处：

| 问题 | 涉及例子 | 具体表现 |
|---|---|---|
| 🔴 **`class State(dict): pass` 静默失败** | **全部 10 篇** | LangGraph 1.x 靠 State 类的**类型注解**（`__annotations__`）构建状态 schema；裸 `dict`/`Dict` 子类无注解 → 图无法收集状态 → **`graph.invoke()` 返回 `None`**。**不报错、不崩溃，只是结果不对**——这是最隐蔽的坑 |
| 🔴 **LangChain 0.x import 路径断裂** | 03/04 | `from langchain.chains import RetrievalQA` → 1.x 收入 `langchain_classic.chains`；`from langchain.tools import tool` → `langchain_core.tools` |
| 🔴 **教材自带逻辑 bug（实测确认）** | 03/04/06/10 | 03 的 `llm=None`；04 的 `multiply` 无 docstring + `.invoke` 误用；06 的降级链断裂；10 的预期输出键名笔误 |
| 🟠 **`OpenAIEmbeddings` / `OpenAI` 模型** | 03 | 需 `OPENAI_API_KEY` 且国内无法直连 |

**核心洞察（本章最有价值的一课）**：
> **「静默失败」比「报错」更危险。** 10 篇的 `State(dict)` 问题，代码「跑得通」（不抛异常），
> 但结果全错。这类 bug 在真实工程里最难排查——**因为没有错误信号**。

### 1.3 本章改写要解决什么

| 教材原实现 | 改写后 | 说明 |
|---|---|---|
| `class State(dict): pass` / `class State(Dict): pass` | **`class State(TypedDict)` + 字段注解** | **本章唯一必须改的「骨架级」修改**，其余代码逐行保留 |
| `langchain.chains.RetrievalQA` | `langchain_classic.chains.RetrievalQA` | 仅换路径 |
| `langchain.tools.tool` | `langchain_core.tools.tool` | 仅换路径 |
| `OpenAIEmbeddings()` | `DashScopeEmbeddings()` | 中文 + 免 key 冲突 |
| `RetrievalQA.from_chain_type(llm=None, ...)` | `llm=ChatTongyi(model="qwen-plus")` | **修复教材 bug** |
| `multiply(a=..., b=...)`（直接调用工具对象） | `multiply.invoke({"a": ..., "b": ...})` | **修复教材 bug** |
| `multiply`（无 docstring） | 补 `"""计算两个整数的乘积"""` | **修复教材 bug** |
| 06 的 `conclude_node` 精确匹配 | `any(... in s for s in summaries)` 子串匹配 | **修复教材 bug** |

### 1.4 本章最该带走的三句话

1. **LangGraph 的 State 必须有字段注解**（`TypedDict`）——这是 1.x 的硬要求。裸 `dict` 子类会「静默失败」（`invoke` 返回 `None`）。
2. **节点就是「读整个 State、返回部分更新」的普通函数**——`def node(state) -> dict`。返回的 dict 会被**合并**进 State（不是替换）。
3. **「MCP」「A2A」教材里是同名陷阱**——08 篇的 `MCPInterface` 是内存字典存取类，09 篇的 `A2AProtocol` 是同进程消息列表，**都与真实协议无关**。真实 MCP/A2A 在 chapter10/13。

---

## 2. 学习路径（10 文件 / 1129 行）

按「骨架 → 分支 → 集成 → 流水线 → 通信」的顺序阅读：

| # | 文件 | 行数 | 核心机制 | 读完后你应能说出 |
|---|---|---|---|---|
| 01 | `01_使用langgraph定义两个节点.py` | 79 | `StateGraph(TypedDict)` + 2 节点 + 顺序边 | LangGraph 最小骨架 + State 注解的必要性 |
| 02 | `02_使用langgraph设置节点之间的条件边.py` | 107 | `add_conditional_edges` + 路由函数 + 映射表 | 条件边的三个参数各是什么 |
| 03 | `03_LangChain的检索工具与LangGraph集成.py` | 83 | `RetrievalQA` 作为节点 | 链与图的分工（链检索生成，图编排） |
| 04 | `04_LangChain函数调用工具与LangGraph集成.py` | 76 | `@tool` + `.invoke({...})` 作为节点 | 工具对象怎么正确调用 |
| 05 | `05_基于LangGraph的简单任务流.py` | 104 | 四节点流水线（预处理→检索→摘要→结论） | 节点间怎么「读上游键、写自己键」 |
| 06 | `06_科研助手多步骤任务实现.py` | 131 | 五节点链 + 列表状态 + **降级链修复** | 多节点链的状态设计 + 失败信号怎么传 |
| 07 | `07_访问外部数据库进行检索.py` | 123 | 四节点 + `sqlite3.connect(":memory:")` | 工位怎么接真实数据库 |
| 08 | `08_实现LangGraph与MCP接口的映射.py` | 136 | `MCPInterface`（外部上下文存储）+ 双通道 | 外部存储与图状态的本质差异 |
| 09 | `09_A2A的多Agent通信协议传递.py` | 140 | `A2AProtocol`（消息列表）+ 3 Agent 串行 | 消息传递范式（不共享变量的协作） |
| 10 | `10_通过消息总线进行广播多个Agent.py` | 150 | `AgentHub.broadcast` + **并行分支图（扇出-汇聚）** | 并行分支的屏障语义 |

### 阅读路线建议

- **第一遍（骨架 2 篇）**：01 → 02。图的最小骨架 + 动态分支。
- **第二遍（集成 2 篇）**：03 → 04。看见「LangChain 管工具，LangGraph 管编排」的分工。
- **第三遍（流水线 3 篇）**：05 → 06 → 07。四节点 → 五节点 → 接真数据库。
- **第四遍（通信 3 篇）**：08 → 09 → 10。外部存储 → 消息传递 → 广播 + 并行。
- **关键呼应**：01 是全章骨架；05/06/07 是它的「加节点」变体；08/09/10 是它的「多 Agent」变体。
- **必读的对照**：08（字典覆盖）vs 09（列表累积）—— 同样是「模块级外部存储」，行为完全不同。

---

## 3. 五条工程主线（本章反复出现的设计决策）

### 主线一：State 三要素（TypedDict + 字段注解 + 合并语义）

```python
class State(TypedDict):        # ← 必须 TypedDict（或带 __annotations__ 的类）
    query: str
    retrieved: str
    answer: str

def search_node(state: State):
    query = state.get("query", "")
    return {"retrieved": f"检索到与 {query} 相关的信息"}   # ← 只返回「我负责的键」
```

**三条铁律**：
1. **必须是 `TypedDict`**（或等价带注解的类）——裸 `dict`/`Dict` 子类会静默失败。
2. **字段必须覆盖节点会读到的所有键**（09 篇实测教训：漏申明 `query` → 入口键被静默裁剪）。
3. **节点返回的是「部分更新」**——LangGraph 会把返回的 dict **合并**进 State，不是替换。

### 主线二：两种边的语义

| 边类型 | API | 语义 | 出现 |
|---|---|---|---|
| **顺序边** | `add_edge("a", "b")` | a 完成后执行 b | 01/03/04/05/06/07/08/09 |
| **条件边** | `add_conditional_edges("check", route_fn, mapping)` | 按 route_fn 的返回值选目标 | 02 |
| **终止** | `add_edge("x", END)` 或 `set_finish_point("x")` | 图结束 | 全章 |
| **入口** | `set_entry_point("x")` 或 `add_edge(START, "x")` | 图的起点 | 全章 |

**条件边三参数（02 篇核心）**：
```python
builder.add_conditional_edges(
    "check",                            # ① 挂在哪个节点之后
    lambda state: state["route"],       # ② 路由函数：读状态 → 返回「选择值」
    {"fast": "fast", "normal": "normal"} # ③ 映射表：选择值 → 目标节点名
)
```

### 主线三：状态字段的「三段式」命名（05/06/07 统一）

```
入口键 ────→ 中间键 ────→ 结果键
query        retrieved     answer / conclusion
             normalized    summary
             keywords      filtered_docs
```

**每一跳都是「读上游键、写自己键」**——数据在共享状态里逐级传递，形成看得见的流水线。

### 主线四：外部存储 vs 图状态（08/09 篇的核心对照）

| 维度 | 图状态（`State`） | 外部存储（`mcp.context_store` / `a2a.messages`） |
|---|---|---|
| 生命周期 | **每次 `invoke` 从零开始** | **跨 `invoke` 存活**（模块级对象） |
| 存储形态 | LangGraph 内部管理 | 字典（08）/ 列表（09/10） |
| 第二次 invoke | 全新状态 | **字典：同名 key 被覆盖**（08）；**列表：append 累积**（09/10） |
| 生产对应 | 请求级上下文 | Redis / DB / 文件 |

**生产对应（08 篇注释明确）**：`MCPInterface` 对应的真实概念是「节点间通过共享的外部存储交换上下文」，生产用 Redis/数据库/文件。

### 主线五：消息传递范式（09/10 篇）

```
┌─────────────────────────────────────────────────┐
│  图状态只存「结果」，Agent 之间的「交流」走消息总线  │
└─────────────────────────────────────────────────┘
AgentA ──send(retrieved)──→ AgentB ──send(analysis)──→ AgentC
                                  ↑
                          receive() 按 receiver 过滤出收件箱
```

**关键设计点**：
- **Agent 之间不共享变量**——只能「发消息 / 收消息」；
- `receive(agent)` 按 `receiver` 过滤出「收件箱」；
- `inbox[-1]` 取最新一条（同收件人多条时的取舍策略）；
- **10 篇升级**：`broadcast` = 循环单播（一条消息同时投给多个 Agent）。

---

## 4. 学习检查清单（读完自测）

- [ ] 能说出为什么 `class State(dict): pass` 会导致 `invoke` 返回 `None`。
- [ ] 能指出「静默失败」与「报错」哪个更难排查，为什么。
- [ ] 能写出条件边的三个参数。
- [ ] 能说出节点函数的返回语义（部分更新 vs 全量替换）。
- [ ] 能说出 05 篇四个节点各自读什么键、写什么键。
- [ ] 能解释 06 篇的降级链为什么断裂、怎么修的。
- [ ] 能说出 `sqlite3.connect(":memory:")` 的生命周期特点。
- [ ] 能说出 08（字典覆盖）与 09（列表累积）的差别。
- [ ] 能说出教材的「MCPInterface」「A2AProtocol」与真实协议的关系。
- [ ] 能解释 10 篇的「扇出-汇聚」和「屏障语义」。

---

# 下篇：契约与验收

## 5. 全局技术约束（C-xx）

### C-01 State 必须使用 `TypedDict` 且字段完整

**约束**：
```python
from typing import TypedDict
class State(TypedDict):
    ...字段注解...
```
**禁止**：`class State(dict): pass` / `class State(Dict): pass`（无注解 → 静默失败）。
**要求**：字段必须覆盖**所有节点会读到的键**（含入口键如 `query`）。
**验收**：10 篇 grep `class State` 应全部为 `(TypedDict)`。

### C-02 节点函数签名统一

```python
def xxx_node(state: State) -> State:
    value = state.get("key", default)      # 读：用 .get 带默认值
    return {"new_key": ...}                # 写：只返回自己负责的键
```
**约束**：参数为整个 State；返回 dict（部分更新）。
**要点**：使用 `state.get(key, default)` 而非 `state[key]`，避免 KeyError。

### C-03 图构建标准顺序

```python
builder = StateGraph(State)
builder.add_node("name", fn)          # 1. 加节点
builder.add_edge(...)                 # 2. 加边
builder.set_entry_point("first")      # 3. 设入口
builder.add_edge("last", END)         # 4. 设终点（或 set_finish_point）
graph = builder.compile()             # 5. 编译
result = graph.invoke({...})          # 6. 执行
```
**说明**：`set_entry_point` / `set_finish_point` 是旧式 API（新版推荐 `add_edge(START, ...)` / `add_edge(..., END)`），但 1.x 仍可用——**本篇保持与教材一致**。

### C-04 LangChain 1.x 导入路径

| 对象 | 正确路径 | 教材旧路径 |
|---|---|---|
| `RetrievalQA` | `langchain_classic.chains` | `langchain.chains` |
| `FAISS` | `langchain_community.vectorstores` | `langchain.vectorstores` |
| `DashScopeEmbeddings` | `langchain_community.embeddings` | `langchain.embeddings`（OpenAIEmbeddings） |
| `ChatTongyi` | `langchain_community.chat_models` | — |
| `@tool` | `langchain_core.tools` | `langchain.tools` |

### C-05 模型统一百炼

- `ChatTongyi(model="qwen-plus", dashscope_api_key=os.environ.get("DASHSCOPE_API_KEY"))`（LangChain 封装，03 篇）
- `DashScopeEmbeddings()`（向量化，03 篇）
- **本章 8 篇无 LLM 调用**（01/02/04~10 都是纯本地模拟）——只有 03 篇真正调模型。

### C-06 `@tool` 装饰的函数必须有 docstring

**约束**：
```python
@tool
def multiply(a: int, b: int) -> int:
    """计算两个整数的乘积"""      # ← 必须有（= 工具说明书 description）
    return a * b
```
**理由**：LangGraph/LangChain 的 `@tool` 若无 docstring 且未传 `description`，**直接抛 `ValueError`**。
**教学呼应**：`@tool` 一键生成 Function Calling 三件套——**类型注解 = 参数 schema，docstring = description，函数体 = 执行逻辑**。

### C-07 工具对象必须用 `.invoke(参数字典)` 调用

```python
result = multiply.invoke({"a": state["x"], "b": state["y"]})    # ✅
# result = multiply(a=..., b=...)                                # ❌ TypeError: 'StructuredTool' object is not callable
```
**理由**：`@tool` 返回的是 `StructuredTool` **工具对象**，不是函数本身。

### C-08 失败信号必须用「结构化字段」或「子串匹配」

**约束**：**禁止**用精确匹配（`x in list_of_strings`）判断「被加工过的失败信号」。
**反例（06 篇教材 bug）**：`"有效文献不足" in ["有效文献不足..."]` → `False`（因省略号），降级链断裂。
**正例（06 篇修复）**：
```python
if any(("有效文献不足" in s) or ("未找到" in s) or (s == "暂无摘要") for s in summaries):
```
**更优方案（07 篇注释建议）**：用结构化 `status` 字段传失败状态（如 `{"status": "failed", "reason": ...}`）。

### C-09 外部存储必须是模块级对象

**约束**：`mcp = MCPInterface()` / `a2a = A2AProtocol()` / `hub = AgentHub()` 都定义在**模块级**，所有节点共享同一个实例。
**理由**：这是「跨节点/跨 invoke 持久化」的实现基础。
**已知风险**：模块级全局 → 多会话污染（见缺口 G-04）。

### C-10 SQL 必须用 `?` 占位符

**约束**：07 篇的 SQL 查询必须 `cursor.execute("SELECT ... WHERE keyword=?", (kw,))`。
**理由**：SQL 注入防护（呼应 chapter02-06）。

### C-11 教材原代码以注释保留 + 明确标注问题

**约束**：每篇文件头必须包含：
1. 教材原写法（含 `class State(dict): pass`）；
2. 不可运行/结果错误的**具体原因**；
3. 改写方案。
**实例**：01 篇注释明确指出「这是比 06/07 篇更隐蔽的『静默失败』：不报错、不崩溃，只是结果不对」。

### C-12 教材 bug 修补必须留痕

**约束**：发现教材逻辑 bug 时，**必须**在注释中说明「原写法 → 问题 → 修复」三段。
**实例**：04 篇（docstring + `.invoke`）、06 篇（降级链）、10 篇（预期输出键名笔误）。

### C-13 名不副实的概念必须诚实辨析

**约束**：教材中「名不副实」的概念必须**显式指认**，说明「真实概念是什么」。
**实例**：
- 08 篇：「教材的 `MCPInterface` 只是**一个内存字典存取类**——它与 MCP 协议毫无关系……见到『自定义 MCP 类』先怀疑是不是同名陷阱」。
- 09 篇：「教材的 `A2AProtocol` 只是**同进程内的消息列表存取类**——它与 A2A 协议毫无关系（08 篇的『MCP』同理）」。

---

## 6. 逐文件契约（F-01 ~ F-10）

---

### F-01 `01_使用langgraph定义两个节点.py`（79 行）——最小骨架篇

**意图**：LangGraph 最小骨架——2 节点 + 顺序边，先建图再谈能力。

**State 契约**：
```python
class State(TypedDict):
    query: str
    retrieved: str
    answer: str
```

**节点契约**：
| 节点 | 读 | 写 |
|---|---|---|
| `search_node` | `query` | `retrieved` = `f"检索到与 {query} 相关的信息"` |
| `generate_node` | `retrieved` | `answer` = `f"基于{info}生成最终答案"` |

**图契约**：`add_edge("search","generate")` + `set_entry_point("search")` + `set_finish_point("generate")` + `compile()`。

**输出契约**：`print(graph.invoke({"query": "LangGraph"}))` → 含 `retrieved` 与 `answer` 的 dict。

**验收标准**：
- V-01-A：`result` **不是 None**（若为 None 说明 State 注解缺失）。
- V-01-B：`result["retrieved"] == "检索到与 LangGraph 相关的信息"`。
- V-01-C：`result["answer"] == "基于检索到与 LangGraph 相关的信息生成最终答案"`。

**教材问题（文件头注释实录）**：
> 原写法：`class State(dict): pass`（无字段注解的 dict 子类）。
> 原写法的问题：本篇实测 langgraph 1.2.11 下代码"跑得通但结果错误"——`graph.invoke()` 返回 `None` 而不是预期的状态字典。原因：LangGraph 1.x 靠 State 类的类型注解（`__annotations__`）来构建状态 schema，裸 dict 子类没有任何字段注解，图无法收集状态，invoke 只能返回 None。**这是比 06/07 篇更隐蔽的"静默失败"：不报错、不崩溃，只是结果不对。**

---

### F-02 `02_使用langgraph设置节点之间的条件边.py`（107 行）——条件边篇

**意图**：从「固定流水线」走向「动态任务流」。

**State 契约**：`query` / `route`（中间变量）/ `response`。

**三个节点契约**：
| 节点 | 逻辑 |
|---|---|
| `check_node` | `"urgent" in query.lower()` → `route="fast"`；否则 `"normal"` |
| `fast_node` | `response = "快速处理路径已启动"` |
| `normal_node` | `response = "普通处理路径已启动"` |

**条件边契约（本篇核心）**：
```python
builder.add_conditional_edges(
    "check",                              # 挂在 check 之后
    lambda state: state["route"],         # 路由函数
    {"fast": "fast", "normal": "normal"}  # 映射表
)
```

**验收标准（与教材预期完全一致）**：
- V-02-A：`invoke({"query": "urgent request"})` → `{'query': 'urgent request', 'route': 'fast', 'response': '快速处理路径已启动'}`。
- V-02-B：`invoke({"query": "regular request"})` → `route='normal'`, `response='普通处理路径已启动'`。

**已知风险**：路由函数 `lambda state: state["route"]` **用下标取值**（非 `.get`）——若 `check_node` 未写 `route` 会 KeyError（本篇流程保证安全）。**且映射表必须覆盖路由函数的全部可能返回值**，否则 LangGraph 报错（见缺口 G-05）。

**教材问题（文件头注释实录）**：
> 原写法的问题：与 01 篇相同——langgraph 1.x 靠 State 类的类型注解构建状态 schema，裸 dict 子类无注解，实测 `graph.invoke()` 返回 None（静默失败）。
> **本篇问题更典型：条件边的路由函数 `lambda state: state["route"]` 依赖 route 键，无 schema 时这个键根本不在图的状态定义里。**

---

### F-03 `03_LangChain的检索工具与LangGraph集成.py`（83 行）——链集成篇

**意图**：把 char04/06 式的「LangChain 链」作为一个节点塞进图——**链负责检索+生成，图负责编排调度**。

**导入契约（1.x）**：
```python
from langchain_classic.chains import RetrievalQA
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_community.chat_models import ChatTongyi
from langgraph.graph import StateGraph
```

**LLM 契约（修复教材 `llm=None`）**：
```python
llm = ChatTongyi(model="qwen-plus", dashscope_api_key=os.environ.get("DASHSCOPE_API_KEY"))
```

**链契约**：
```python
db = FAISS.from_texts(["LangGraph是一个任务编排框架", "LangChain是一个工具链框架"], DashScopeEmbeddings())
retriever = db.as_retriever()
qa_tool = RetrievalQA.from_chain_type(llm=llm, retriever=retriever, chain_type="stuff")
```

**State + 节点契约**：`State(question, answer)`；`query_node` 调 `qa_tool.run(state["question"])` → `{"answer": result}`。

**验收标准**：
- V-03-A：`invoke({"question": "LangGraph是什么？"})` 返回含 `answer` 的 dict。
- V-03-B：`answer` 是**基于检索到的「LangGraph是一个任务编排框架」生成的回答**（不是空串）。
- V-03-C：`llm` 不为 None（否则 `RetrievalQA.run()` 报错）。

**已知风险**：
- ⚠️ `DashScopeEmbeddings()` **未传 `dashscope_api_key`**（依赖环境变量自动读取）——若环境变量未设会失败（对比 06 章的显式传参）。
- ⚠️ 知识库只有 2 条，检索意义有限（教学用的最小数据）。
- ⚠️ `qa_tool.run()` 是 LangChain 的**同步阻塞**调用。

**教材问题（文件头注释实录）**：
> 原写法：langchain 0.x 的 import 路径 + OpenAI 模型类，在当前环境无法运行，原因有四：① LangChain 1.x 路径拆分：RetrievalQA 收纳进 `langchain_classic.chains`……② `OpenAIEmbeddings` 需要 `OPENAI_API_KEY` 且国内无法直连；③ **`llm=None` 是教材伪代码**——`RetrievalQA` 的职责是"检索 + 让 LLM 基于检索结果生成答案"，没有 LLM 这条链根本无法工作（run 时必然报错）；④ `class State(dict): pass` 无字段注解——langgraph 1.x 无法构建状态 schema，实测 invoke 返回 None。

---

### F-04 `04_LangChain函数调用工具与LangGraph集成.py`（76 行）——工具集成篇

**意图**：把 LangChain 工具接入图节点；修复教材两处 bug。

**导入契约**：`from langchain_core.tools import tool`。

**工具契约（修复 docstring）**：
```python
@tool
def multiply(a: int, b: int) -> int:
    """计算两个整数的乘积"""      # ← 教材缺失，实测抛 ValueError
    return a * b
```

**节点契约（修复调用方式）**：
```python
def calc_node(state: State):
    result = multiply.invoke({"a": state["x"], "b": state["y"]})   # ✅
    # 原写法：multiply(a=state["x"], b=state["y"]) → TypeError: 'StructuredTool' object is not callable
    return {"product": result}
```

**State 契约**：`x: int` / `y: int` / `product: int`。

**验收标准**：
- V-04-A：`invoke({"x": 7, "y": 8})` → `product == 56`。
- V-04-B：`multiply` 有 docstring（`multiply.description` 非空）。
- V-04-C：不再抛 `ValueError` / `TypeError`。

**已知风险**：
- ⚠️ 本篇的 `multiply` 是**被节点「手动调用」**的（**没有大模型参与决策**）——文件头注释明确说明：「真正的『模型自主决定调不调工具』（Function Calling 循环）见 char02 系列与 char05 后续篇章」。**标题里的「函数调用」易被误解为 Function Calling**。
- ⚠️ State 字段是 `int` 类型，但 LangGraph 不强制校验（传字符串会静默通过）。

**教材问题（文件头注释实录）**：
> 原写法：import 路径断裂 + 两处教材自带 bug（实测确认）：① `from langchain.tools import tool` —— LangChain 1.x 中 `@tool` 收纳进 `langchain_core.tools`；② 教材的 `multiply` 函数**没有 docstring** —— `@tool` 装饰器实测直接抛 `ValueError: "Function must have a docstring if description not provided"`（docstring 就是工具说明书 description，没有它模型不知道这工具干嘛的）；③ `calc_node` 里 `multiply(a=state["x"], b=state["y"])` —— 实测抛 `TypeError: "'StructuredTool' object is not callable"`（`@tool` 返回的是 StructuredTool 工具对象，不是函数本身，调用它的标准方式是 `.invoke(参数字典)`）；④ `class State(dict): pass` 无字段注解 —— langgraph 1.x 静默失败。

---

### F-05 `05_基于LangGraph的简单任务流.py`（104 行）——四节点流水线篇

**意图**：01 的两节点图扩展为完整四节点业务流水线。

**State 契约（五字段）**：
```python
class State(TypedDict):
    query: str; standardized: str; retrieved: str; summary: str; conclusion: str
```

**四节点契约**：

| 节点 | 读 | 写 | 逻辑 |
|---|---|---|---|
| `preprocess_node` | `query` | `query`（strip 后）、`standardized`（lower + 去 `?`） | 标准化 |
| `retrieve_node` | `standardized` | `retrieved` | 字典**精确匹配**（`database.get(keyword, "未找到相关文献")`） |
| `summarize_node` | `retrieved` | `summary` | 失败信号 → `"暂无可用信息"`；否则 `content[:20] + "..."` |
| `conclude_node` | `summary` | `conclusion` | 失败 → `"当前问题未能得到支持性资料"`；否则 `f"基于文献摘要可得: {summary}"` |

**边契约**：`set_entry_point("preprocess")` + 三条件顺序边 + `add_edge("conclude", END)`。

**验收标准**：
- V-05-A：`invoke({"query": "LangGraph?"})` → `standardized == "langgraph"`。
- V-05-B：`retrieved == "LangGraph是一种任务图编排框架，擅长复杂流程管理"`（**精确匹配命中**）。
- V-05-C：**`summary == "LangGraph是一种任务图编排框架，..."`** —— 注意 `content[:20]` 按字符截断（第 20 个字符是「，」），**与教材手写预期「...编排框...」不同**。

**已知风险 / 关键点**：
- ⚠️ **`retrieve_node` 是字典精确匹配** —— `standardized` 必须**恰好等于**某个 key（`langgraph` / `agent`）才命中。问「LangGraph 是什么」（带空格）会 miss（见缺口 G-06）。
- ⚠️ `preprocess_node` **同时改写 `query` 键**（strip 后的值覆盖原值）——这是「节点可以修改已有键」的示例，但会丢失原始输入。
- ⚠️ `summarize_node` 的截断是**硬截断字符**（真实场景应换成 LLM 摘要，注释已说明）。
- 教材预期输出与实测**有差异**（截断长度）——文件尾注释已如实记录。

**教材问题（文件头注释实录）**：
> 原写法：`from typing import Dict` + `class State(Dict): pass`。原写法的问题：与 01-04 篇相同——langgraph 1.x 靠 State 类的字段注解构建状态 schema，Dict 子类依然没有字段注解，实测 `graph.invoke()` 返回 None（静默失败，**系列第五次**）。

---

### F-06 `06_科研助手多步骤任务实现.py`（131 行）——五节点链 + 降级链修复篇

**意图**：五节点串行链 + 修复教材的**降级链断裂 bug**。

**State 契约（六字段，含两个列表）**：
```python
class State(TypedDict):
    query: str; keywords: List[str]; retrieved_docs: List[str]
    filtered_docs: List[str]; summaries: List[str]; conclusion: str
```

**五节点契约**：

| 节点 | 逻辑 |
|---|---|
| `preprocess_node` | `keywords = [w.lower() for w in query.split() if len(w) > 3]` |
| `retrieve_node` | 遍历 keywords 查字典（`graph`/`agent`），命中则 extend |
| `filter_node` | `list({doc for doc in docs if "未找到" not in doc})`（**set 去重，会打乱顺序**） |
| `summarize_node` | `[doc[:15] + "..." for doc in docs]` |
| `conclude_node` | **修复：子串匹配** |

**降级链修复契约（本篇核心教学点）**：
```python
# 原写法（bug）：精确匹配列表元素
# if "暂无摘要" in summaries or "有效文献不足" in summaries:   ← 失败信号被加了省略号，永不匹配
# 修复：子串匹配，失败信号无论是否被加工都能识别
if any(("有效文献不足" in s) or ("未找到" in s) or (s == "暂无摘要") for s in summaries):
    conclusion = "未能生成可靠的科研结论"
else:
    conclusion = "基于现有文献分析：" + " | ".join(summaries)
```

**验收标准**：
- V-06-A（正常路径）：`invoke({"query": "Graph Agent Research"})` → 4 条 `retrieved_docs`，`conclusion` 以「基于现有文献分析：」开头。
- V-06-B（故障路径）：`invoke({"query": "Quantum Research"})` → `filtered_docs == ["有效文献不足"]`，**`conclusion == "未能生成可靠的科研结论"`**（修复后）。
- V-06-C：修复前故障路径的 `conclusion` 会是 `"基于现有文献分析：有效文献不足..."`（**失败被当正常结果**）。

**已知风险 / 关键点**：
- ⚠️ `filter_node` 用 **set 推导式去重 → 打乱文档顺序**（注释已提醒：生产用 `dict.fromkeys` 保序）。
- ⚠️ 关键词提取是「按空格分词 + len>3」——**对中文无效**（中文无空格），只适合英文 query。
- ⚠️ 失败信号**仍是字符串**，靠「子串匹配」补救——**根本方案是用结构化 `status` 字段**（注释已建议，见缺口 G-01）。
- ⚠️ `keywords` 含 `research` 但数据库无此键 → 静默跳过（无提示）。

**教材问题（文件头注释实录）**：
> 另一处教材自带 bug（`conclude_node` 的降级链断裂，实测确认）：故障路径下 `filter_node` 产出失败信号 "有效文献不足"（6 个字符，不足 15 字不截断），`summarize_node` 仍会给它拼上省略号 → `summaries` 里是 "有效文献不足..."；而 `conclude_node` 用精确匹配 `if "有效文献不足" in summaries` 判断——列表里是带省略号的版本，精确匹配永远失败 → 走 else 分支，最终输出 "基于现有文献分析：有效文献不足..."——**失败被当成正常分析结果输出**。
> 修复：改用子串匹配（`any` + `in` 字符串包含判断），失败信号无论是否被加工过都能识别。

---

### F-07 `07_访问外部数据库进行检索.py`（123 行）——真实数据库篇

**意图**：retrieve 工位从字典模拟升级为**真正的 SQL 查询**。

**State 契约**：`query` / `keywords: List[str]` / `retrieved: List[str]` / `processed: List[str]` / `conclusion`。

**数据库契约（`retrieve_node`）**：
```python
conn = sqlite3.connect(":memory:")                     # 内存库
cursor.execute("CREATE TABLE papers (id INTEGER PRIMARY KEY, keyword TEXT, content TEXT)")
cursor.executemany("INSERT INTO papers (keyword, content) VALUES (?, ?)", [...])
for kw in state["keywords"]:
    cursor.execute("SELECT content FROM papers WHERE keyword=?", (kw,))   # ← ? 占位符防注入
    results.extend([row[0] for row in cursor.fetchall()])
conn.close()
```
**三个教学点（注释明确）**：
1. `:memory:` 内存库——**每次连接都是全新空库**，关闭即销毁，故每次执行节点都要重建表；
2. `CREATE TABLE` / `executemany` / `SELECT` 是标准 SQL；
3. `?` 占位符 + 元组传参 = SQL 注入防护。

**工具节点契约**：`processed = [doc.replace("系统", "智能体系统") for doc in docs]`（模拟外部工具）。

**结论节点契约**：
```python
if "未找到相关数据" in processed or "工具未返回结果" in processed:
    conclusion = "未能生成有效结论"
```

**验收标准**：
- V-07-A（正常）：`invoke({"query": "Graph Agent Database Research"})` → `retrieved` 3 条，`processed` 中「多Agent**智能体**系统依赖…」（replace 生效）。
- V-07-B（故障）：`invoke({"query": "Quantum"})` → `conclusion == "未能生成有效结论"`。

**已知风险 / 关键洞察（注释已点明）**：
- 🔴 **降级链「活着」是运气不是设计** —— 注释明确：「`conclude` 用精确匹配判断失败信号，而上一工位 tool 的 `replace` 恰好不会加工『未找到相关数据』（信号里没有『系统』二字）——本篇降级链活着是**运气**不是设计！若失败信号改叫『检索系统异常』，`replace` 会把它变成『检索智能体系统异常』，精确匹配立刻失效——与 06 篇同款断裂。」
- ⚠️ **每次执行节点都重建表/插数据** —— 内存库生命周期决定（生产应换文件库/连接池，只做一次）。
- ⚠️ `:memory:` 意味着**每次 invoke 都从零建库**，无法跨 invoke 持久化。

**教材问题（文件头注释实录）**：
> 原写法的问题：与 01-06 篇相同——langgraph 1.x 靠 State 类的字段注解构建状态 schema，Dict 子类没有字段注解，实测 `graph.invoke()` 返回 None（静默失败，系列第七次）。
> 改写：State 改用 TypedDict（五个字段注解，教材 import 的 List 正好派上用场）。四个节点函数（`sqlite3` 逻辑一字未动）、图构建、invoke 与原版逐行一致。

---

### F-08 `08_实现LangGraph与MCP接口的映射.py`（136 行）——外部上下文存储篇

**意图**：演示「节点间通过共享的**外部存储**交换上下文」（与图 State 并行）。

**「MCP」辨析（本篇最重要的教学点）**：
> 教材的 `MCPInterface` 只是**一个内存字典存取类**——它与 MCP 协议毫无关系，真正演示的概念是「节点间通过共享的外部存储交换上下文」（生产对应 Redis/数据库/文件）。

**`MCPInterface` 契约**：
```python
class MCPInterface:
    def __init__(self): self.context_store = {}
    def save_context(self, key: str, value: Dict): self.context_store[key] = value
    def load_context(self, key: str) -> Dict: return self.context_store.get(key, {})
```
**模块级实例**：`mcp = MCPInterface()`（所有节点共享）。

**双通道契约**：
| 节点 | 写 State | 写 mcp |
|---|---|---|
| `preprocess_node` | `query` | `query_ctx` = `{"query": query}` |
| `retrieve_node` | `retrieved` | `retrieval_ctx` = `{"retrieved": result}` |
| `conclude_node` | `summary` | `final_ctx` = `{"summary": summary}` |

**`conclude_node` 契约**：从 mcp **读**前两节点的存档拼摘要：`f"问题:{query_ctx.get('query')} | 检索结果:{retrieval_ctx.get('retrieved')}"`。

**验收标准**：
- V-08-A：第一次 `invoke({"query": "LangGraph"})` → `summary == "问题:LangGraph | 检索结果:LangGraph支持任务图编排"`。
- V-08-B：第二次 `invoke({"query": "Agent"})` → `summary` 换成 Agent 数据。
- V-08-C：**最终 `mcp.context_store` 的三个键全部是第二次的数据**（`query_ctx` / `retrieval_ctx` / `final_ctx` 被**覆盖**）。

**已知风险**：
- ⚠️ **字典 key 固定 → 同名覆盖** —— 第二次 invoke 的数据覆盖第一次（注释已实证）。**这是「外部存储」与「图状态」的本质差异**。
- ⚠️ `context_store` 无清理机制 —— 长期运行会累积（虽然 key 数固定）。
- ⚠️ 模块级单例 → **多会话污染**（并发 invoke 会互相覆盖）（见缺口 G-04）。
- ⚠️ `retrieve_node` 用 `query.lower()` 精确匹配 `fake_db` —— 只支持 `langgraph` / `agent` 两个关键词。

**教材问题（文件头注释实录）**：
> 【重要辨析——教材"MCP"名的诚实说明】真实世界的 MCP（Model Context Protocol）是 Anthropic 提出的开放协议：客户端-服务器架构、JSON-RPC 通信、工具/资源/提示三大原语，与 LangGraph 的真实集成走 `langchain-mcp-adapters` 库。**教材的 `MCPInterface` 只是一个内存字典存取类——它与 MCP 协议毫无关系**，真正演示的概念是"节点间通过共享的外部存储交换上下文"。本篇保留教材命名（方便对照原书），但请记住：**见到"自定义 MCP 类"先怀疑是不是同名陷阱**。

---

### F-09 `09_A2A的多Agent通信协议传递.py`（140 行）——消息传递篇

**意图**：演示**消息传递范式**——Agent 之间不共享变量，靠「发消息/收消息」协作。

**「A2A」辨析**：
> 教材的 `A2AProtocol` 只是**同进程内的消息列表存取类**——它与 A2A 协议毫无关系（08 篇的「MCP」同理）。本篇真正教的概念是「消息传递范式」。

**State 契约（**必须含 `query`**）**：
```python
class State(TypedDict):
    query: str                # ← 实测教训：漏声明会被静默裁剪
    agentA_result: str
    agentB_analysis: str
    agentC_conclusion: str
```

**`A2AProtocol` 契约**：
```python
def send(self, sender, receiver, content):
    message = {"sender": ..., "receiver": ..., "timestamp": time.time(), "content": content}
    self.messages.append(message)
def receive(self, agent):
    return [msg for msg in self.messages if msg["receiver"] == agent]    # 按收件人过滤收件箱
```

**三节点契约**：
| 节点 | 行为 |
|---|---|
| `agent_a_node` | 检索 → `a2a.send("AgentA","AgentB",{"retrieved": result})` → 写 `agentA_result` |
| `agent_b_node` | `inbox = a2a.receive("AgentB")`；`inbox[-1]["content"].get("retrieved")` → 分析 → `send("AgentB","AgentC",{"analysis":...})` |
| `agent_c_node` | `inbox = a2a.receive("AgentC")`；`inbox[-1]["content"].get("analysis")` → 结论 |

**验收标准**：
- V-09-A：第一次 `invoke({"query": "LangGraph"})` → `agentC_conclusion` 含「LangGraph是一种任务图编排框架」。
- V-09-B：第二次 `invoke({"query": "Agent"})` → 结论换成 Agent 数据。
- V-09-C：**最终 `a2a.messages` 有 4 条**（两次运行各 2 条）——**列表 append 累积**（对比 08 篇的字典覆盖）。

**已知风险 / 关键教训（注释明确）**：
- 🔴 **State 漏声明入口键会被静默裁剪** —— 文件头注释：「初版改写只声明了三个结果字段、漏了 `query`，结果 LangGraph 1.x 把不在 schema 里的输入键**静默裁剪**——两次 invoke 全链路『未找到相关数据』。**这比 01-08 篇的『返回 None』更隐蔽：图正常跑完，数据悄悄丢在入口。**」
- ⚠️ `messages` **只增不减** —— 长期运行会内存膨胀（见缺口 G-03）。
- ⚠️ `inbox[-1]` 取最新 —— 若多个 Agent 交叉发送，可能取错（本例串行无此问题）。
- ⚠️ `receive` 每次都**全量扫描** `messages` —— O(n) 复杂度，大规模下低效。
- ⚠️ 消息无「已读/确认」机制 —— 发送方不知道对方是否处理。

**教材问题（文件头注释实录）**：
> 【重要辨析——教材"A2A"名的诚实说明】真实世界的 A2A（Agent2Agent Protocol）是 Google 于 2025 年提出的开放协议（后捐给 Linux 基金会）：Agent Card（能力发现）/ Task / Message 标准对象、JSON-RPC over HTTP 传输，与 MCP 是"姊妹协议"。**教材的 `A2AProtocol` 只是同进程内的消息列表存取类——它与 A2A 协议毫无关系**。本篇真正教的概念是"消息传递范式"：Agent 之间不共享变量，靠"发消息/收消息"协作——**这个范式在分布式多 Agent（不同进程/机器）才是刚需，同进程教学演示只是它的婴儿版。**

---

### F-10 `10_通过消息总线进行广播多个Agent.py`（150 行）——广播 + 并行分支篇

**意图**：三个新知识点——广播、**并行分支图（扇出-汇聚）**、随机分工。

**State 契约（五字段，**必须含 `query`**）**：
```python
class State(TypedDict):
    query: str
    AgentA_tasks: List[str]
    AgentB_results: List[str]
    AgentC_results: List[str]
    AgentD_conclusion: str
```

**`AgentHub` 契约（相对 09 篇新增 `broadcast`）**：
```python
def send(self, sender, receiver, content): ...        # 单播
def broadcast(self, sender, content, agents):          # 广播 = 循环单播
    for agent in agents: self.send(sender, agent, content)
def receive(self, agent): ...
```

**四节点契约**：
| 节点 | 行为 |
|---|---|
| `agent_a_node` | `sub_tasks = [f"{query}-子任务{i}" for i in range(1,4)]` → `broadcast(..., ["AgentB","AgentC"])` |
| `agent_b_node` | 收到 tasks → `[f"AgentB完成:{t}" for t in tasks if random.choice([True,False])]` |
| `agent_c_node` | 同 B，前缀 `AgentC` |
| `agent_d_node` | 遍历收件箱**全部**消息，`extend` 汇总 → `" | ".join(aggregated)` |

**图契约（系列第一个并行分支图）**：
```python
builder.add_edge("agentA", "agentB")
builder.add_edge("agentA", "agentC")     # ← A 后分叉，B/C 并行（同一 superstep）
builder.add_edge("agentB", "agentD")
builder.add_edge("agentC", "agentD")     # ← 汇聚：D 等两个分支都完成（屏障语义）
builder.add_edge("agentD", END)
```

**验收标准**：
- V-10-A：`invoke({"query": "科研协作任务"})` → `AgentA_tasks` 有 3 条子任务。
- V-10-B：`AgentB_results` 与 `AgentC_results` 各自随机子集（**每次运行不同**）。
- V-10-C：**`AgentD_conclusion` 是字符串**（`" | ".join`），**不是列表**（教材预期输出的 `AgentD_results` 键是笔误）。
- V-10-D：`hub.messages` **共 4 条**（A 广播给 B/C 各 1 条 + B/C 汇报给 D 各 1 条）。

**已知风险 / 关键点**：
- 🔴 **教材预期输出键名笔误**（注释已勘误）——「`agent_d_node` 返回的键是 `AgentD_conclusion`，值是 `" | ".join` 拼的字符串，不是名为 `AgentD_results` 的列表」。
- ⚠️ **随机分工可能导致任务重复/漏做** —— `random.choice([True,False])` 独立随机 → 极端情况 B 和 C 都跳过全部任务（`aggregated` 为空 → `"未获得有效结果"`）。教材展示的「恰好一人一个」只是一种可能。
- ⚠️ **广播 = 循环单播**（非真广播）—— 每个订阅者各存一份完整副本，N 个订阅者存 N 份（见缺口 G-07）。
- ⚠️ **`agent_d_node` 无去重** —— 若任务被重复完成，结论里会重复出现。
- ⚠️ **并行分支的写入冲突** —— B 和 C 在同一 superstep 写不同键（`AgentB_results` / `AgentC_results`），无冲突；**但若写同一个键，LangGraph 的行为需显式定义 reducer**（见缺口 G-02）。

**教材问题（文件头注释实录）**：
> 【教材预期输出勘误（重要）】教材第 4-8 行预期输出中的最后一条：`{'AgentD_results': [...]}` 与实际代码不符——`agent_d_node` 返回的键是 `AgentD_conclusion`，值是 `" | ".join` 拼的字符串，不是名为 `AgentD_results` 的列表。另外 AgentB/AgentC 的分工是 `random.choice` 随机决定，教材展示的只是一种可能，**每次运行都不同（可能出现任务重复、任务漏做、极端情况全空）——这正是随机模拟的本意。**
> 【必须包含 query 字段——09 篇的实测教训】漏声明节点会读的入口键，LangGraph 1.x 会静默裁剪该输入键（不报错），`agent_a_node` 拿到空 query，拆出的任务变成 `"-子任务1"`（前缀丢失）。

---

## 7. 全章验收清单（V-01 ~ V-12）

### 7.1 运行层验收

| 编号 | 验收项 | 期望 |
|---|---|---|
| V-01 | `python 01_...py` | 返回含 retrieved/answer 的 dict（**非 None**） |
| V-02 | `python 02_...py` | 两行输出分别走 fast / normal |
| V-03 | `python 03_...py` | 返回含 answer 的 dict（answer 非空） |
| V-04 | `python 04_...py` | `product == 56` |
| V-05 | `python 05_...py` | 五字段齐全，standardized == "langgraph" |
| V-06 | `python 06_...py` | 正常路径 4 条文献；故障路径 conclusion == "未能生成可靠的科研结论" |
| V-07 | `python 07_...py` | 正常路径 replace 生效；故障路径 conclusion == "未能生成有效结论" |
| V-08 | `python 08_...py` | 两次 invoke + context_store 三键均为第二次数据 |
| V-09 | `python 09_...py` | 两次 invoke + messages 共 4 条 |
| V-10 | `python 10_...py` | AgentD_conclusion 为字符串 + messages 共 4 条 |

### 7.2 契约层验收

| 编号 | 契约 | 对应 | 验证方式 |
|---|---|---|---|
| V-11 | 全部 `class State` 为 `TypedDict`（C-01） | 全章 | grep `class State` |
| V-12 | State 字段覆盖入口键（C-01） | 09/10 | 检查 `query` 是否声明 |

### 7.3 学习层验收

- [ ] 能解释「静默失败」为什么比报错更难查。
- [ ] 能写出条件边三参数。
- [ ] 能说出 08（字典）与 09（列表）在第二次 invoke 后的差异。
- [ ] 能说出 10 篇并行分支的屏障语义。

---

## 8. 已知缺口与后续改进（Gap Analysis）

| 编号 | 等级 | 缺口 | 影响 | 建议改进 | 对照章节 |
|---|---|---|---|---|---|
| G-01 | 🔴 | 失败信号用**字符串精确匹配**（06/07 篇） | 信号被加工后降级链断裂（06 已现，07 靠运气） | 用结构化 `status` 字段（如 `{"status":"failed"}`） | — |
| G-02 | 🟠 | **并行分支写同一键的 reducer 未定义**（10 篇） | 若 B/C 写同一键会报错或结果不确定 | 显式定义 `Annotated[list, operator.add]` 等 reducer | — |
| G-03 | 🟠 | `messages` **只增不减**（09/10 篇） | 长跑内存膨胀 | 加队列容量上限 / 定期清理 | chapter12 |
| G-04 | 🟠 | 外部存储是**模块级全局**（08/09/10） | 多会话/并发 invoke 互相污染 | 按 session_id 分片 / 改为请求级对象 | chapter12 |
| G-05 | 🟠 | 条件边**映射表需覆盖全部返回值** | 遗漏值 → LangGraph 运行时报错 | 加 `default` 分支处理未知路由值 | — |
| G-06 | 🟠 | `retrieve_node` 用**字典精确匹配**（05/08/09） | 轻微措辞变化即 miss | 改为关键词包含 / 模糊匹配 | chapter06（向量检索） |
| G-07 | 🟠 | `broadcast` = **循环单播**（10 篇） | N 个订阅者存 N 份副本，浪费内存 | 改为「一份消息 + 订阅者索引」 | — |
| G-08 | 🟠 | 关键词提取**按空格分词**（06/07 篇） | 对中文无效（中文无空格） | 接入中文分词（jieba）或 LLM 抽关键词 | — |
| G-09 | 🟠 | 全章**无异常处理**（节点内） | 节点抛异常会中断整个图 | 节点内 try/except + 失败写状态 | chapter12/13 |
| G-10 | 🟡 | `filter_node` 用 **set 去重打乱顺序**（06 篇） | 结果顺序不确定 | 用 `dict.fromkeys` 保序去重 | — |
| G-11 | 🟡 | `preprocess_node` **覆盖 `query` 原值**（05 篇） | 丢失原始输入 | 用新键 `normalized_query` | — |
| G-12 | 🟡 | 08 篇 `context_store` **无清理** | key 固定但语义混淆（新旧数据混合） | 加 session 前缀或定期清理 | — |
| G-13 | 🟡 | 10 篇 `agent_d_node` **无结果去重** | 重复任务在结论中重复出现 | 汇总前去重 | — |
| G-14 | 🟡 | 使用旧的 `set_entry_point` API | 新版推荐 `add_edge(START, ...)` | 迁移到新 API | — |
| G-15 | 🟡 | 全章**无日志/可观测** | 无法追踪节点执行 | 加 logging / 回调 | chapter12 |

### 缺口优先级建议

- **P0（正确性）**：G-01（失败信号）、G-02（reducer）
- **P1（健壮性）**：G-03、G-04、G-05、G-09
- **P2（质量）**：G-06、G-07、G-08
- **P3（整洁）**：G-10~G-15

---

## 附录 A：LangGraph 标准骨架（全章共用）

```python
from typing import TypedDict
from langgraph.graph import StateGraph, END

# ① State：必须 TypedDict + 字段注解（含全部入口键）
class State(TypedDict):
    query: str
    result: str

# ② 节点：读整个 state，返回「部分更新」dict
def my_node(state: State):
    return {"result": f"处理 {state.get('query','')}"}

# ③ 建图
builder = StateGraph(State)
builder.add_node("my", my_node)
builder.set_entry_point("my")          # 或 add_edge(START, "my")
builder.add_edge("my", END)
graph = builder.compile()

# ④ 执行
print(graph.invoke({"query": "hello"}))
```

## 附录 B：图的四种结构（本章演进路径）

| 结构 | 篇 | 图示 |
|---|---|---|
| 线性 2 节点 | 01 | `A → B` |
| 条件分支 | 02 | `check →(route)→ fast/normal` |
| 线性 4~5 节点 | 05/06/07 | `A → B → C → D (→ E)` |
| 并行扇出-汇聚 | 10 | `A → {B, C} → D` |

## 附录 C：「静默失败」三连（本章最深刻的教训）

| 现象 | 原因 | 篇 |
|---|---|---|
| `invoke` 返回 **None** | `State` 无字段注解，schema 为空 | 01~08 |
| **入口键被裁剪**（数据悄悄丢） | 字段注解漏声明入口键（如 `query`） | 09（实测）/10 |
| **ID 被覆盖**（旧数据消失） | 外部字典 key 固定 | 08 |

**共同点**：**都不报错**。这就是本章反复强调的核心教训——**没有错误信号 ≠ 没有错误**。

## 附录 D：外部存储 vs 图状态

| 维度 | 图状态 `State` | 外部存储（`mcp` / `a2a` / `hub`） |
|---|---|---|
| 生命周期 | 每次 invoke 重置 | 进程存活期间持续 |
| 第二次 invoke | 全新状态 | **08 字典：覆盖 / 09·10 列表：累积** |
| 生产对应 | 请求级上下文 | Redis / DB / 文件 |
| 教学价值 | 「图内怎么传数据」 | 「跨请求怎么留痕」 |

## 附录 E：教材「名不副实」概念对照

| 教材命名 | 实际是什么 | 真实协议是什么 | 篇 |
|---|---|---|---|
| `MCPInterface` | 内存字典存取类 | MCP：JSON-RPC + tools/resources/prompts，走 `langchain-mcp-adapters` | 08 |
| `A2AProtocol` | 同进程消息列表 | A2A：Agent Card/Task/Message，JSON-RPC over HTTP | 09 |
| 「函数调用工具」 | 节点**手动调用**的工具对象 | Function Calling：模型**自主决策**调用 | 04 |
