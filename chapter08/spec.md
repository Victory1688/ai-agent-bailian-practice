# 第 8 章 规范说明书（spec.md）——单智能体系统实战：五大能力集成

> **SDD 定位**：本文回答 *「把前七章的零件组装成一个能用的单 Agent，需要补哪些能力」*。
> **上篇（意图与学习路径）**回答 *为什么学、学什么、怎么学*；
> **下篇（契约与验收）**回答 *每个文件到底承诺了什么、怎么验证、还缺什么*。
> **主线**：char07 是「**数据层**」（上下文的表示/存储/筛选），char08 是「**控制层**」（Agent 的生命周期/输入/故障/记忆/预算）。
> 前七章都在教**零件**，本章教**组装**。五个例子各补一种能力，合起来就是一个生产级单 Agent 的完整能力面：
> **听懂（02）→ 记住（04）→ 精打细算（05）→ 扛住故障（03）→ 全程可观测（01）**。
>
> 适用范围：`D:/AiWorkOut/aiAgentCode/chapter08/`（5 个 .py / 638 行）。
> 契约字段一律**从代码事实反推**，不臆造；教材简化点与实测踩坑一并留痕。

---

# 上篇：意图与学习路径

## 1. 章意图（Why）

### 1.1 教材原版想解决什么

教材用一章讲「单智能体系统构建」，用五个例子各补一种能力，回答五个工程问题：

| 教材概念 | 想说明什么 | 补的能力 |
|---|---|---|
| 具备状态感知能力的单智能体 | 跟踪和控制智能体在执行任务过程中所处的**不同阶段**——长任务链、多轮会话、工具调用的稳定基石 | **状态机** |
| 输入参数解析与封装 | 模型生成的是**自然语言**，工具/API 需要的是**结构化参数**——解析器是连接二者的桥梁 | **输入规范化** |
| 工具异常处理机制 | 工具调用可能因网络/限流/参数/服务不可用失败，生产级系统必须**优雅降级** | **容错** |
| LangChain Memory 使用 | 标准化记忆管理接口，复用历史上下文，增强长期对话感知 | **记忆** |
| 上下文动态剪辑策略 | Token 窗口有上限，简单传递所有历史会**浪费 Token 在低价值内容上** | **预算管理** |

### 1.2 教材原版的三大断点

本章 5 个例子**全部无法直接运行**，卡在三处：

| 断点 | 涉及例子 | 具体表现 |
|---|---|---|
| 🔴 **虚构框架 `qwen_agent`** | 01-05 全部 | `from qwen_agent.agent import Agent` / `from qwen_agent.tools import Tool` / `from qwen_agent.context import Message` —— 该框架在真实环境不存在（char02 起已多次确认），`ImportError` |
| 🔴 **虚构 Tool 继承 + 虚构 Agent 实例化** | 01-05 全部 | `class XxxTool(Tool): super().__init__(name=..., description=...)` 与 `self.agent = Agent(tools=[...]); self.agent.chat(messages=[Message(...)])` |
| 🟠 **`langchain.memory` 路径已迁移（仅 04 篇）** | 04 | `from langchain.memory import ConversationBufferWindowMemory` → 1.3.18 中已移至 **`langchain_classic.memory`** |

**另外三个** 04 篇独有的教材缺陷：
- **三个死 import** —— `OpenAI` / `ConversationChain` / `messages_from_dict` / `messages_to_dict` **全部导入但从未使用**（教材模板残留）；
- **`FakeDataFetcher` 注册但从未调用** —— 初始化并注册给（虚构的）Agent，但 `ask()` 方法里从未显式调用 —— **char07-03/04 路由死代码谱系的延续**；
- **`chat_memory.messages` 是全量视图** —— 直接访问会**绕开 `k` 参数的窗口截断**（本章最重要的发现，见 F-04）。

### 1.3 本章改写要解决什么

| 教材原实现 | 改写后 | 教学点 |
|---|---|---|
| `from qwen_agent.agent import Agent` | `import dashscope` + `dashscope.Generation.call` | 唯一的真实 LLM 调用点变得可见 |
| `from qwen_agent.tools import Tool` | 删除 | — |
| `from qwen_agent.context import Message` | 删除（`messages=[{"role": "user", ...}]` 直接写） | Message 的真身就是 dict |
| `class XxxTool(Tool)` + `super().__init__(...)` | `class XxxTool:` + `self.name/description` 属性 | **最小改动**——类名与 `call()` 签名不变 |
| `self.agent = Agent(tools=tools)` | 删除（Agent 类内直接调 dashscope） | — |
| `self.agent.chat(messages=[Message(...)])` | `dashscope.Generation.call(model="qwen-plus", messages=[...], result_format='message')` | 参数语义一一对应 |
| `from langchain.memory import ConversationBufferWindowMemory` | `from langchain_classic.memory import ConversationBufferWindowMemory` | 1.x 路径迁移 |
| 三个死 import | **注释保留** + 标注「从未使用」 | 教材残留的诚实标注 |

**改写纪律**：本章是「**算法与结构优先**」的章节——所有**核心资产**原样保留：
`AgentState` 六态枚举 / `update_state` / `show_history` / `parse_input` / `print_parameters` / `RiskyEconomicTool` 的 `random` 失败模拟 / `RobustAgent` 的 `"[ERROR]" in tool_response` 降级判断 / `ask()` 四步循环 / `build_segment` 六字段 / `dynamic_clip_context` 贪心装填。

### 1.4 本章最该带走的三句话

1. **失败也是信息**——工具失败时返回 **`[ERROR]` 字符串**而非抛异常，让调用方可以做**分支决策**（走正常路径还是降级路径）。这是 char02 系列确立的惯例，在 03 篇被显式用于**优雅降级**。
2. **存储与视图必须分离**——`chat_memory` 是**全量存储**，`load_memory_variables()` 是**窗口视图**（**读时过滤**）。直接访问 `chat_memory.messages` 会**绕开 `k` 参数**，让窗口机制**静默失效**（04 篇最重要的陷阱）。
3. **上下文压缩有两个流派**——**规则窗口**（char07-07 `dynamic_merge_context`：按 `type` 分类筛选）vs **预算装填**（08-05 `dynamic_clip_context`：按 `priority` 排序 + `token_limit` 贪心装填）。**两者互补，不是替代关系**。

---

## 2. 学习路径（5 文件 / 638 行）

按「状态 → 输入 → 容错 → 记忆 → 预算」的五层顺序阅读：

| # | 文件 | 行数 | 核心机制 | 读完后你应能说出 |
|---|---|---|---|---|
| 01 | `01_具有状态感知的单Agent.py` | 147 | `AgentState` **六态枚举** + `execute()` 状态流转 + try/except 兜底 | 状态机是什么、为什么长任务链需要它 |
| 02 | `02_输入参数解析与封装Agent.py` | 127 | `parse_input` **三段式规则解析**（分词后缀 / 关键词包含 / if-elif 优先级） | NL → 结构化参数的最小实现与其盲区 |
| 03 | `03_具备异常处理能力的Agent.py` | 111 | `RiskyEconomicTool` 自捕获 + `"[ERROR]" in ...` **降级分支** | 优雅降级怎么做、为什么失败要返回字符串 |
| 04 | `04_langchain的Memory使用.py` | 136 | `ConversationBufferWindowMemory(k=3)` + `ask()` **四步循环** | 存储 vs 视图的区别、窗口截断在哪发生 |
| 05 | `05_自动裁剪上下文并重构提示词.py` | 117 | `build_segment` **六字段** + `dynamic_clip_context` **贪心装填** | Token 预算下怎么选信息 |

### 阅读路线建议

- **第一遍（状态机 1 篇）**：01。**先建骨架**——六态流转 + 历史留痕。这是「可观测的 Agent」的基础。
- **第二遍（输入层 1 篇）**：02。**再解决入口**——用户说的是自然语言，工具要的是结构化参数。
- **第三遍（容错层 1 篇）**：03。**再加保险**——工具会失败，Agent 不能崩。
- **第四遍（记忆层 1 篇）**：04。**再加记忆**——但要注意这里有个**经典陷阱**。
- **第五遍（预算层 1 篇）**：05。**最后算账**——Token 有限，怎么装最有价值的信息。
- **关键呼应**：
  - **五层是「能力叠加」而非「调用依赖」**——任何一层都可以单独拿出来用在别的 Agent 上。
  - **01 与 03 的 `FAILED` 状态呼应**——03 的降级路径本质是「避免进入 `FAILED`」。
  - **04 与 05 都在讲「历史太长怎么办」**——04 是**存储侧的窗口**，05 是**装填侧的预算**。
  - **04 篇与 char04-03 是同一机制的手写版 vs 框架版**。

---

## 3. 四条工程主线（本章反复出现的设计决策）

### 主线一：失败也是信息（03 篇的核心设计）

```python
# 工具内部自捕获异常——永不向上抛，失败也返回字符串
try:
    ...
except Exception as e:
    return f"[ERROR] 工具执行失败：{str(e)}"
```
```python
# 调用方用【子串匹配】判断走哪条路
if "[ERROR]" in tool_response:
    prompt = f"注意：外部工具调用失败，请直接基于常识与历史数据，预测{region}在2026年的经济走势..."
else:
    prompt = f"根据以下数据生成经济分析总结：\n工具输出：{tool_response}..."
```

**三条设计契约**：
| 决策 | 好处 | 代价 |
|---|---|---|
| 工具**永不抛异常** | 上层不会被中断 | 异常信息被降级为字符串（丢失栈信息） |
| 失败信号是 **`[ERROR]` 子串** | 简单、零依赖 | **魔法值**——脆弱的字符串契约（见缺口 G-02） |
| 降级走**另一条 prompt** | 用户体验不断（有回答） | **风格漂移**（正常/降级两条 prompt 措辞不同，回答风格跳变） |

### 主线二：状态变更必须留痕（01 篇）

```python
def update_state(self, new_state: AgentState):
    print(f"→ 状态变更：{self.state.value} → {new_state.value}")
    self.state = new_state
    self.history.append({
        "timestamp": time.time(),
        "task_id": self.task_id,
        "state": self.state.value
    })
```

**六态流转契约**：
```
INITIALIZED ──execute()──> READY ──> RUNNING ──> WAITING_TOOL ──> RUNNING ──> COMPLETED
                                                                      │
                                          （任意阶段异常）─────────────> FAILED
```

**核心认识**：**`timestamp` 是免费的性能探针**——时间戳链天然暴露「工具 `sleep(1)` 1 秒 + LLM 调用十几秒」的真实耗时分布。**生产系统的性能审计靠这种时间差定位瓶颈**（同 char07-05 的教训）。

### 主线三：存储与视图分离（04 篇最重要的陷阱）

| | `chat_memory` | `load_memory_variables({})['history']` |
|---|---|---|
| 性质 | **存储**（全量累积） | **视图**（窗口过滤） |
| 是否受 `k` 约束 | ❌ **不受** | ✅ 受（只保留最近 k 轮） |
| `return_messages=True` 时 | `.chat_memory.messages` 返回 `AIMessage`/`HumanMessage` 对象列表 | 同上但已截断 |

**🔴 教材陷阱（本章最重要发现）**：
```python
# ❌ 绕过窗口截断的写法（教材原写法）
history_str = "\n".join([f"{m.content}" for m in self.memory.chat_memory.messages])
# ✅ 正确写法（读时过滤）
history = self.memory.load_memory_variables({})["history"]
```

**修复前后实测对照**：
| | Round 4 时的 message 条数 |
|---|---|
| 修复前（直接读 `chat_memory.messages`） | **8 条**（4 user + 4 AI，**全量**） |
| 修复后（走 `load_memory_variables`） | **6 条**（3 user + 3 AI，**Round 1 被裁掉**） |

**为什么这样设计**：LangChain 的 Memory 采用「**存全量、取窗口**」——存储层不丢数据（便于审计/序列化），视图层做截断（保护 prompt 长度）。

### 主线四：字段设计跟着用途走（05 篇 vs char07-01）

| 篇 | 字段 | 差异 |
|---|---|---|
| char07-01 | `role` / `content` / `type` / `task_id` / `meta`（**5 字段**） | 通用最小集 |
| **08-05** | `role` / `content` / `type` / **`timestamp`** / **`priority`** / **`length`**（**6 字段**） | **砍掉 `task_id`/`meta`，新增 `timestamp`/`priority`/`length`** |

**为什么**：
- `priority` —— 贪心装填**要先按优先级排序**（`1 if segment_type == "system" else 0.5`）；
- `length` —— 装填**要有 Token 计量**（`len(content) // 2`，中文约 2 字符 = 1 token 的粗略估计）；
- `timestamp` —— 同优先级时**取最新的**（`-x["timestamp"]` 降序）；
- `task_id`/`meta` —— **装填算法用不上，删掉**。

---

## 4. 学习检查清单（读完自测）

- [ ] 能默写 `AgentState` 的六个状态与流转顺序（01）。
- [ ] 能说出「状态管理」解决什么工程问题（长任务链/多轮会话/异常恢复）。
- [ ] 能解释为什么 `update_state` 要记录 `timestamp`（01，性能探针）。
- [ ] 能默写 `parse_input` 的三条规则（年份分词 / 区域关键词 / 指标关键词）。
- [ ] 能说出 `parse_input` 的三条规则盲区（05 篇注释已点出，见 02 篇风险）。
- [ ] 能解释「为什么工具失败要返回 `[ERROR]` 字符串而不是抛异常」（03）。
- [ ] 能说出 `"[ERROR]" in tool_response` 这种判断方式的**两个缺点**。
- [ ] 能解释 `chat_memory.messages` 与 `load_memory_variables({})` 的**本质差异**（04）。
- [ ] 能说出 `k=3` 时 `chat_memory.messages` 在 Round 4 会有几条（**8 条，不是 6 条**）。
- [ ] 能说出 `ConversationBufferWindowMemory` 的「存全量、取窗口」设计动机。
- [ ] 能默写 `dynamic_clip_context` 的排序键与装填条件（05）。
- [ ] 能说出「规则窗口」（char07-07）与「预算装填」（08-05）两个压缩流派的差异。

---

# 下篇：契约与验收

## 5. 全局技术约束（C-xx）

### C-01 全章禁用虚构框架 `qwen_agent`

**约束**：不得出现 `from qwen_agent...` 的可执行 import；仅允许以注释形式保留（「原写法（注释保留）」区块）。
**验收**：grep `qwen_agent` 应只命中**注释块**。

### C-02 工具类一律改写为「纯类 + name/description 属性」

**统一写法**：
```python
class XxxTool:
    def __init__(self):
        # 原写法：super().__init__(name="xxx", description="...")
        self.name = "xxx"
        self.description = "..."
    def call(self, ...) -> str: ...
```
**约束**：**类名与 `call()` 签名保持不变**（最小改动原则）。
**实例对照**：

| 文件 | 类名 | `call()` 签名 |
|---|---|---|
| 01 | `ForecastTool` | `call(self, query: str) -> str` |
| 02 | `EconomicForecastTool` | ⚠️ **`call(self, params: Dict[str, Any]) -> str`** |
| 03 | `RiskyEconomicTool` | ⚠️ **`call(self, inputs: Dict[str, Any]) -> str`** |
| 04 | `FakeDataFetcher` | `call(self, query: str) -> str` |
| 05 | `EconomicSummaryTool` | `call(self, query: str) -> str` |

⚠️ **02/03 篇的 `call` 签名是 `Dict` 输入** —— 因为这两篇的主题就是「**结构化参数**」（02）与「**结构化输入**」（03）。改写时**必须保留签名**（C-05）。

### C-03 LLM 调用统一 `qwen-plus` + `result_format='message'`

**统一写法**：
```python
response = dashscope.Generation.call(
    model="qwen-plus",
    messages=[{"role": "user", "content": prompt}],
    temperature=0.3,
    max_tokens=512,
    result_format='message'
)
content = response.output.choices[0].message.content
```
**约束**：全章统一（`temperature=0.3`、`max_tokens=512`、`result_format='message'` 必填）。
**验收**：grep `result_format='message'` 命中 01/02/03/04/05 共 5 处。

### C-04 API Key 来自环境变量

```python
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key
```
**已知风险**：无空值校验（见缺口 G-01）。

### C-05 核心算法与数据结构骨架必须原样保留

**约束**：以下内容**逐字保留**，不得重构：

| 篇 | 必须保留 |
|---|---|
| 01 | `AgentState` 六态枚举 + `update_state`（含 `history.append`）+ `execute` 的六态流转序列 + `show_history` 的 `time.strftime` 格式化 |
| 02 | `parse_input` 的三段式规则（年份分词 / 区域 if-elif / 指标 if-elif）+ `print_parameters` |
| 03 | `RiskyEconomicTool.call` 的 try/except + `random.random() < 0.5` + `RobustAgent.process` 的 `"[ERROR]" in tool_response` 分支 + 两条 prompt 的原文 |
| 04 | `ConversationBufferWindowMemory(k=3, return_messages=True)` + `ask()` 四步循环 + 4 轮对话设计（**故意的**，让 Round 1 被裁掉） |
| 05 | `build_segment` 六字段 + `dynamic_clip_context` 的排序键与装填条件 |

### C-06 模拟工具与随机机制原样保留

**约束**：
- 01 篇 `ForecastTool.call` 的 `time.sleep(1)` 与硬编码 `5.2%` **保留**；
- 02 篇 `EconomicForecastTool.call` 的 `.get()` 默认值兜底与硬编码 `5.2%` **保留**；
- 03 篇 `RiskyEconomicTool` 的 **`random.random() < 0.5` 随机失败**必须保留（**教学核心：让降级路径可复现地被触发**）；
- 04 篇 `FakeDataFetcher` 的硬编码 `if/elif`（2025/2024/其他）**保留**；
- 05 篇 `EconomicSummaryTool.call` 硬编码字符串**保留**。

### C-07 04 篇 LangChain 路径必须迁移到 `langchain_classic`

**约束**：
```python
# 原写法：from langchain.memory import ConversationBufferWindowMemory
# 改写：langchain 1.3.18 中 memory 已移至 langchain_classic
from langchain_classic.memory import ConversationBufferWindowMemory
```
**验收**：grep `from langchain.memory` 只命中注释。

### C-08 死代码与死 import 必须保留 + 显式标注

**约束**：教材的「注册了但没调用」与「导入了但没用」必须在注释中**明确指认**，代码原样保留（**让新人看到真实后果**）。
**实例（04 篇）**：
```python
# 原写法（注释保留）：死 import
# from langchain.schema import messages_from_dict, messages_to_dict  ← 从未使用
# from langchain.llms import OpenAI                                 ← 从未使用
# from langchain.chains import ConversationChain                   ← 从未使用
```
```python
class FakeDataFetcher:
    """提供历史数据支持的模拟工具（改写：去掉虚构 Tool 继承）

    注意：本类虽然在 LangChainQwenAgent.__init__ 里被初始化，
    但 ask() 方法里从未显式调用它——这是教材模板的遗留问题，
    与 char07-03/04 的路由死代码是同一家族。
    保留原样是为了让新人看到"注册了工具但没调用"的真实后果。
    """
```

### C-09 每个文件头注释必须包含三要素

**约束**：头部注释块必须包含：
1. **教材概念**（含「为什么需要」的说明）；
2. **改写前的问题**（编号列出）；
3. **改写策略**（分条列出保留了什么、替换了什么）。

### C-10 「原写法（注释保留）」必须紧贴改写点

**约束**：每处改写都要在紧邻位置保留 `# 原写法：...`。

### C-11 实测发现写入注释（Memory 陷阱 / 降级命中 / 耗时）

**约束**：能实测验证的结论必须在注释中留痕。
**实例**：
- 04 篇：修复前后对照 —— 「Round 4 时原始存储 8 条 | 窗口视图 6 条（Round 1 被裁掉）」；
- 03 篇：降级路径 **3 次实测命中**；
- 01 篇：时间戳链暴露「工具 1s + LLM 13s」耗时。

### C-12 教材笔误如实标注（不修正内容）

**约束**：教材数据中的笔误必须**如实指认但保持原样**（不修改内容，只在注释中说明）。
**实例（05 篇）**：
```python
# 构建上下文段（原样保留——注意 2023/2025 段的内容与轮次错位，是教材的笔误）
context_pool.append(build_segment("user", "那2023年呢？", "input"))
context_pool.append(build_segment("assistant", "2025年为5.2%", "response"))   # ← 问的是 2023，答的是 2025
```

---

## 6. 逐文件契约（F-01 ~ F-05）

---

### F-01 `01_具有状态感知的单Agent.py`（147 行）——状态机篇

**意图**：回答「**怎么让 Agent 的执行过程可观测、可恢复**」——用**六态枚举**追踪每个阶段。

**状态定义契约（本篇核心教学资产，原样保留）**：
```python
class AgentState(Enum):
    INITIALIZED = "initialized"
    READY = "ready"
    RUNNING = "running"
    WAITING_TOOL = "waiting_tool"
    COMPLETED = "completed"
    FAILED = "failed"
```

**状态流转契约（`execute()` 内的完整序列）**：

| 序 | 动作 | 状态 |
|---|---|---|
| 0 | `__init__` | `INITIALIZED` |
| 1 | `execute()` 开始 | → `READY` |
| 2 | 拼完 `full_prompt` | → `RUNNING` |
| 3 | 工具调用前 | → `WAITING_TOOL` |
| 4 | 工具调用后 | → `RUNNING` |
| 5 | LLM 返回后 | → `COMPLETED` |
| — | **任意阶段异常** | → `FAILED` |

**`update_state` 契约（含留痕）**：
```python
def update_state(self, new_state: AgentState):
    """状态变更 + 记录历史（原样保留）"""
    print(f"→ 状态变更：{self.state.value} → {new_state.value}")
    self.state = new_state
    self.history.append({
        "timestamp": time.time(),
        "task_id": self.task_id,
        "state": self.state.value
    })
```

**`execute` 契约（含异常兜底）**：
```python
def execute(self, system_prompt: str, user_question: str) -> str:
    try:
        self.update_state(AgentState.READY)
        full_prompt = f"""【系统提示】\n{system_prompt}\n\n【用户提问】\n{user_question}\n\n请结合相关经济数据工具完成结构化分析。"""
        self.update_state(AgentState.RUNNING)
        self.update_state(AgentState.WAITING_TOOL)
        tool_result = self.tool.call(user_question)
        self.update_state(AgentState.RUNNING)
        merged_prompt = f"{full_prompt}\n【工具响应】\n{tool_result}\n请生成回答："
        response = dashscope.Generation.call(...)
        result_content = response.output.choices[0].message.content
        self.update_state(AgentState.COMPLETED)
        return result_content
    except Exception as e:
        self.update_state(AgentState.FAILED)
        return f"[ERROR] 任务执行失败：{str(e)}"
```

**工具契约（哑工具 + 模拟耗时）**：
```python
class ForecastTool:
    def call(self, query: str) -> str:
        print("→ 调用 DeepSeek-V1 工具进行预测...")
        time.sleep(1)                                    # 模拟耗时
        return f"[DeepSeek-V1] 预测结果：{query} 的增长预期为5.2%"
```

**`show_history` 契约**：
```python
def show_history(self):
    print("\n--- 状态变更日志 ---")
    for entry in self.history:
        t = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(entry["timestamp"]))
        print(f"{t} | 状态：{entry['state']}")
```

**验收标准**：
- V-01-A：打印 `=== 启动具备状态管理的智能体系统 ===` + `→ 调用 DeepSeek-V1 工具进行预测...`。
- V-01-B：打印 **6 条** `→ 状态变更：X → Y`（`initialized→ready` / `ready→running` / `running→waiting_tool` / `waiting_tool→running` / `running→completed`；**加上起始状态打印**）。
- V-01-C：`--- 模型响应输出 ---` 后输出基于工具结果的经济分析。
- V-01-D：`--- 状态变更日志 ---` 后输出每条 `YYYY-MM-DD HH:MM:SS | 状态：xxx`。
- V-01-E：**日志时间戳间隔可见**——工具阶段约 1 秒，LLM 阶段十几秒（**性能探针**）。

**已知风险 / 诚实标注**：
- ⚠️ **`FAILED` 分支难以自然触发** —— `ForecastTool` 与 `dashscope` 都很少失败，本地运行基本走完整路径（`FAILED` 分支是「可达但未达」的代码，需 monkeypatch 才能复现）。
- ⚠️ **`history` 只存内存** —— 进程结束即丢失（生产需持久化，对比 char07-05 的 JSONL）（见缺口 G-03）。
- ⚠️ **无「超时自动转 `FAILED`」** —— 若 `tool.call` 挂起，状态会**永久停在 `WAITING_TOOL`**（见缺口 G-04）。
- ⚠️ **`state` 用 `Enum` 但 `history` 里存的是 `.value` 字符串** —— 类型不一致（读取时需自己映射）。
- ⚠️ **`update_state` 无并发保护** —— 多线程环境下 `self.state` 与 `self.history` 会竞争（本章是单线程演示）。
- ⚠️ **`full_prompt` 拼了但工具结果又单独拼一次** —— `merged_prompt = f"{full_prompt}\n【工具响应】\n{tool_result}\n请生成回答："`（`full_prompt` 里其实没有工具信息，所以逻辑正确，但拼接层次略乱）。
- ⚠️ **`self.tool = tools[0]` 硬取第一个** —— 若传空列表会 `IndexError`（无校验）。

**教材问题（文件头注释实录）**：
> 什么是状态管理？跟踪和控制智能体在执行任务过程中所处的不同阶段。对于长任务链、多轮会话或工具调用，状态管理是实现稳定交互、任务全链路跟踪和异常快速恢复的核心基石。
> 智能体核心逻辑 (StatefulAgent)：核心 `execute` 方法串联起了完整的任务处理流程，配合 `update_state` 方法实时记录并打印状态变更。逻辑涵盖：初始化任务ID、状态流转控制、工具调用协同、异常捕获与失败处理。
> 改写前的问题：1) `qwen_agent.Agent/Message/Tool`——虚构框架；2) `ForecastTool`——模拟工具（返回假数据 + `time.sleep(1)` 模拟耗时），保持原样。
> **备注：本篇原代码无 redis 调用，无需按 cache.json 方案替换。**

---

### F-02 `02_输入参数解析与封装Agent.py`（127 行）——输入规范化篇

**意图**：回答「**怎么把自然语言变成工具能吃的结构化参数**」——`parse_input` 是 NL → 结构化参数的最小实现。

**工具契约（`Dict` 输入）**：
```python
class EconomicForecastTool:
    def call(self, params: Dict[str, Any]) -> str:
        # .get() 带默认值——参数缺失时的兜底（原样保留）
        region = params.get("region", "中国")
        year = params.get("year", 2026)
        focus = params.get("focus", "GDP")
        return f"[DeepSeek-V1] 预测结果：{region}在{year}年的{focus}增长率预计为5.2%"
```
**关键设计**：**`.get()` 带默认值** —— 参数缺失时**不报错，用兜底值**。这是「输入封装」的容错基础。

**`parse_input` 契约（本篇核心教学资产，原样保留）**：
```python
def parse_input(user_text: str) -> Dict[str, Any]:
    """简单的规则解析器：从文本中提取区域、年份和指标类型"""
    region = "中国"      # 默认
    year = 2026          # 默认
    focus = "GDP"        # 默认

    # 年份解析：按空格分词，找"数字+年"的 token
    for token in user_text.split():
        if token.endswith("年") and token[:-1].isdigit():
            year = int(token[:-1])

    # 区域解析：关键词优先级 美国 > 欧盟 > 默认中国
    if "美国" in user_text:
        region = "美国"
    elif "欧盟" in user_text:
        region = "欧盟"

    # 指标关键词：CPI > PMI > 默认GDP
    if "CPI" in user_text:
        focus = "CPI"
    elif "PMI" in user_text:
        focus = "PMI"

    return {"region": region, "year": year, "focus": focus}
```

**三条解析规则契约**：

| 字段 | 规则 | 实现 |
|---|---|---|
| `year` | **按空格分词，找「数字+年」的 token** | `token.endswith("年") and token[:-1].isdigit()` |
| `region` | **关键词包含**（`美国` > `欧盟` > 默认 `中国`） | `if "美国" in ... elif "欧盟" in ...` |
| `focus` | **关键词包含**（`CPI` > `PMI` > 默认 `GDP`） | `if "CPI" in ... elif "PMI" in ...` |

**主流程契约**：
```python
user_input = "请预测2026年美国的GDP增长趋势"
structured_params = parse_input(user_input)      # → {"region": "美国", "year": 2026, "focus": "GDP"}
print_parameters(structured_params)
tool_output = forecast_tool.call(structured_params)
# → "[DeepSeek-V1] 预测结果：美国在2026年的GDP增长率预计为5.2%"
```

**验收标准**：
- V-02-A：`=== 启动输入参数解析与封装系统 ===` + `--- 结构化参数 ---` 后输出三行 `region: 美国` / `year: 2026` / `focus: GDP`。
- V-02-B：`--- 工具输出结果 ---` 后输出 `[DeepSeek-V1] 预测结果：美国在2026年的GDP增长率预计为5.2%`。
- V-02-C：`--- Qwen3.0 输出结果 ---` 后输出政策分析师视角的解读。
- V-02-D：**`year` 解析成功**（`"2026年"` → `2026`，证明分词后缀规则生效）。

**已知风险 / 诚实标注（三条规则盲区）**：
- ⚠️ **盲区 1：相对时间无法解析** —— 「**明年**」「**后年**」没有数字 token → 回落到默认 `2026`（**用户说「明年」得到 2026，可能是错的**）。
- ⚠️ **盲区 2：多区域只能取优先级最高的一个** —— 「美国**和**欧盟」只会得到 `美国`（`if/elif` 结构**只返回一个值**，无多值支持）。
- ⚠️ **盲区 3：大小写敏感** —— `"cpi"`（小写）不匹配 `"CPI"` → 回落到 `GDP`（**无 `upper()` 归一化**）。
- ⚠️ **`year` 只取最后一个匹配** —— 若文本含多个「数字+年」（「2023年和2026年对比」），**循环会覆盖，返回最后一个**（无显式策略）。
- ⚠️ **无「解析置信度」** —— 无法知道结果是命中规则还是走了默认值（**默认值和真实提取无法区分**）（见缺口 G-05）。
- ⚠️ **规则硬编码** —— 加一个区域/指标就要改代码（对比 char07-04 的 `any()` 列表写法，可扩展性更差）。
- ⚠️ **`focus` 的关键词是大小写混排** —— `"CPI"`/`"PMI"` 大写，但用户可能输入 `"cpi"`。

**教材问题（文件头注释实录）**：
> 为什么需要参数解析？填补"人机"鸿沟——模型生成的是自然语言，而工具/API需要的是结构化参数。解析器就是连接二者的关键桥梁。
> 保障调用准确性——输入参数格式错误或缺失，会直接导致工具调用失败，或返回无意义的错误结果。
> 改写前的问题：1) `qwen_agent.Agent/Message/Tool`——虚构框架；2) `EconomicForecastTool`——模拟工具（返回假数据），保持原样。
> 【改写说明】`parse_input` 规则解析器 + `print_parameters` 原样保留（本篇核心教学资产：NL→结构化参数的最小实现）。

---

### F-03 `03_具备异常处理能力的Agent.py`（111 行）——容错降级篇

**意图**：回答「**工具失败了 Agent 怎么办**」——**优雅降级**：依赖不可用时仍提供基础服务，而不是直接崩掉。

**🔴 工具契约（带随机失败，本篇教学核心）**：
```python
class RiskyEconomicTool:
    def call(self, inputs: Dict[str, Any]) -> str:
        # 工具内部自捕获异常——永不向上抛，失败也返回字符串（char02 惯例）
        try:
            region = inputs.get("region")
            if not region:
                raise ValueError("缺少region字段")

            # 模拟远程调用失败（50% 概率，原样保留——教学核心）
            if random.random() < 0.5:
                raise ConnectionError("远程API调用失败：连接超时")

            return f"[DeepSeek-V1] 预测：{region} 2026年GDP增长预计为5.3%"

        except Exception as e:
            return f"[ERROR] 工具执行失败：{str(e)}"
```

**为什么保留 `random` 失败**：**让降级路径可复现地被触发**（约 50% 概率）——这是「教学上可验证」的关键设计。若工具永远成功，降级分支就是死代码。

**`RobustAgent.process` 契约（降级分支，本篇核心）**：
```python
def process(self, user_input: str) -> str:
    region = "美国" if "美国" in user_input else "中国"     # 极简参数提取（02 篇 parse_input 的简化版）

    tool_response = self.tool.call({"region": region})
    print(f"\n→ 工具返回结果：{tool_response}")

    if "[ERROR]" in tool_response:
        # 降级逻辑（原样保留——本篇核心教学资产）
        print("→ 进入降级流程，切换为模型直接生成")
        prompt = f"""注意：外部工具调用失败，请直接基于常识与历史数据，预测{region}在2026年的经济走势，并给出简明解释。"""
    else:
        # 正常逻辑（原样保留）
        prompt = f"""根据以下数据生成经济分析总结：
工具输出：{tool_response}
分析要求：语言简洁、观点明确、适合决策参考"""

    response = dashscope.Generation.call(model="qwen-plus", messages=[{"role": "user", "content": prompt}], ...)
    return response.output.choices[0].message.content
```

**两条路径的 prompt 契约对照**：

| 路径 | 触发条件 | prompt 内容 | 风格走向 |
|---|---|---|---|
| **正常** | `"[ERROR]" not in tool_response` | `"根据以下数据生成经济分析总结：\n工具输出：{...}\n分析要求：语言简洁、观点明确、适合决策参考"` | **数据驱动**——基于工具输出 |
| **降级** | `"[ERROR]" in tool_response` | `"注意：外部工具调用失败，请直接基于常识与历史数据，预测{region}在2026年的经济走势，并给出简明解释。"` | **常识驱动**——无数据支撑 |

**验收标准**：
- V-03-A：`=== 启动带异常处理的Agent系统 ===` + `→ 工具返回结果：...`（可能是正常数据或 `[ERROR]`）。
- V-03-B：**50% 概率出现 `→ 进入降级流程，切换为模型直接生成`**（多次运行必能观察到）。
- V-03-C：`--- Qwen3.0 最终输出 ---` 后输出分析（**两条路径都有输出**）。
- V-03-D：**无论哪条路径，脚本都不崩溃**（异常被完整封装）。
- V-03-E：正常路径输出含工具数据（`5.3%`）；降级路径输出不含（模型自己估）。

**已知风险 / 诚实标注（本篇最有价值的教学发现）**：
- 🔴 **降级 prompt 的风格漂移** —— 正常路径要求「**语言简洁**」，降级路径要求「**给出简明解释**」。**实测降级回答更长更结构化**，用户体验**明显跳变**（见缺口 G-06）。
- 🔴 **LLM 会主动质疑假数据** —— 工具返回硬编码 `5.3%`，`qwen-plus` **实测会主动指出「显著高于历史趋势和主流机构预期」**。**但数据质量必须从源头保证，不能指望下游 LLM 兜底**（见缺口 G-07）。
- ⚠️ **`"[ERROR]"` 是魔法值** —— 字符串契约脆弱：若工具返回内容里**恰好含 `[ERROR]`**（如文档提到这个词），会**误判为失败**。生产应用**结构化 `status` 字段**（对比 char05 的结论字段）（见缺口 G-02）。
- ⚠️ **`region` 提取极简** —— 只有「美国 / 其他」两分支（比 02 篇的 `parse_input` 更简陋）。
- ⚠️ **无重试机制** —— 失败直接降级，没有 L1 重试（生产应「重试 → 降级 → 熔断」三层）。
- ⚠️ **异常信息被降级为字符串** —— `str(e)` 丢失栈信息（调试价值下降）。
- ⚠️ **`random` 无种子** —— 结果不可复现（教学上需要「多次运行观察」，但无法「一次运行必现」）。

**教材问题（文件头注释实录）**：
> 为什么需要异常处理？现实世界的不确定性——工具调用可能因网络波动、API调用限制、参数传递错误或外部服务不可用等原因失败，是无法完全避免的。
> 系统健壮性 (Robustness)——一个生产级的智能体系统，必须具备"优雅降级"的能力，在依赖的工具不可用时，依然能提供基础的服务，而不是直接抛出错误导致整个流程崩溃。
> 改写前的问题：1) `qwen_agent.Agent/Message/Tool`——虚构框架；2) `RiskyEconomicTool`——模拟工具（random 50% 失败 + 假数据），**随机机制原样保留**（随机失败正是本篇教学重点：让降级路径可复现地被触发）。
> 【改写说明】`RiskyEconomicTool` 的 try/except + random 失败模拟原样保留（教学核心）；`RobustAgent` 的降级分支判断（`"[ERROR]" in tool_response`）原样保留。

---

### F-04 `04_langchain的Memory使用.py`（136 行）——记忆篇（最重要陷阱）

**意图**：回答「**怎么用框架托管记忆**」——`ConversationBufferWindowMemory(k=3)` 只保留最近 3 轮。

**导入契约（1.x 路径迁移）**：
```python
from langchain_classic.memory import ConversationBufferWindowMemory
# 原写法：from langchain.memory import ConversationBufferWindowMemory
# 改写：langchain 1.3.18 中 memory 已移至 langchain_classic
```

**🔴 死 import 契约（教材残留，必须标注）**：
```python
# 原写法（注释保留）：死 import
# from langchain.memory import ConversationBufferWindowMemory
# from langchain.schema import messages_from_dict, messages_to_dict  ← 从未使用
# from langchain.llms import OpenAI                                 ← 从未使用
# from langchain.chains import ConversationChain                   ← 从未使用
```

**Memory 配置契约（原样保留）**：
```python
# k=3 表示只保留最近 3 轮对话（6 条 message：3 user + 3 AI）
# return_messages=True 让 .chat_memory.messages 返回 AIMessage/HumanMessage 对象列表
memory = ConversationBufferWindowMemory(k=3, return_messages=True)
```

**🔴 死代码契约（`FakeDataFetcher` 注册但从未调用）**：
```python
class FakeDataFetcher:
    """提供历史数据支持的模拟工具（改写：去掉虚构 Tool 继承）

    注意：本类虽然在 LangChainQwenAgent.__init__ 里被初始化，
    但 ask() 方法里从未显式调用它——这是教材模板的遗留问题，
    与 char07-03/04 的路由死代码是同一家族。
    保留原样是为了让新人看到"注册了工具但没调用"的真实后果。
    """
    def call(self, query: str) -> str:
        if "2025" in query: return "2025年GDP增长率为5.2%，主要受益于消费回暖和出口恢复"
        elif "2024" in query: return "2024年GDP增长为3.0%，疫情影响下内需低迷"
        else: return "暂无相关数据"
```

**`ask()` 四步循环契约（本篇核心）**：
```python
def ask(self, user_input: str) -> str:
    """四步循环：历史注入 → LLM → 回写 memory（原样保留）"""
    # Step 1: 历史注入——从 memory.chat_memory.messages 取最近 k 轮
    history_str = "\n".join([f"{m.content}" for m in self.memory.chat_memory.messages])
    full_prompt = f"""以下是最近对话历史：\n{history_str}\n\n用户现在的问题是：\n{user_input}\n\n请结合历史与知识进行回答："""

    # Step 2: 调 Qwen 生成响应
    response = dashscope.Generation.call(model="qwen-plus", messages=[{"role": "user", "content": full_prompt}], ...)
    result_content = response.output.choices[0].message.content

    # Step 3: 回写 memory——LangChain 的 BufferWindowMemory 自动做窗口截断
    self.memory.chat_memory.add_user_message(user_input)
    self.memory.chat_memory.add_ai_message(result_content)

    # Step 4: 调试打印——当前 memory 里存了几条 message
    msg_count = len(self.memory.chat_memory.messages)
    print(f"  [Memory] 当前存储 {msg_count} 条 message（k=3 窗口上限 6 条）")
    return result_content
```

**🔴 教材陷阱契约（本章最重要发现）**：

Step 1 的 `self.memory.chat_memory.messages` 是**全量累积视图**，**直接访问 = `k` 参数失效**。窗口截断只在 **`load_memory_variables({})['history']`** 发生（**读时过滤**设计）。

| | 性质 | 是否受 `k` 约束 |
|---|---|---|
| `chat_memory.messages` | **存储**（全量累积） | ❌ **不受** |
| `load_memory_variables({})["history"]` | **视图**（窗口过滤） | ✅ 受（最近 k 轮） |

**实测对照**：

| | Round 4 时的 message 条数 |
|---|---|
| 直接读 `chat_memory.messages` | **8 条**（4 user + 4 AI，**全量**） |
| 走 `load_memory_variables` | **6 条**（3 user + 3 AI，**Round 1 被裁掉**） |

**4 轮对话契约（设计是故意的）**：
```python
# 4 轮对话设计是故意的——k=3 窗口意味着 Round 4 时 Round 1 应被裁掉
bot.ask("2024年GDP是多少？")        # Round 1
bot.ask("那2025年呢？")             # Round 2
bot.ask("你觉得2026年增长是否会更快？")  # Round 3
bot.ask("依据是什么？")              # Round 4
```

**验收标准**：
- V-04-A：`=== 启动结合LangChain记忆机制的智能体 ===` + 4 组 `[Round N] 用户提问：...` + 回答。
- V-04-B：每轮后打印 `[Memory] 当前存储 N 条 message（k=3 窗口上限 6 条）`。
- V-04-C：**N 的序列为 2 → 4 → 6 → 8**（**全量增长，不受 `k` 约束** —— 这是陷阱的直接证据）。
- V-04-D：Round 2 「那2025年呢？」回答**连贯**（知道在问 GDP）。
- V-04-E：`FakeDataFetcher` **被初始化但从未被调用**（无 `data_fetch` 相关输出）。

**已知风险 / 诚实标注**：
- 🔴 **`chat_memory.messages` 绕开窗口截断** —— **本章最重要的陷阱**。表现为「`k=3` 设了，但历史越来越长」，**prompt 持续膨胀直至超模型上下文**（见缺口 G-08）。
- 🔴 **`FakeDataFetcher` 是纯摆设** —— 初始化 + 注册，但 `ask()` 从不调用（**死代码谱系第三线**，前两线是 char07-03 的 `tool` 分支与 char07-04 的 `hybrid` 分支）。
- 🔴 **三个死 import** —— `OpenAI` / `ConversationChain` / `messages_from_dict` / `messages_to_dict`（教材模板残留）。
- ⚠️ **`return_messages=True` 但只取 `m.content`** —— 丢掉了角色信息（`AIMessage`/`HumanMessage` 的类型），拼出来的 `history_str` **无法区分谁说的**（对比 05 篇的 `[ROLE-TYPE]` 前缀，见缺口 G-09）。
- ⚠️ **`memory` 是模块级全局变量** —— 多会话会串台（无 `session_id` 隔离）。
- ⚠️ **`ConversationBufferWindowMemory` 已在 LangChain 0.3.1 废弃** —— 新项目应用 **LangGraph checkpoint / Store API**（见缺口 G-10）。
- ⚠️ **Step 1 读的是「上一轮结束时」的历史** —— 本轮 `user_input` 在 Step 3 才写入（**逻辑正确但容易误解**：本轮的 `user_input` 出现在 `full_prompt` 的「用户现在的问题是」段落，而非 `history_str`）。
- ⚠️ **无 Token 计数** —— `k=3` 是**轮数**约束，不是 Token 约束（长回答时 3 轮也可能超限，对比 05 篇的 `length` 字段）。

**教材问题（文件头注释实录）**：
> 为什么需要 Memory？为大模型应用提供一套标准化的记忆管理接口，屏蔽底层存储细节，专注业务逻辑开发。无缝集成到智能体中，通过复用历史对话上下文，显著增强模型的长期对话感知能力。
> 常见的 Memory 类型：`ConversationBufferMemory`（全量存储，不截断）/ `ConversationSummaryMemory`（LLM 摘要压缩存储）/ `ConversationBufferWindowMemory`（窗口存储，只保留最近 k 轮，最常用）。
> 改写前的问题：1) `qwen_agent.Agent/Message/Tool`——虚构框架；2) `FakeDataFetcher`——模拟工具（硬编码 if/elif 假数据），保持原样；3) **三个死 import**：`OpenAI` / `ConversationChain` / `messages_from_dict` / `messages_to_dict` 全部导入但从未使用（教材模板残留）；4) `FakeDataFetcher` 虽然被初始化并注册给虚构 Agent，但 `ask()` 方法里从未显式调用——**这是 char07-03/04 路由死代码谱系的延续**。
> 【实测】修复后对照：Round 4 时原始存储 **8 条** | 窗口视图 **6 条**（Round 1 被裁掉）。

---

### F-05 `05_自动裁剪上下文并重构提示词.py`（117 行）——预算装填篇

**意图**：回答「**Token 有限时怎么装最有价值的信息**」——`dynamic_clip_context` 用 `priority` 排序 + `token_limit` 贪心装填。

**与 char07-07 的关系契约（重要认知，教材注释已点明）**：
> 07 篇 `dynamic_merge_context` 是「**按类型规则筛选**」（system 全留 → tool 最新 1 → 历史最近 4）；
> 本篇 `dynamic_clip_context` 是「**按 Token 预算装填**」（优先级排序 + 贪心装填）；
> **两者是上下文压缩的两个流派：规则窗口 vs 预算装填**，本篇显式引入了 `priority` 和 token 计量。

**对比契约表**：

| 维度 | char07-07 规则窗口 | 08-05 预算装填 |
|---|---|---|
| 筛选依据 | **`type`**（system/tool/input/response） | **`priority`** + `timestamp` |
| 装填依据 | **固定条数**（`[:4]`） | **Token 预算**（`token_limit`） |
| Token 意识 | ❌ 无 | ✅ 有（`length` 字段） |
| 装不下时 | 硬截断 `[:4]` | **跳过继续**（贪心，装到装不下为止） |
| 算法 | 分类 + 窗口 | 排序 + 贪心 |

**`build_segment` 六字段契约（原样保留）**：
```python
def build_segment(role: str, content: str, segment_type: str, timestamp=None) -> Dict:
    """构建六字段上下文段（与 char07-01 五字段相比：去掉 task_id/meta，新增 timestamp/priority/length）"""
    return {
        "role": role,
        "content": content,
        "type": segment_type,
        "timestamp": timestamp or time.time(),
        "priority": 1 if segment_type == "system" else 0.5,   # system 段优先级最高
        "length": len(content) // 2  # 模拟token数（中文约2字符=1token的粗略估计）
    }
```

**六字段语义契约**：

| 字段 | 值 | 用途 |
|---|---|---|
| `role` | `system` / `user` / `assistant` / `tool` | 标注前缀 |
| `content` | 正文 | 信息载体 |
| `type` | `system` / `input` / `response` / `tool` | 分类 |
| `timestamp` | `time.time()` | **同优先级时取最新** |
| `priority` | **`1`（system）或 `0.5`（其他）** | **排序主键** |
| `length` | **`len(content) // 2`** | **Token 计量（中文约 2 字符 = 1 token）** |

**`dynamic_clip_context` 契约（本篇核心教学资产，原样保留）**：
```python
def dynamic_clip_context(segments: List[Dict], token_limit=150) -> str:
    """贪心装填算法：按优先级与时间排序后，在 token 预算内尽量多装"""
    # 按优先级降序 + 时间戳降序排序（system 段优先，同优先级取最新的）
    segments.sort(key=lambda x: (-x["priority"], -x["timestamp"]))

    total = 0
    clipped = []
    for seg in segments:
        if total + seg["length"] <= token_limit:      # ← 装得下就装
            clipped.append(seg)
            total += seg["length"]
        # ← 装不下不算了？不——continue 到下一个（贪心跳过）

    # 构造Prompt（[ROLE-TYPE] 标注前缀，与 char07-07 同款）
    merged = ""
    for seg in clipped:
        merged += f"[{seg['role']}-{seg['type']}] {seg['content']}\n"
    return merged
```

**⚠️ 关键机制**：**装不下时是「跳过继续」而非「终止」** —— 这是**贪心（greedy）**而非**顺序（sequential）**截断。若长段装不下，会**试下一个更短的段**。

**排序键契约**：
```python
segments.sort(key=lambda x: (-x["priority"], -x["timestamp"]))
#                            ↑ 优先级降序        ↑ 时间戳降序（同优先级取最新）
```

**上下文池契约（9 段，含教材笔误）**：

| 序 | `role` | `type` | 内容 |
|---|---|---|---|
| 1 | `system` | `system` | `"你是资深经济顾问，语言需精准、简洁"` |
| 2 | `user` | `input` | `"2024年GDP是多少？"` |
| 3 | `assistant` | `response` | `"2024年增长为3.0%"` |
| 4 | `user` | `input` | `"那2023年呢？"` |
| 5 | `assistant` | `response` | `"2025年为5.2%"` | ⚠️ **教材笔误**：问 2023 答 2025 |
| 6 | `tool` | `tool` | `tool.call("2026年预测")` |
| 7 | `user` | `input` | `"2026年会不会更高？"` |
| 8 | `assistant` | `response` | `"预计增长可达5.4%"` |
| 9 | `user` | `input` | `"主要依据有哪些？"` |

**⚠️ 教材笔误契约（如实标注，不修改）**：
```python
# 构建上下文段（原样保留——注意 2023/2025 段的内容与轮次错位，是教材的笔误）
context_pool.append(build_segment("user", "那2023年呢？", "input"))
context_pool.append(build_segment("assistant", "2025年为5.2%", "response"))
```

**装填预算契约**：`token_limit=100`（**教学用的紧预算**，故意让部分段被挤出）。

**选取结果推演**：
- system 段（priority=1）**必然入选**；
- 其余段（priority=0.5）按 `timestamp` **降序**（最新的在前）：段 9 → 段 8 → 段 7 → 段 6 → 段 5 → 段 4 → 段 3 → 段 2；
- 在 `token_limit=100` 内**贪心装填**，装不下就跳过试下一个。

**验收标准**：
- V-05-A：`=== 启动具备上下文动态剪辑能力的Agent系统 ===` + `→ DeepSeek-V1` 相关输出（工具调用）。
- V-05-B：`--- 剪辑后上下文结构 ---` 输出**带 `[ROLE-TYPE]` 前缀**的段（如 `[system-system] 你是资深经济顾问...`）。
- V-05-C：**system 段必然在输出里**（priority=1 保底）。
- V-05-D：**部分段被挤出**（总 `length` 之和超过 100）。
- V-05-E：`--- Qwen3.0 响应输出 ---` 后输出基于剪辑后上下文的回答。
- V-05-F：**段 2/3（最早的对话）大概率被挤出**（时间戳最旧）。

**已知风险 / 诚实标注**：
- ⚠️ **`length` 是粗略估计** —— `len(content) // 2`（中文约 2 字符 = 1 token）**在不同 tokenizer 下误差可达 ±30%**（生产应用 `tiktoken`）（见缺口 G-11）。
- ⚠️ **`priority` 只有两档**（`1` / `0.5`）—— **无更细的权重分层**（如「当前问题」应高于「历史对话」）。
- ⚠️ **`segments.sort()` 原地修改入参** —— 调用方的列表被重排（**副作用**，工程上不推荐）（见缺口 G-12）。
- ⚠️ **贪心装填可能产生「语义跳跃」** —— 跳过中间段后，保留下来的段可能**语义不连贯**（如 system + 段 9 + 段 8，中间的 7/6 被挤掉）。
- ⚠️ **无「当前问题保底」** —— 最关键的「用户当前提问」（段 9）可能与 system 一起被留下，但也**可能因长度被挤出**（**无「最后一段必须保留」的约束**）。
- ⚠️ **`token_limit` 默认 150 但调用传 100** —— 默认值未被使用（同 char06-04 的 `max_len` 模式）。
- ⚠️ **无去重**（同 char07-07）。
- ⚠️ **`tool` 段也在 `priority=0.5` 池里** —— 与历史对话**同权重**（而 char07-07 把 tool 单独列为「留最新 1 条」）。

**教材问题（文件头注释实录）**：
> 为什么需要动态剪辑？1) **上下文长度限制**——大模型的输入窗口有固定的 Token 数量上限，无法一次性承载过长的历史对话或海量文档。2) **避免信息过载与浪费**——在长对话中简单传递所有历史信息，会消耗大量 Token 在低价值或不相关的内容上，降低模型推理效率。
> 【本篇与 char07-07 的关系（重要认知）】07 篇 `dynamic_merge_context` 是"按类型规则筛选"，本篇 `dynamic_clip_context` 是"按 Token 预算装填"，两者是上下文压缩的两个流派：**规则窗口 vs 预算装填**，本篇显式引入了 `priority` 和 token 计量。
> 改写前的问题：1) `qwen_agent.Agent/Message/Tool`——虚构框架；2) `EconomicSummaryTool`——模拟工具（返回假数据），保持原样。

---

## 7. 全章验收清单（V-01 ~ V-14）

### 7.1 运行层验收

| 编号 | 验收项 | 期望 |
|---|---|---|
| V-01 | `python 01_...py` | 六态流转打印 + 状态日志（时间戳间隔可见 1s / 十几秒） |
| V-02 | `python 02_...py` | 结构化参数 `美国 / 2026 / GDP` + 工具输出 + LLM 解读 |
| V-03 | `python 03_...py` | 工具结果 + **50% 概率降级路径** + 两条路径都不崩 |
| V-04 | `python 04_...py` | 4 轮对话 + **message 数 2→4→6→8**（窗口失效的证据） |
| V-05 | `python 05_...py` | 剪辑后上下文 + system 段保底 + 部分段被挤出 |

### 7.2 契约层验收

| 编号 | 契约 | 对应 | 验证方式 |
|---|---|---|---|
| V-06 | 无可执行 `from qwen_agent`（C-01） | 全章 | grep 只命中注释 |
| V-07 | 工具类均为纯类 + `name/description`（C-02） | 01-05 | grep `class XxxTool` |
| V-08 | LLM 调用均带 `result_format='message'`（C-03） | 01-05 | grep 命中 5 处 |
| V-09 | 每文件有 `os.environ.get('DASHSCOPE_API_KEY')`（C-04） | 01-05 | grep 命中 5 处 |
| V-10 | 骨架（AgentState/update_state/parse_input/dynamic_clip_context 等）完整（C-05） | 01/02/03/04/05 | grep 关键词 |
| V-11 | 04 篇无 `from langchain.memory`（C-07） | 04 | grep 只命中注释 |
| V-12 | 死代码/死 import 已标注（C-08） | 04 | grep 「从未使用」/「从未显式调用」 |
| V-13 | 每个文件头含「改写前的问题」+「改写策略」（C-09） | 全章 | grep 关键词 |
| V-14 | 教材笔误已如实标注但保留原样（C-12） | 05 | grep 「教材的笔误」 |

### 7.3 学习层验收

- [ ] 能默写 `AgentState` 六态与流转序列。
- [ ] 能说出状态管理解决什么工程问题。
- [ ] 能解释「`timestamp` 是免费的性能探针」。
- [ ] 能默写 `parse_input` 三条规则。
- [ ] 能说出 `parse_input` 的三条规则盲区（相对时间 / 多区域 / 大小写）。
- [ ] 能解释「为什么工具失败返回 `[ERROR]` 字符串而不是抛异常」。
- [ ] 能说出 `"[ERROR]" in ...` 判断方式的两个缺点。
- [ ] 能解释 `chat_memory.messages` 与 `load_memory_variables({})` 的本质差异。
- [ ] 能预测 `k=3` 时 Round 4 的 `chat_memory.messages` 有几条（**8 条**）。
- [ ] 能说出「存全量、取窗口」的设计动机。
- [ ] 能默写 `dynamic_clip_context` 的排序键与装填条件。
- [ ] 能说出「规则窗口」与「预算装填」两个流派的核心差异。

---

## 8. 已知缺口与后续改进（Gap Analysis）

| 编号 | 等级 | 缺口 | 影响 | 建议改进 | 对照章节 |
|---|---|---|---|---|---|
| G-01 | 🟠 | 全章 `os.environ.get('DASHSCOPE_API_KEY')` **无空值校验** | key 未设时报错晦涩 | 启动时校验并友好提示 | chapter12 |
| G-02 | 🔴 | 03 篇 **`"[ERROR]"` 是魔法值**（子串匹配的字符串契约） | 内容含 `[ERROR]` 会误判为失败 | 改用**结构化 `status` 字段** | chapter05（结论字段） |
| G-03 | 🟠 | 01 篇 `history` **只存内存** | 进程结束丢失，无审计能力 | 持久化（JSONL / 数据库） | chapter07-05 |
| G-04 | 🟠 | 01 篇**无「超时自动转 FAILED」** | 工具挂起 → 状态永久停在 `WAITING_TOOL` | 加超时看门狗 | — |
| G-05 | 🟠 | 02 篇**无「解析置信度」** | 默认值与真实提取无法区分 | 返回 `(params, confidence)` 或标记来源 | — |
| G-06 | 🟠 | 03 篇**降级 prompt 风格漂移**（正常「语言简洁」vs 降级「简明解释」） | 用户体验跳变（降级回答更长） | 两条 prompt 统一风格约束 + 加降级标识 | — |
| G-07 | 🟠 | 03 篇**依赖 LLM 质疑假数据** | 数据质量问题被下游掩盖 | 数据源加校验（不指望 LLM 兜底） | chapter08-03 自身 |
| G-08 | 🔴 | 04 篇 **`chat_memory.messages` 绕开窗口截断** | `k` 参数静默失效，prompt 持续膨胀 | 走 `load_memory_variables({})` | — |
| G-09 | 🟠 | 04 篇 `history_str` **丢失角色信息**（只取 `m.content`） | LLM 无法区分谁说的话 | 加 `[ROLE]` 前缀（如 05 篇） | chapter07-02/07 |
| G-10 | 🟠 | 04 篇 **`ConversationBufferWindowMemory` 已废弃**（0.3.1 起） | 未来不兼容 | 迁移 **LangGraph checkpoint / Store API** | chapter05 |
| G-11 | 🟠 | 05 篇 **`length = len(content) // 2` 是粗略估计** | Token 误差可达 ±30% | 用 `tiktoken` 真实计数 | — |
| G-12 | 🟠 | 05 篇 `segments.sort()` **原地修改入参** | 调用方列表被重排（副作用） | `sorted(segments, key=...)` | — |
| G-13 | 🟠 | 05 篇**无「当前问题保底」** | 用户当前提问可能被挤出 | 为 `input` 段加保底优先级 | — |
| G-14 | 🟠 | 03 篇**无重试机制** | 失败直接降级 | 加 L1 重试 → L2 降级 → L3 熔断 | — |
| G-15 | 🟡 | 01 篇 `state`（Enum）与 `history`（字符串）**类型不一致** | 读取需手动映射 | 统一存储类型 | — |
| G-16 | 🟡 | 02 篇 `year` **多匹配时取最后一个**（无策略） | 「2023和2026对比」结果不确定 | 显式定义取值策略 | — |
| G-17 | 🟡 | 全章**无并发保护**（`state`/`history`/`memory`） | 多线程会竞争 | 加锁或改单线程队列 | chapter09-07 |
| G-18 | 🟡 | 04 篇 `memory` 是**模块级全局变量** | 多会话串台 | 按 `session_id` 分桶 | chapter09-06 |
| G-19 | 🟡 | 05 篇 `token_limit` **默认 150 但传 100** | 默认值未使用 | 统一或去掉默认 | — |
| G-20 | 🟡 | 全章**无日志框架**（全用 `print`） | 无法控制级别 | 引入 `logging` | — |
| G-21 | 🟡 | 五篇**各自独立** | 无法体现「集成」 | 合并为一个 `StatefulSmartAgent` 类 | 毕业设计建议 |

### 缺口优先级建议

- **P0（正确性）**：G-02（魔法值）、G-08（窗口静默失效）
- **P1（体验与质量）**：G-06（风格漂移）、G-07（依赖 LLM 兜底）、G-09（丢角色）、G-13（提问被挤出）
- **P2（健壮性）**：G-01、G-03、G-04、G-05、G-10、G-11、G-12、G-14
- **P3（整洁与迁移）**：G-15、G-16、G-17、G-18、G-19、G-20、G-21

---

## 附录 A：状态机流转图（01 篇）

```
                    ┌─────────────────────┐
                    │   INITIALIZED       │  __init__
                    └──────────┬──────────┘
                               │ execute() 开始
                    ┌──────────▼──────────┐
                    │   READY             │
                    └──────────┬──────────┘
                               │ 拼完 full_prompt
                    ┌──────────▼──────────┐
                    │   RUNNING           │
                    └──────────┬──────────┘
                               │ 准备调工具
                    ┌──────────▼──────────┐
                    │   WAITING_TOOL      │◄── 工具耗时（timestamp 探针）
                    └──────────┬──────────┘
                               │ 工具返回
                    ┌──────────▼──────────┐
                    │   RUNNING           │
                    └──────────┬──────────┘
                               │ LLM 返回
                    ┌──────────▼──────────┐
                    │   COMPLETED         │
                    └─────────────────────┘

    任意阶段异常 ──────────────────────► FAILED
```

## 附录 B：Memory 存储与视图对照（04 篇）

```python
memory = ConversationBufferWindowMemory(k=3, return_messages=True)

# ❌ 全量存储视图（绕开 k 约束）
len(memory.chat_memory.messages)                 # Round 4 → 8 条

# ✅ 窗口视图（读时过滤）
history = memory.load_memory_variables({})["history"]
len(history)                                     # Round 4 → 6 条
```

| 访问路径 | 性质 | 受 `k` 约束 | Round 4 条数 |
|---|---|---|---|
| `chat_memory.messages` | 存储 | ❌ | **8** |
| `load_memory_variables({})["history"]` | 视图 | ✅ | **6** |

**设计动机**：**存储层不丢数据**（便于审计/序列化），**视图层做截断**（保护 prompt 长度）。

## 附录 C：上下文压缩两个流派对照（char07-07 vs 08-05）

| 维度 | char07-07 `dynamic_merge_context` | 08-05 `dynamic_clip_context` |
|---|---|---|
| 流派 | **规则窗口** | **预算装填** |
| 筛选依据 | `type`（system / tool / input / response） | `priority` + `timestamp` |
| 装填依据 | 固定条数（`[:4]`） | **Token 预算**（`token_limit`） |
| Token 意识 | ❌ | ✅（`length` 字段） |
| 装不下时 | 硬截断 | **跳过继续**（贪心） |
| system 段 | 全保留 | 全保留（`priority=1`） |
| tool 段 | 单独留最新 1 条 | 与历史同权重（`0.5`） |
| 算法复杂度 | O(n) | O(n log n)（排序） |

**结论**：**两者互补，不是替代关系**。生产实践一般**先规则粗筛（07），再预算精装（08）**。

## 附录 D：四条不变式

| # | 不变式 | 内容 | 实证 |
|---|---|---|---|
| 1 | **失败也是信息** | 工具失败返回 `[ERROR]` 字符串而非抛异常，让上层做分支决策 | 03 篇降级路径 3 次实测命中 |
| 2 | **状态变更必须留痕** | 每次 `update_state` 都记 `timestamp` + 状态值 | 01 篇时间戳链暴露工具 1s + LLM 十几秒 |
| 3 | **存储与视图分离** | `chat_memory` 全量存储 / `load_memory_variables` 窗口视图（读时过滤） | 04 篇 bug 修复前后对照：8 条 vs 6 条 |
| 4 | **字段设计跟着用途走** | 本篇 `build_segment` 砍 `task_id`/`meta`、加 `timestamp`/`priority`/`length` | 05 篇六字段 vs char07-01 五字段的演进 |

## 附录 E：六条跨章关联

| 本篇 | 关联章节 | 关联点 |
|---|---|---|
| 01 `AgentState` | char05 LangGraph 状态图 | 手写状态机 vs 图编排的 State |
| 01 `update_state` 时间戳 | char07-05 JSONL `timestamp` | **性能探针同家族** |
| 02 `parse_input` | char04-02 ReAct 工具入参 / char07-03 路由 | **NL → 结构化参数**三个场景 |
| 03 `[ERROR]` 降级 | char05 降级链（结构化 status 结论） | **字符串魔法值 vs 结构化字段**的对比教学 |
| 04 `ConversationBufferWindowMemory` | char04-03 `ConversationBufferMemory` | **同一机制的手写版 vs 框架版** |
| 05 `dynamic_clip_context` | char07-01/02 上下文段 / char07-07 规则窗口 | **上下文压缩的两个流派** |

**核心认识**：char08 是 char01-07 的**第一次「集成」**——五个例子各补一种能力，合起来就是一个生产级单 Agent 的完整能力面。

## 附录 F：教学版 vs 生产版差距

| 教学简化 | 生产要求 | 相关篇 |
|---|---|---|
| 状态存内存 `history` 列表 | 持久化状态机（JSONL / 数据库）+ **超时自动转 `FAILED`** | 01 |
| 规则解析硬编码三条 | 声明式参数 schema + 两级漏斗（**规则优先，LLM 兜底**） | 02 |
| `[ERROR]` 字符串魔法值 | 结构化 `status` 字段 + **L1 重试 / L2 降级 / L3 熔断** | 03 |
| Memory 类已废弃仍使用 | **LangGraph checkpoint / Store API** | 04 |
| `len(content) // 2` 估 token | 真实 tokenizer（**`tiktoken`**）计数 | 05 |
| 五篇各自独立 | 合并为一个 `StatefulSmartAgent` 类 | 全部 |
| 无日志框架 | `logging` + 结构化日志 | 全部 |

## 附录 G：毕业设计建议——五篇合并

把 01-05 的五种能力合并成**一个** `StatefulSmartAgent`：

```python
class StatefulSmartAgent:
    def __init__(self, tools, token_limit=2000):
        self.state = AgentState.INITIALIZED          # ← 01 状态机
        self.history = []                             # ← 01 留痕
        self.memory = ConversationBufferWindowMemory(k=5, return_messages=True)  # ← 04 记忆
        self.tools = tools
        self.token_limit = token_limit                # ← 05 预算

    def execute(self, user_input: str) -> str:
        # ① 参数解析（02）
        params = parse_input(user_input)
        # ② 上下文装填（05）
        context = dynamic_clip_context(self.build_pool(), self.token_limit)
        # ③ 工具调用 + 容错（03）
        tool_result = self.call_tool_with_fallback(params)
        # ④ 状态流转（01）
        self.update_state(AgentState.RUNNING)
        # ⑤ 历史注入（04，注意走 load_memory_variables）
        history = self.memory.load_memory_variables({})["history"]
        ...
```

**这个练习的价值**：把「**五种能力叠加**」的抽象认识，变成一次真实的**代码集成**体验。
