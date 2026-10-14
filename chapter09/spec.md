# 第 9 章 规范说明书（spec.md）——多智能体系统：协作 / 调度 / 并发 / 协议

> **SDD 定位**：本文回答 *「多个 Agent 怎么一起干活」*。
> **上篇（意图与学习路径）**回答 *为什么学、学什么、怎么学*；
> **下篇（契约与验收）**回答 *每个文件到底承诺了什么、怎么验证、还缺什么*。
> **主线**：char01-08 都在「造一个 Agent」——给它加工具、加记忆、加状态、加降级。
> char09 是**全书第一次把多个 Agent 摆在一张桌子上**，问四个全新的工程问题：
> ① 数据怎么传（协作模式）→ ② 选谁先干（调度策略）→ ③ 同时干怎么不串台（并发管理）→ ④ 干的过程中消息长什么样（通信协议）。
> 本章 7 篇代码 + 1 篇纯注释把这些问题**逐层拆开**：01-02 协作模式 → 03-04 调度策略 → 05-07 并发管理 → 08 协议格式。
>
> 适用范围：`D:/AiWorkOut/aiAgentCode/chapter09/`（7 个可运行 .py + 1 个纯注释 .py / 932 行）。
> 契约字段一律**从代码事实反推**，不臆造；教材简化点与改写依据一并留痕。

---

# 上篇：意图与学习路径

## 1. 章意图（Why）

### 1.1 教材原版想解决什么

教材用一章讲多智能体系统，把「协作」这件事拆成四层工程问题：

| 教材概念 | 想说明什么 |
|---|---|
| 主控智能体与子任务智能体划分 | **主从架构**——主控只拆解调度，子 Agent 只干活，功能解耦 |
| 多智能体状态共享 | **黑板架构**——用中心状态管理器统一存取，实现逻辑解耦与数据共享 |
| 任务分配策略（轮询/权重） | 任务怎么均匀/按权重分给多个 Agent，保障负载均衡 |
| 任务依赖链与优先级 | **DAG 建模 + 优先级队列**，避免循环依赖死锁，同层按优先级排序 |
| 子智能体并行执行管理 | 用多线程同时触发多个子 Agent，用锁保证共享数据安全写入 |
| 上下文切换与隔离 | **命名空间 + task_id**，防止并发任务的历史对话互相渗透 |
| 状态同步与锁控制 | **Mutex / RWLock**，把关键代码标记为临界区，序列化共享资源读写 |
| Agent 间通信元信息 | Agent 之间发消息，一条完整消息长什么样（id/from/to/type/payload/auth） |

### 1.2 教材原版的三大断点

本章 7 个可运行例子**全部无法直接运行**，卡在三处（第 8 篇纯注释无需运行）：

| 断点 | 涉及例子 | 具体表现 |
|---|---|---|
| 🔴 **虚构框架 `qwen_agent`** | 01-07 全部 | `from qwen_agent.agent import Agent` / `from qwen_agent.context import Message` / `from qwen_agent.tools import Tool` —— 该框架在真实环境不存在（char02 起已多次确认），`ImportError` |
| 🔴 **虚构 Tool 继承 + 虚构 Agent 实例化** | 01/02/03/05/07 | `class XxxAgent(Tool): super().__init__(name=..., description=...)` 与 `agent = Agent(); agent.chat(messages=[Message(...)])` —— 继承的基类不存在，`chat()` 是虚构 API |
| 🟠 **无参 Agent 实例化（比前几篇更简化）** | 04/05/06 | `agent = Agent()` **连 `tools` 参数都没传** —— 结构与 01-03 略有差异，但同样是虚构 |

另外两个**数据真实性问题**：
- 01/02/03 篇的子 Agent `call()` 返回**硬编码模拟数据**（教材刻意为之）——教学重点是「调度结构」而非数据真实性。
- 05/06/07 篇的模拟耗时（`time.sleep(1.2/1.5/1.7/0.5)`）也是刻意保留——它让「并行 vs 串行」「锁内临界区耗时」变得肉眼可见。

### 1.3 本章改写要解决什么

全章 7 篇的改写逻辑**完全同构**（这是本章最容易识别的模式）：

| 教材原实现 | 改写后 | 教学点 |
|---|---|---|
| `from qwen_agent.agent import Agent` | `import dashscope` + `dashscope.Generation.call` | 不再黑盒，看得见唯一的真实 LLM 调用点 |
| `from qwen_agent.context import Message` | 普通 dict `{"role": ..., "content": ...}` | Message 的真身就是一个 dict |
| `from qwen_agent.tools import Tool` | 删除 import | — |
| `class XxxAgent(Tool)` + `super().__init__(name=..., description=...)` | `class XxxAgent:` + `self.name/self.description` 属性 | **最小改动**——只删了继承，类名与 `call()` 方法名不变 |
| `agent = Agent(tools=tools); agent.chat(messages=[msg])` | `dashscope.Generation.call(model="qwen-plus", messages=[...], result_format='message')` | 参数语义一一对应 |
| 7 篇中的 redis 调用 | —— | **无**（7 篇均无 redis，无需按 cache.json 方案替换） |

**改写纪律**：本章是「**调度结构优先**」的章节——所有**调度/协作/并发骨架原样保留**（`SharedState` / `TaskDispatcher` / `TaskExecutor` / `ParallelExecutor` / `ContextScope` / `SharedLog`），只把「虚构框架接入点」换成 dashscope。教材的模拟数据与模拟耗时也**原样保留**，因为它们承载教学语义。

### 1.4 本章最该带走的三句话

1. **调度的本质 = 一个决策函数**——无论轮询（`counter % N`）、加权（重池等概率）、还是 DAG（`depends` 全满足 → 入堆 → 优先级最大先出），底层都是「输入当前状态 → 输出下一个该干啥」的纯函数。char05 的 LangGraph 条件边路由函数就是这个家族的框架化升级版。
2. **并发安全三原则（优先级从高到低）**：**能隔离就不共享**（06 ContextScope）→ **能用免锁工具就不手写锁**（`queue.Queue`）→ **必须共享时才用 Lock**（05/07）。本章 05-07 三篇就是这三个原则的递进示范。
3. **协作模式从耦合到解耦的三级进化**：直接传递（01，高耦合链式）→ 黑板共享（02，写入者与读取者解耦）→ 并行+隔离+同步（05-07，各跑各的 + 少量共享写）。

---

## 2. 学习路径（8 文件 / 932 行）

按「协作模式 → 调度策略 → 并发管理 → 协议格式」的四层顺序阅读：

| # | 文件 | 行数 | 核心机制 | 读完后你应能说出 |
|---|---|---|---|---|
| 01 | `01_3个Agent联动的财经系统.py` | 112 | 主控写死三步调度链 + **直接传递** | 主从架构与「上游输出即下游输入」的耦合代价 |
| 02 | `02_多智能体间的状态共享机制.py` | 132 | `SharedState` 中心状态池 + 写入/读取分工 | **黑板架构**为什么能解耦 |
| 03 | `03_任务分配策略轮训与权重.py` | 130 | `TaskDispatcher`：`counter % N` 轮询 + **重池**加权 | 两种无依赖调度策略的实现与差异 |
| 04 | `04_任务依赖链与优先级控制.py` | 143 | `TaskExecutor`：**heapq 优先级堆 + depends 解锁** | DAG 调度怎么避免死锁 + 同层择优 |
| 05 | `05_子智能体并行执行管理.py` | 130 | `ParallelExecutor`：`Thread.start` + `join` 屏障 + `Lock` | 并行加速比怎么算、临界区是什么 |
| 06 | `06_上下文切换与隔离设计.py` | 145 | `ContextScope`：`task_id` 命名空间分桶 | **隔离**为什么优先于加锁 |
| 07 | `07_状态同步与锁控制策略.py` | 119 | `SharedLog`：`with lock` 临界区互斥写入 | 锁的语义与代价（锁内慢操作是反模式） |
| 08 | `08_agnet之间交互元信息例子.py` | 21 | JSON 通信格式结构定义（**纯注释，无可运行代码**） | 一条 Agent 通信消息的完整字段设计 |

### 阅读路线建议

- **第一遍（协作模式 2 篇）**：01 → 02。**先跑 01，再跑 02，对比感受**——同样三个角色干活，01 是主控写死顺序、数据靠函数返回值串起来；02 是每个 Agent 自己去状态池读写、主控只驱动流程。这是本章最重要的对照。
- **第二遍（调度策略 2 篇）**：03 → 04。03 讲「多个 Agent 都能干、选谁」（无依赖选择），04 讲「任务之间还有前后约束」（有依赖 DAG）。**03 的轮询与加权是同一问题的两种解法**，04 则把问题升级为图。
- **第三遍（并发管理 3 篇）**：05 → 06 → 07。05 追求「快」（并行），06 追求「不串台」（隔离），07 追求「不写坏」（同步）。**三篇合起来才是完整的并发系统**。
- **第四遍（协议 1 篇）**：08。纯设计参考，无需运行——理解「Agent 之间发消息应该长什么样」。
- **关键呼应**：
  - 01 与 02 是**同一系统的两种协作实现**，读的时候请对照。
  - 05/06/07 三篇是**并发安全三原则的逐条示范**，顺序即优先级。
  - 08 的 JSON 结构 = 01-07 所有「Agent 间数据传递」的**正式化版本**（前面都用函数返回值/共享字典，08 给出标准信封）。

---

## 3. 三条工程主线（本章反复出现的设计决策）

### 主线一：统一改写范式（全章同构）

7 篇的改写逻辑完全一致，形成一张「可套用的替换表」：

| 问题类型 | 教材写法 | 改写为 |
|---|---|---|
| 虚构框架 import | `from qwen_agent.agent import Agent` | 删除 + `import dashscope` |
| 虚构 Tool 继承 | `class XxxAgent(Tool): super().__init__(name=..., description=...)` | `class XxxAgent:` + `self.name / self.description` |
| 虚构 Agent 实例化 | `agent = Agent(tools=...); agent.chat(messages=[msg])` | `dashscope.Generation.call(model="qwen-plus", messages=[...])` |
| 虚构 Message 类 | `Message(role="user", content=...)` | `{"role": "user", "content": ...}` |
| redis 替换 | —— | **无**（7 篇均无 redis 调用） |

**为什么重要**：这张表是本章的「重构纪律」——读完 01 篇的改写方式，剩下 6 篇可以**预测**改法。这也是检验读者是否看懂的方式。

### 主线二：调度的本质 = 决策函数

无论哪种调度策略，底层都是一个「输入当前状态 → 输出下一个该干啥」的纯函数：

```
03 轮询：  counter % N                                    → 选中 agents[counter % N]
03 加权：  random.choice(pool)  其中 pool = Σ [agent] * weight  → 重池等概率即权重概率
04 DAG：   所有 depends 已 executed → 入堆 → heappop 取 -priority 最小（即 priority 最大）
```

**对照 char05**：LangGraph 的 `add_conditional_edges(node, route_fn, mapping)` 里的 `route_fn` 就是这个家族的框架化升级版——理解了 03/04 的调度决策函数，再看 LangGraph 的路由就不再是黑盒。

**04 篇的关键设计**：用「**小根堆 + 存 `-priority`**」模拟大根堆（Python `heapq` 无最大堆）。堆里放的是 `(-priority, task_id)` 元组——**优先级相同时按 task_id 字符串排序**（这是 `heapq` 比较元组的隐式行为，值得注意）。

### 主线三：并发安全三原则（优先级从高到低）

本章 05-07 三篇正好对应递进的三个原则：

| 原则 | 本篇代表 | 含义 | 代价 |
|---|---|---|---|
| **能隔离就不共享** | 06 `ContextScope` | 每个任务一个独立命名空间，数据结构上就不可能串 | 内存占用（但可 `destroy` 回收） |
| **能用免锁工具就不手写锁** | （本篇未用）`queue.Queue` | Python 标准库线程安全容器，内部已加锁 | —— |
| **必须共享时才用 Lock** | 05 `ParallelExecutor.lock` / 07 `SharedLog.lock` | 显式互斥，牺牲并发性换正确性 | 串行等待 |

**核心认识**：**锁不是第一选择，隔离才是**。06 篇的 `ContextScope` 通过「给每个 task_id 一个独立的 list」从根本上消除了竞争条件——这比「加锁保护一个共享 list」更彻底（前者是**数据结构层面不可能串**，后者是**靠纪律保证不串**）。

---

## 4. 学习检查清单（读完自测）

- [ ] 能用自己的话解释「主从架构」和「黑板架构」的区别。
- [ ] 能说出**直接传递**（01）与**黑板共享**（02）各自适合什么场景。
- [ ] 能手写一个 `counter % N` 轮询调度器。
- [ ] 能解释「重池」实现加权分配的原理（为什么 `random.choice` 重池 = 按权重概率）。
- [ ] 能说出为什么加权分配在**小样本**下不收敛。
- [ ] 能用 `heapq` + `depends` 手写一个简易 DAG 调度器。
- [ ] 能解释「为什么 heapq 要存 `-priority`」。
- [ ] 能说出 `Thread.start()` 与 `Thread.join()` 各自的作用。
- [ ] 能计算并行加速比（串行总耗时 ÷ 并行耗时）。
- [ ] 能解释「临界区」和「互斥」的含义。
- [ ] 能说出「能隔离就不共享」这句话为什么成立。
- [ ] 能说出锁内做耗时操作为什么是反模式，以及生产级做法（生产者-消费者）。
- [ ] 能默写一条 Agent 通信消息的完整 JSON 字段。

---

# 下篇：契约与验收

## 5. 全局技术约束（C-xx）

### C-01 全章禁用虚构框架 `qwen_agent`

**约束**：不得出现 `from qwen_agent...` 的可执行 import；仅允许以注释形式保留（「原写法」区块）。
**验收**：grep `qwen_agent` 应只命中**注释块**（`# from qwen_agent...` 或文件头说明）。

### C-02 子 Agent 一律改写为「纯类 + name/description 属性」

**统一写法**：
```python
class XxxAgent:
    def __init__(self, ...):
        # 原写法：super().__init__(name="xxx", description="...")
        self.name = "xxx"
        self.description = "..."
    def call(self, query: str) -> str: ...
```
**约束**：**类名与 `call(query) -> str` 方法名保持不变**（最小改动原则——让读者对照时能一眼看出「只删了继承」）。
**例外**：07 篇的 `LoggingAgent` 继承 `threading.Thread`（这是**真实**继承，不是虚构的 —— 它就是要做线程）；06 篇的 `AgentTask` 同理。

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
return response.output.choices[0].message.content
```
**参数约束**：
- `result_format='message'` **必填** —— 否则 `response.output.choices[0]` 结构不成立（返回 text 格式）；
- `temperature=0.3`（全章统一，偏低以保证稳定）；
- `max_tokens=512`（全章统一）；
- 响应路径**固定** `response.output.choices[0].message.content`。

**验收**：grep `result_format='message'` 命中 01-07 全部 LLM 调用点。

### C-04 API Key 来自环境变量

```python
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key
```
**约束**：全章统一这两行，出现在每个文件的模块级。
**已知风险**：**无空值校验**（见缺口 G-01）——key 未设置时会得到晦涩的认证错误。

### C-05 调度骨架必须原样保留（不得「优化」）

**约束**：以下教学资产**逐字保留**，不得为了「更优雅」而改写：

| 篇 | 必须保留的原样结构 |
|---|---|
| 01 | `ControlAgent.run()` 的三步调度链（资讯 → 预测 → LLM 整合） |
| 02 | `SharedState.update/get/dump` 三方法 + 两子 Agent 的写/读分工 |
| 03 | `_build_weighted_pool()` 重池构造 + `dispatch()` 双分支 |
| 04 | `TaskExecutor.execute()` 的 heapq 主循环 + `_can_execute()` 解锁 |
| 05 | `ParallelExecutor.execute_all()` 的 start/join 屏障 + `with self.lock` |
| 06 | `ContextScope.create/append/get/destroy` 四方法 + task_id 命名空间 |
| 07 | `SharedLog.write_log()` 的 `with self.lock` 临界区 |

**理由**：本章是「**结构教学章**」——骨架本身就是要教的东西，不是可替换的实现细节。

### C-06 模拟数据与模拟耗时原样保留

**约束**：子 Agent 的硬编码返回（如 `"[资讯摘要] 当前宏观新闻显示：制造业回暖..."`）与 `time.sleep()` **不得替换为真实 API / 删除**。
**理由**：
- **模拟数据**：教材刻意为之——教学重点是「调度结构」而非「数据真实性」。改成真实 API 会引入网络不确定性，反而掩盖调度逻辑。
- **模拟耗时**：05 篇的 `sleep(1.2/1.5/1.7)` 让「并行 1.7s vs 串行 4.4s」的对比可见；07 篇的 `sleep(0.5)` 在锁内，让「串行等待」肉眼可见。**删掉就失去了教学效果**。

### C-07 主流程与原样输出保留

**约束**：`if __name__ == "__main__":` 段落的**演示流程与打印语句**原样保留（如 `=== 启动... ===` 标题、`--- Qwen3.0最终响应 ---` 分隔线）。
**理由**：这些打印是学习者的「观察窗口」，比如 05 篇的 `并行执行总耗时：X 秒（串行预计 4.4 秒）` 直接给出了加速比。

### C-08 文件头注释必须包含三要素

**约束**：每个改写文件的头部注释块必须包含：
1. **核心概念**（教材原意，1-3 行）；
2. **改写前的问题**（编号列出，指向虚构框架/虚构继承/虚构实例化）；
3. **改写策略**（分条列出保留了什么、替换了什么）。

**实例**（01 篇头部）：
```python
# 改写前的问题：
#   1) qwen_agent.Agent/Message/Tool——虚构框架（char02 起已多次确认不存在于真实环境）
#   2) NewsAgent / ForecastAgent 的 call() 返回硬编码模拟数据（教材刻意为之，保留原样）
#   3) ControlAgent 内部的 agent.chat() 是唯一真实 LLM 调用点
# 改写策略：
#   - 三类角色的职责划分 + run() 三步调度链原样保留（本篇核心教学资产：主从架构）
#   - NewsAgent / ForecastAgent 去掉虚构 Tool 继承，改为纯类（模拟数据保持原样）
#   - agent.chat() → dashscope.Generation.call（qwen-plus）
```

### C-09 「原写法（注释保留）」必须紧贴改写点

**约束**：每一处改写都要在**紧邻位置**保留原写法注释，格式为 `# 原写法：...`。
**实例**：
```python
# 原写法：self.agent = Agent(tools=tools)
# 改写：删掉虚构 Agent 实例——主控只持有子Agent引用，LLM 调用走 dashscope
self.news_tool = tools[0]
self.forecast_tool = tools[1]
```
**理由**：这是「可对照重构」的关键——读者能逐行看出改了什么。

### C-10 并发原语必须用标准库，不引第三方

**约束**：并发只能使用 `threading`（`Thread` / `Lock`）与 `heapq` / `random` 等标准库。
**理由**：本章教学目标是「**看见并发原语本身**」——引入 `concurrent.futures` / `asyncio` 会掩盖 `Thread.start/join` 与 `Lock` 的基础语义。

### C-11 08 篇纯注释文件保持原样

**约束**：`08_agnet之间交互元信息例子.py` **不得**添加可运行代码或改为 `.md`。
**理由**：它是「设计参考」而非「可运行例子」——教材本意就是给一个 JSON 结构示例。文件名拼写错误（`agnet`）**保留原样**作为「教材勘误」的实物证据。

### C-12 实测数据写入注释（加速比 / 收敛性）

**约束**：能实测的量化结论必须在注释中留痕。
**实例**：
- 05 篇：`并行 1.7s vs 串行 4.4s = 2.59x 加速比`；
- 03 篇：`权重 1:1:3 的 3 次实测 → agent_3 仅占 67%，跑 100 次才收敛到约 60%`；
- 04 篇：`实际执行顺序 fetch_news → model → report → graph（依赖约束优先于优先级）`。

**理由**：这是学习型代码最有价值的部分——**可复现的一手观察**。

---

## 6. 逐文件契约（F-01 ~ F-08）

---

### F-01 `01_3个Agent联动的财经系统.py`（112 行）——直接传递篇

**意图**：主从架构的最小示范——主控 Agent **不干活**，只负责「任务拆解 → 按依赖顺序调度子 Agent → 最终整合 LLM 回应」。

**三类角色契约**：

| 类 | 角色 | 职责 | `call()` 返回 |
|---|---|---|---|
| `NewsAgent` | 资讯子 Agent | 抓取并提取财经新闻 | 硬编码 `"[资讯摘要] 当前宏观新闻显示：制造业回暖，CPI保持温和，出口增长稳定。"` |
| `ForecastAgent` | 分析子 Agent | 根据资讯预测 GDP 趋势 | `f"[预测结果] 综合判断2024年GDP预计增长5.3%。分析依据为：{summary}"` |
| `ControlAgent` | 主控 Agent | 调度 + 整合 | 三步链式调度 |

**ControlAgent 契约**：
```python
class ControlAgent:
    def __init__(self, tools: List):
        # 原写法：self.agent = Agent(tools=tools)
        self.news_tool = tools[0]
        self.forecast_tool = tools[1]

    def run(self, user_query: str) -> str:
        summary  = self.news_tool.call(user_query)       # Step 1
        forecast = self.forecast_tool.call(summary)      # Step 2 ← 上游输出即下游输入
        final_prompt = f"""请基于以下任务链条返回统一回应：
任务目标：{user_query}
资讯摘要：{summary}
预测输出：{forecast}
请以财经顾问语气生成最终报告："""
        # Step 3：dashscope.Generation.call
```

**核心机制契约（本篇教学点）**：
- **数据传递方式 = 函数返回值串起来**（`summary` 传给 `forecast_tool.call(summary)`）—— 这是「**直接传递**」。
- **调度顺序写死在 `run()` 里** —— 主控的调度是**硬编码三步**，无决策函数。

**主流程契约**：
```python
news = NewsAgent(); forecast = ForecastAgent()
control_agent = ControlAgent(tools=[news, forecast])
response = control_agent.run("请预测2024年中国GDP走势，并说明依据")
```

**验收标准**：
- V-01-A：打印 `→ 开始执行主控Agent任务拆解与调度` + 三条 `→ 调用xxx...` 流水线日志。
- V-01-B：打印 `--- Qwen3.0最终响应 ---` 后输出财经顾问语气报告。
- V-01-C：报告中**出现 GDP 相关数字与依据**（LLM 基于链式结果生成）。

**已知风险 / 诚实标注**：
- ⚠️ **「幻觉放大链」** —— 上游只喂了硬编码事实（宏观三句 + GDP 5.3%），下游 `qwen-plus` 会**自行编造** PMI / CPI / 出口增速等细节数字，报告读起来极其可信但全是幻觉。**这是本篇最有价值的实测发现**（见缺口 G-03）。
- ⚠️ 两个子 Agent 的 `call()` 是硬编码 —— 无法替换为真实数据（C-06 约束，且这是教学要求）。
- ⚠️ 耦合度高 —— 上游返回值的**格式变化**会直接影响下游（无接口契约）。

**教材问题（文件头注释实录）**：
> 改写前的问题：1) `qwen_agent.Agent/Message/Tool`——虚构框架（char02 起已多次确认不存在于真实环境）；2) `NewsAgent / ForecastAgent` 的 `call()` 返回硬编码模拟数据（教材刻意为之，保留原样）——真实子 Agent 应接入新闻 API / 数据库，本篇教学重点是"调度结构"而非数据真实性；3) `ControlAgent` 内部的 `agent.chat()` 是唯一真实 LLM 调用点。
> 备注：本篇原代码无 redis 调用，无需按 cache.json 方案替换。

---

### F-02 `02_多智能体间的状态共享机制.py`（132 行）——黑板共享篇

**意图**：与 01 篇**对照**——同样三个角色干活，但数据不再靠函数返回值串联，而是全部经过**中心状态管理器**（黑板）。

**SharedState 契约（本篇灵魂，原样保留）**：
```python
class SharedState:
    def __init__(self):
        self.state: Dict[str, Any] = {}

    def update(self, key: str, value: Any):
        print(f"→ [状态更新] {key} = {value}")     # 打印日志便于调试
        self.state[key] = value

    def get(self, key: str, default=None):
        return self.state.get(key, default)

    def dump(self) -> Dict[str, Any]:
        return self.state.copy()                     # 复制一份，防外部改内部
```

**三个 Agent 的读写分工契约**：

| Agent | 写 | 读 |
|---|---|---|
| `AnalysisAgent` | `econ_trend` | —— |
| `ReportAgent` | `final_report` | `econ_trend` |
| `ControllerAgent` | `user_input` | `user_input` / `econ_trend` / `final_report` |

**关键契约（解耦的证据）**：
```python
analysis = self.analysis_tool.call(user_query)   # 写 econ_trend
report   = self.report_tool.call("")             # ← 注意参数是空串！
```
**`call("")` 传空串是刻意的** —— 数据**完全靠状态池传递**，不通过参数。这是「黑板解耦」最直接的代码证据。

**主流程契约**：三个对象**共享同一个 `shared` 实例**：
```python
shared = SharedState()
agent1 = AnalysisAgent(shared)
agent2 = ReportAgent(shared)
controller = ControllerAgent([agent1, agent2], shared)
```

**验收标准**：
- V-02-A：打印 `→ [状态更新] user_input = ...` / `econ_trend = ...` / `final_report = ...` 三条。
- V-02-B：打印 `--- Qwen3.0最终响应 ---` 后输出完整用户报告。
- V-02-C：`report_tool.call("")` 返回时**确实读到了 `econ_trend`**（值为「制造业增长、CPI温和回落、出口回升」）。

**已知风险 / 诚实标注**：
- ⚠️ **幻觉风险延续 01 篇** —— 状态池里只有三句硬编码趋势，LLM 仍会自行填充细节。
- ⚠️ **黑板可能成为瓶颈** —— 所有 Agent 读写同一 `SharedState`，规模化后会成为竞争点（本篇串行执行，未暴露）。
- ⚠️ **无 key 命名规范/无类型约束** —— `update("econ_trend", ...)` 与 `get("econ_trend", ...)` 靠**字符串字面量**对齐，写错就是静默 `None`（见缺口 G-04）。
- ⚠️ **`dump()` 是浅拷贝** —— 若 value 是可变对象，外部修改仍会渗透（当前 value 均为 str，无影响）。

**教材问题（文件头注释实录）**：
> 核心概念：通过独立的"中心状态管理器"来统一存储和分发任务中间结果与上下文，实现智能体间的逻辑解耦与数据共享。
> 改写前的问题：同 01 篇三条（虚构框架 / 硬编码模拟数据 / agent.chat() 唯一真实调用点）。
> 改写策略：`SharedState` 中心管理器 + 两子 Agent 的写入/读取模式 + `execute()` 三步调度链原样保留（本篇核心教学资产：状态共享让 Agent 解耦）。

---

### F-03 `03_任务分配策略轮训与权重.py`（130 行）——无依赖调度篇

**意图**：解决「**多个 Agent 都能干同一个任务，选谁？**」——两种策略：轮询（均匀）与加权（按性能）。

**EconomicAgent 契约**：
```python
class EconomicAgent:
    def __init__(self, name, quality: float):
        self.name = name
        self.description = f"财经预测Agent（性能评分：{quality}）"
        self.quality = quality    # 性能评分属性（本例中未被调度器使用——见风险）
    def call(self, query: str) -> str:
        return f"[{self.name}] 分析完成：预计增长为 {round(5 + random.random(), 2)}%。性能评分为 {self.quality}"
```
**注意**：`random.random()` 让每次输出略有差异（模拟真实波动）。

**TaskDispatcher 契约（本篇灵魂，原样保留）**：
```python
class TaskDispatcher:
    def __init__(self, agents, strategy="round_robin", weights=None):
        self.agents = agents
        self.strategy = strategy
        self.weights = weights or {}
        self.counter = 0
        # 加权策略**预构造重池**
        self.pool = self._build_weighted_pool() if strategy == "weighted" else agents

    def _build_weighted_pool(self):
        pool = []
        for agent in self.agents:
            weight = self.weights.get(agent.name, 1)   # 未配置默认 1
            pool.extend([agent] * weight)
        return pool

    def dispatch(self):
        if self.strategy == "round_robin":
            agent = self.agents[self.counter % len(self.agents)]
            self.counter += 1
            return agent
        elif self.strategy == "weighted":
            return random.choice(self.pool)
```

**两种策略的数学契约**：

| 策略 | 决策函数 | 分布 |
|---|---|---|
| `round_robin` | `agents[counter % N]` | 严格均匀（N 次一循环） |
| `weighted` | `random.choice(Σ [agent]×weight)` | **概率性**——重池长度 = Σweight，等概率抽取 = 按权重概率 |

**主流程契约（双策略对比，本篇核心演示）**：
```python
agent1/2/3 = EconomicAgent("econ_agent_1/2/3", 0.85/0.90/0.95)
# 轮询：跑 3 次
round_dispatcher = TaskDispatcher([a1,a2,a3], strategy="round_robin")
# 加权：权重 1:1:3
weight_map = {"econ_agent_1": 1, "econ_agent_2": 1, "econ_agent_3": 3}
weighted_dispatcher = TaskDispatcher([a1,a2,a3], strategy="weighted", weights=weight_map)
```

**验收标准**：
- V-03-A：轮询 3 次打印 `→ 分配给Agent：econ_agent_1 → econ_agent_2 → econ_agent_3`（严格依次）。
- V-03-B：加权 3 次打印的 Agent 名**随机但 econ_agent_3 出现频率更高**。
- V-03-C：`econ_agent_3` 约占 60%（权重 3/5）——但 **3 次样本远不足以体现**。

**已知风险 / 诚实标注（本篇最有价值的实测发现）**：
- 🔴 **权重是概率不是配额（小样本不收敛）** —— 实测权重 1:1:3 跑 3 次出现 `agent_3 → agent_1 → agent_1`（agent_1 占 67%，远高于理论 20%）；**跑 100 次才接近 20%/20%/60%**。教材的「3 次演示」会给人错误印象（见缺口 G-05）。
- ⚠️ **`quality` 属性定义但未被调度器使用** —— 权重与 quality 是**独立配置**（代码注释已明确：`self.quality` 的注释写「调度器可据此做加权」，但实际 `weights` 是独立传入的 dict）。这是「设计意图 vs 实现」的落差。
- ⚠️ **重池在 `__init__` 时构造一次** —— 若运行时想改权重，必须重建 Dispatcher（无动态调整接口）。
- ⚠️ `weights=None` 的类型标注是 `Dict[str, int] = None` —— 类型与默认值不一致（应为 `Optional[Dict[str,int]]`）。

**教材问题（文件头注释实录）**：
> 核心问题：如何将子任务合理地分配给不同智能体，以保障系统整体的高并发处理性能、毫秒级响应效率，以及各个节点的任务负载均衡？
> 轮询分配 (Round-Robin)：将任务按请求顺序均匀、依次地分配给一组可用的智能体，形成循环分配队列。
> 加权分配 (Weighted Dispatch)：为每个智能体节点赋予一个"权重系数"，系统根据权重占比进行概率性的任务分配。
> 【本篇的 quality 与 weights 是两套独立配置】——`EconomicAgent.quality` 是「性能评分」属性，`TaskDispatcher.weights` 是「调度权重」dict；本例中两者独立设置（0.85/0.90/0.95 与 1/1/3），**并未联动**。

---

### F-04 `04_任务依赖链与优先级控制.py`（143 行）——DAG 调度篇

**意图**：调度问题升级——任务之间**有前后依赖**（不能用简单轮询），且同层任务**需要按优先级排序**。

**Task 契约（任务四元组）**：
```python
class Task:
    def __init__(self, id: str, func: Callable, depends: List[str] = None, priority: int = 1):
        self.id = id
        self.func = func             # 无参数函数，结果存 self.result
        self.depends = depends or [] # 前置依赖的 ID 列表
        self.priority = priority     # 优先级（越大越高）
        self.executed = False        # 标记位
        self.result = None
```

**TaskExecutor 契约（本篇灵魂，原样保留）**：
```python
class TaskExecutor:
    def __init__(self):
        self.tasks: Dict[str, Task] = {}
        self.execution_log = []

    def register(self, task: Task): self.tasks[task.id] = task

    def _can_execute(self, task: Task) -> bool:
        """依赖检查：所有前置任务都已执行才能开始"""
        return all(self.tasks[dep].executed for dep in task.depends)

    def execute(self):
        pq = []                                          # 小根堆（存 -priority）
        # Step 1：根任务（无依赖）入堆
        for task in self.tasks.values():
            if not task.depends:
                heapq.heappush(pq, (-task.priority, task.id))
        # Step 2：主循环
        while pq:
            _, tid = heapq.heappop(pq)                   # 堆顶 = 当前最高优先级
            task = self.tasks[tid]
            if task.executed: continue                   # 已执行过
            if not self._can_execute(task): continue     # 依赖未满足
            task.result = task.func(); task.executed = True
            self.execution_log.append((tid, task.result))
            # Step 3：解锁下游
            for t in self.tasks.values():
                if not t.executed and self._can_execute(t):
                    heapq.heappush(pq, (-t.priority, t.id))
```

**核心机制契约（三句话）**：
1. **解锁**：只把「无前置依赖」的根任务入堆；
2. **级联**：任务完成后扫描全表，把**新解锁**的任务入堆；
3. **择优**：堆顶是 `-priority` 最小者 = `priority` 最大者，先执行。

**任务图契约（主流程）**：
```python
executor.register(Task("fetch_news", task_fetch_news, priority=3))
executor.register(Task("model", task_model_analysis, depends=["fetch_news"], priority=4))
executor.register(Task("graph", task_generate_graph, depends=["model"], priority=1))
executor.register(Task("report", task_generate_report, depends=["model"], priority=2))
```
依赖链：`fetch_news → model → {graph, report}`（model 是 graph/report 的共同上游）。

**4 个任务函数契约**：每个都是 `time.sleep(1)` + 返回硬编码字符串（模拟耗时，C-06 保留）。

**验收标准**：
- V-04-A：执行顺序为 **`fetch_news` → `model` → `report` → `graph`**。
  - 关键推理：`model` 优先级 4 最高，但它被 `fetch_news` 阻塞；`fetch_news` 完成后 `model` 解锁入堆（优先级 4 最高）先执行；`model` 完成后 `graph(1)` 与 `report(2)` **同时解锁**，此时堆中 `report` 优先（2 > 1）。
  - ⚠️ **注意 `graph` 优先级是 1（最低）**——尽管它在依赖链上「更靠左」，仍因优先级低而后执行。
- V-04-B：打印 `→ 执行任务：xxx（优先级：N）` 共 4 行。
- V-04-C：总耗时 ≥ 4 秒（4 × `sleep(1)`，**串行执行**）。
- V-04-D：`--- Qwen3.0输出总结 ---` 后输出基于 `executor.get_summary()` 的分析总结。

**核心教学点（依赖约束优先于优先级）**：
> **优先级只在「同一批次可执行任务」之间比较** —— `model` 优先级最高，但它必须先等 `fetch_news`。这说明 **DAG 的依赖约束是不可逾越的硬约束，优先级只是同层内的软排序**。

**已知风险 / 诚实标注**：
- ⚠️ **无环检测** —— 若注册时写成循环依赖（A depends B, B depends A），**两个任务都不会入堆**（无根任务），`execute()` 静默结束、无任何输出。教材导语说「避免循环依赖死锁」，但**代码未实现检测**（见缺口 G-06）。
- ⚠️ **同优先级时按 task_id 字符串排序** —— `heapq` 比较元组 `(-priority, id)`，优先级相同则比较 id 字符串（隐式行为，未在注释中说明）。
- ⚠️ **`execute()` 无返回值** —— 结果要另调 `get_summary()`（接口不够直接）。
- ⚠️ **`time.sleep(1)` × 4 = 4 秒** —— 与 05 篇的并行形成**直接对照**（05 篇三任务并行只需 1.7 秒）。但**04 篇有依赖，不能并行**——这是刻意的对照设计。
- ⚠️ `Task.func` 是**无参函数** —— 若任务需要上游结果，当前设计**不支持**（`model` 拿不到 `fetch_news` 的 `result`）。这是一个明显的**能力缺口**（见缺口 G-07）。

**教材问题（文件头注释实录）**：
> 调度执行逻辑：1. 解锁任务：优先扫描并执行所有无前置依赖的"根任务"。2. 级联触发：任务完成后，自动将其下游所有直接依赖任务解锁。3. 择优执行：在同一批次可执行的任务池中，按照预设优先级规则调度执行。
> 改写前的问题：1) `qwen_agent.Agent/Message`——虚构框架；2) `Agent()` 实例化——原写法没传 `tools` 参数（比前几篇更简化，但仍是虚构）；3) 4 个任务函数用 `time.sleep(1)` 模拟耗时（原样保留，教学重点是调度逻辑）。
> 【实测执行顺序】`fetch_news → model → report → graph` —— 注意 `graph` 优先级 1 低于 `report` 的 2，虽同在 model 下游，仍后执行。**依赖约束优先于优先级**。

---

### F-05 `05_子智能体并行执行管理.py`（130 行）——并行执行篇

**意图**：解决「串行任务处理效率低」——用多线程**同时触发**多个子 Agent，用 `Lock` 保证共享数据安全写入。

**三个子 Agent 契约**（耗时递增，用于验证并行收益）：

| 类 | name | 模拟耗时 | 返回 |
|---|---|---|---|
| `PolicyAgent` | `policy_agent` | 1.2s | `"政策导向积极，财政刺激与减税政策持续发力。"` |
| `SentimentAgent` | `sentiment_agent` | 1.5s | `"市场情绪整体乐观，投资者信心显著回暖。"` |
| `TrendAgent` | `trend_agent` | 1.7s | `"预计2024年GDP增长为5.5%，主要来源于消费与出口复苏。"` |

**ParallelExecutor 契约（本篇灵魂，原样保留）**：
```python
class ParallelExecutor:
    def __init__(self):
        self.results: Dict[str, str] = {}   # 所有线程共享
        self.lock = threading.Lock()        # 保护 results 写入

    def run_agent(self, agent, name: str):
        print(f"→ 启动{name}")
        result = agent.call("")
        with self.lock:                     # ← 临界区
            self.results[name] = result
        print(f"→ {name}完成")

    def execute_all(self, agents: Dict):
        threads = []
        for name, agent in agents.items():
            t = threading.Thread(target=self.run_agent, args=(agent, name))
            t.start()                       # 并发启动
            threads.append(t)
        for t in threads:
            t.join()                        # 屏障：等所有线程结束
        return self.results
```

**关键并发语义契约**：

| 原语 | 语义 | 必要性 |
|---|---|---|
| `t.start()` | 启动线程（**立即返回**，不等待执行完） | 让三个 Agent 同时跑 |
| `t.join()` | **屏障**——阻塞直到该线程结束 | 保证 `results` 收集完整 |
| `with self.lock:` | 临界区——**同一时刻只有一个线程能进入** | 保护 `results` 字典写入 |

⚠️ **注意 `t.start()` 在循环内、`t.join()` 在循环外** —— 这是「**先全部启动、再全部等待**」的模式（不是「启动一个等一个」）。若把 `join()` 放进第一个循环，就退化成串行了。

**主流程契约（含计时，新增）**：
```python
t0 = time.time()
results = executor.execute_all(agents)
elapsed = time.time() - t0
print(f"\n并行执行总耗时：{elapsed:.2f}秒（串行预计 {1.2+1.5+1.7:.1f} 秒）")
```

**验收标准**：
- V-05-A：打印 `→ 启动政策分析` / `→ 启动市场情绪` / `→ 启动趋势预测` **三条连续出现**（证明并发启动）。
- V-05-B：`→ {name}完成` 的顺序为 **趋势预测（1.7s）→ 市场情绪（1.5s）→ 政策分析（1.2s）**（**按耗时倒序完成**，证明真并行）。
- V-05-C：**总耗时 ≈ 1.7 秒**（= 最慢那个），而非 4.4 秒（串行和）。
- V-05-D：**加速比 ≈ 2.59x**（4.4 / 1.7）。
- V-05-E：汇总 prompt 含三个 Agent 的输出 + `--- Qwen3.0响应输出 ---` 后输出简报。

**已知风险 / 诚实标注**：
- ⚠️ **Python GIL 的真相** —— `threading` 在 **CPU 密集**任务上**不会**有加速（GIL 串行化字节码）；本例有加速是因为任务是 `time.sleep()`（**I/O 等待会释放 GIL**）。**真实场景中**：I/O 密集（网络/磁盘）用 `threading`，CPU 密集用 `multiprocessing`（见缺口 G-08）。
- ⚠️ **`results` 字典的写入虽加锁，但 `dict` 在 CPython 中的单键写入本身是原子的** —— 这里加锁是**教学示范**（更规范的写法），而非严格必需。
- ⚠️ **无超时控制** —— 若某线程卡死，`join()` 会永久阻塞（应使用 `join(timeout=...)`）。
- ⚠️ **无异常处理** —— 线程内抛异常**不会**传播到主线程（`threading` 默认打印 traceback 但不中断），`results` 会缺 key。
- ⚠️ **`agent.call("")` 传空串** —— 各子 Agent 的 `call(_: str)` 忽略参数（与 02 篇同款「参数无用，数据靠别处传」的模式）。

**教材问题（文件头注释实录）**：
> 案例目标：构建一个支持多智能体并行协作的执行系统，解决串行任务处理效率低的问题。核心是利用 Python 多线程机制，同时触发并管理多个子智能体的任务流程，通过线程锁保证共享数据的安全写入，最终统一汇总所有子任务的执行结果。
> 改写前的问题：1) `qwen_agent.Agent/Message/Tool`——虚构框架；2) 三个子 Agent 的 `call()` 用 `time.sleep()` 模拟耗时（教材刻意为之，保留原样）；3) `Agent()` 实例化没传 `tools` 参数（同 04 篇，仍是虚构）。
> 【实测并行加速比】并行 1.7s vs 串行 4.4s = **2.59x**。注意：这个加速来自 `sleep` 释放 GIL，**不是** CPU 并行。

---

### F-06 `06_上下文切换与隔离设计.py`（145 行）——上下文隔离篇

**意图**：解决「**状态污染与响应混乱**」——多任务并发时，历史对话/任务参数会相互渗透。方案是**命名空间 + task_id 的物理与逻辑双重隔离**。

**ContextScope 契约（本篇灵魂，原样保留）**：
```python
class ContextScope:
    def __init__(self):
        self.contexts: Dict[str, list] = {}   # task_id → 消息列表（命名空间分桶）

    def create(self, task_id: str):
        self.contexts[task_id] = []           # 新任务 = 新桶

    def append(self, task_id: str, message: dict):
        if task_id in self.contexts:          # ← 守卫：不存在的 task_id 静默忽略
            self.contexts[task_id].append(message)

    def get(self, task_id: str) -> list:
        return self.contexts.get(task_id, [])  # 不存在返回空列表

    def destroy(self, task_id: str):
        if task_id in self.contexts:
            del self.contexts[task_id]
```

**AgentTask 契约（线程化的任务单元）**：
```python
class AgentTask(threading.Thread):
    def __init__(self, task_id, user_input, scope):
        super().__init__()
        self.task_id = task_id; self.user_input = user_input
        self.scope = scope; self.result = None

    def run(self):
        self.scope.create(self.task_id)                                       # 1. 建独立上下文
        self.scope.append(self.task_id, {"role": "user", "content": self.user_input})  # 2. 追加用户消息
        history = self.scope.get(self.task_id)                                # 3. 取自己的上下文
        response = dashscope.Generation.call(model="qwen-plus", messages=history, ...)  # 独立 LLM 调用
        assistant_content = response.output.choices[0].message.content
        self.scope.append(self.task_id, {"role": "assistant", "content": assistant_content})  # 4. 回填
        self.result = assistant_content
```

**隔离契约（核心机制）**：
- **隔离单位 = `task_id`** —— 每个任务一个独立的 `list`；
- **隔离手段 = 命名空间分桶**（`contexts[task_id]`）—— 数据结构上**物理隔离**，不是靠加锁纪律；
- ⚠️ **`ContextScope` 的 `dict` 本身在多线程下被并发写**（`create` 同时调用）—— 严格说这里**有**竞争条件（CPython 下大概率安全，因为不同 key 的写入落在不同桶）。**这恰恰是「能隔离就不共享」的边界**：分桶减少了冲突概率，但**没有完全消除**对顶层 dict 的并发访问。

**主流程契约**：
```python
tasks = [
    AgentTask("task_001", "请简要说明当前中国宏观经济趋势", context_scope),
    AgentTask("task_002", "总结2023年人工智能的发展方向", context_scope),
    AgentTask("task_003", "请写一段300字的自然语言处理技术简介", context_scope)
]
for task in tasks: task.start()     # 先全部启动
for task in tasks: task.join()      # 再全部等待
```

**隔离检查契约（可复用的验证代码段）**：
```python
for t in tasks:
    ctx = context_scope.get(t.task_id)
    roles = [m["role"] for m in ctx]
    print(f"  {t.task_id}: {len(ctx)} 条消息，角色序列 {roles}（无其他任务内容 = 隔离成功）")
```

**验收标准**：
- V-06-A：打印 `→ 启动任务[task_001/002/003]` 三条连续出现。
- V-06-B：**每个 task_id 的消息数为 2**（user + assistant）。
- V-06-C：**角色序列均为 `['user', 'assistant']`**（无其他任务内容渗透 = 隔离成功）。
- V-06-D：三个任务完成耗时 **< 串行和**（三个 LLM 调用并行）。
- V-06-E：汇总输出 `--- 汇总总结 ---` + 三个任务统一总结。

**核心教学点（为什么隔离优于加锁）**：
> 如果三个任务**共享一个** `list` 存历史对话，那么并发追加会导致**消息交错**（task_001 的 user、task_002 的 user、task_001 的 assistant...混在一起），LLM 看到的上下文就乱了。
> **加锁**能防止交错，但**无法防止逻辑污染**（`messages=history` 会带上别的任务的消息）。
> **分桶隔离**从根上解决：每个任务只能看到自己的桶。

**已知风险 / 诚实标注**：
- ⚠️ **`ContextScope.contexts` 顶层 dict 无锁** —— 并发 `create()` 时严格说有竞争（CPython 下不同 key 写入大概率安全，但**不应依赖此实现细节**）（见缺口 G-09）。
- ⚠️ **`append()` 的静默忽略** —— 若忘调 `create()`，`append()` 会**静默丢弃消息**（无警告），后续 `get()` 返回空列表，LLM 收到空 messages 会报错或乱答。**这是隐蔽的 bug 源**（见缺口 G-10）。
- ⚠️ **`destroy()` 未被调用** —— 主流程里创建了三个上下文但从未销毁（示例代码省略，真实场景需在任务结束后回收，否则内存持续增长）。
- ⚠️ **每个任务新建一次 LLM 调用** —— 三个并行 LLM 调用会消耗三份额度（教学上无妨，生产需考虑限流）。
- ⚠️ **无超时/重试** —— LLM 调用失败会抛异常并中断该线程。

**教材问题（文件头注释实录）**：
> 核心痛点：状态污染与响应混乱——如果上下文无法有效隔离，多任务并发时，历史对话、任务参数极易相互渗透，导致智能体逻辑错乱，无法准确响应用户需求。
> 技术方案：动态切换与作用域隔离——• 上下文切换：实现上下文环境的动态加载、暂停、恢复与清除，确保任务间无残留。• 上下文隔离：引入命名空间与任务ID机制，严格管理每个任务上下文的生命周期，物理与逻辑上双重隔离。
> 改写前的问题：1) `qwen_agent.Message`——虚构消息类（实际就是 `{"role":..., "content":...}` 字典）；2) `qwen_agent.Agent`——虚构框架（`Agent()` 无参实例化后 `chat()` 是虚构 API）；3) `AgentTask.run()` 内部的 `agent.chat()` 是唯一真实 LLM 调用点（原代码每次调都新建 Agent 实例）。

---

### F-07 `07_状态同步与锁控制策略.py`（119 行）——锁控制篇

**意图**：解决「**竞态条件、数据覆盖**」——引入互斥锁，把共享状态的关键读写标记为**临界区**。

**SharedLog 契约（本篇灵魂，原样保留）**：
```python
class SharedLog:
    def __init__(self):
        self.logs: List[str] = []
        self.lock = threading.Lock()

    def write_log(self, agent_name: str, message: str):
        with self.lock:                              # ← 临界区开始
            entry = f"[{agent_name}]：{message}"
            print(f"→ 写入日志：{entry}")
            self.logs.append(entry)
            time.sleep(0.5)                          # 模拟写入延迟（原样保留）
        # 临界区结束：with 块退出时自动释放锁

    def read_logs(self) -> str:
        return "\n".join(self.logs)
```

**关键契约**：
- **`with self.lock:` 是 `acquire()` / `release()` 的语法糖** —— 异常时也能保证释放（比手写 `try/finally` 安全）。
- **`time.sleep(0.5)` 在锁内是刻意的** —— 它**放大临界区耗时**，让「3 个线程串行写入 ≥ 1.5 秒」肉眼可见。**这是教学演示，不是生产写法**（见风险）。

**LoggingAgent 契约（线程 + 独立 LLM）**：
```python
class LoggingAgent(threading.Thread):
    def run(self):
        print(f"→ {self.name}开始处理任务")
        response = dashscope.Generation.call(model="qwen-plus", messages=[{"role":"user","content":self.query}], ...)
        self.response = response.output.choices[0].message.content
        self.shared_log.write_log(self.name, self.response)   # ← 加锁写入
        print(f"→ {self.name}完成写入")
```
⚠️ **注意 `LLM 调用` 在锁外、`write_log` 在锁内** —— 这是**正确**的设计（慢操作不该进临界区）。**对比 `sleep(0.5)` 在锁内**——形成「什么该进锁内」的对照。

**主流程契约**：
```python
queries = ["请分析中国当前的宏观经济政策", "请概述当前全球通货膨胀形势", "请简要预测人工智能在2025年的发展趋势"]
agents = [LoggingAgent(f"Agent_{i+1}", shared_log, q) for i, q in enumerate(queries)]
for agent in agents: agent.start()
for agent in agents: agent.join()
```

**验收标准**：
- V-07-A：三个 `→ Agent_N开始处理任务` **连续出现**（证明并行启动 LLM）。
- V-07-B：`→ 写入日志：[Agent_N]：...` **不交错**——每次 `print` 后紧跟完整 `entry`，绝不会出现两条日志字符混杂。
- V-07-C：**写入顺序随机**（哪个 LLM 先返回不确定），但**每条都完整**。
- V-07-D：`--- Qwen3.0输出总结 ---` 后输出基于三条日志的总结。

**核心教学点（锁的语义与代价）**：
> **锁保证「不交错」，不保证「顺序」** —— 三个线程谁先拿到锁是随机的（取决于调度），但一旦进入临界区就独占。
> **顺序随机 ≠ 出错** —— 日志条目顺序变化是可接受的；**交错（字符混杂）才是错误**。

**已知风险 / 诚实标注（本篇最有价值的反模式启示）**：
- 🔴 **锁内做耗时操作是反模式** —— 本篇为了教学把 `sleep(0.5)` 放进临界区，3 个线程 × 0.5s = **写入阶段至少 1.5 秒纯串行等待**。**生产级做法**：锁内只塞队列（微秒级操作），锁外由专门线程消费 —— **生产者-消费者模式**（见缺口 G-11）。
- ⚠️ **`read_logs()` 无锁** —— 读取时若仍有线程在写，理论上可能读到中间状态（Python 中 `"\n".join(list)` 对正在 append 的 list 会抛 `RuntimeError: list changed size during iteration` 吗？—— 不会，`join` 内部先取长度快照；但**语义上仍不安全**）。
- ⚠️ **`self.name` 覆盖 `Thread.name`** —— `LoggingAgent` 继承 `threading.Thread` 并赋值 `self.name`，**覆盖了 Thread 的内置 `name` 属性**（Python 3.10+ 中 `Thread.name` 是 property，赋字符串可以但不规范）。
- ⚠️ **LLM 调用失败无捕获** —— 线程内异常静默（同 05 篇）。
- ⚠️ **`Lock` 非可重入** —— 若 `write_log` 内部再调一个也加同一把锁的方法，会**死锁**（本例无此问题，但读者需知道 `RLock` 的存在）。

**教材问题（文件头注释实录）**：
> 核心问题：在并发环境中，若多个智能体同时对共享状态进行读写操作，极易引发竞态条件、数据覆盖或逻辑错误，破坏系统的稳定性。
> 解决方案：同步与互斥——• 状态同步：对关键共享资源的读写逻辑进行严格的序列化与受控管理。• 锁控制：引入互斥锁(Mutex)或读写锁(RWLock)，将关键代码标记为"临界区"，强制保证在任意时刻只有一个线程能进入执行。
> 改写前的问题：1) `qwen_agent.Agent/Message`——虚构框架；2) `LoggingAgent.run()` 内每次新建 `Agent()` 实例再 `chat()`（虚构 API）；3) 主控的 `summary_agent = Agent()` 同样是虚构实例化；4) `write_log` 里的 `time.sleep(0.5)` 模拟写入延迟（教材刻意为之，保留原样——它让"锁内临界区耗时"变得肉眼可见，**3 个线程串行写入 = 至少 1.5 秒**）。
> 【特别说明】教材提到 `读写锁(RWLock)`，但**代码只用了 `Lock`（互斥锁）**——Python 标准库无内置 RWLock，读写锁是「读共享、写互斥」的优化，本例未实现。**这是教材描述与实现的落差**。

---

### F-08 `08_agnet之间交互元信息例子.py`（21 行）——通信协议篇（纯注释）

**意图**：给出一条 **Agent 间通信消息的完整结构定义** —— 这是 01-07 所有「Agent 间数据传递」的**正式化信封**。

**消息结构契约（完整 JSON）**：
```json
{
  "id": "msg-20240503-00123",
  "timestamp": "2025-05-03T13:45:27Z",
  "from": "agent:task_dispatcher",
  "to": "agent:data_parser",
  "type": "command",
  "priority": 2,
  "context_ref": ["mem-1001", "task-req-879"],
  "payload": {
    "function": "parse_table",
    "args": {"file_url": "https://data.gov.cn/table.csv", "columns": ["region", "gdp"]}
  },
  "auth": {"token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...", "signature": "b1a927ec3..."}
}
```

**字段契约表**：

| 字段 | 类型 | 语义 | 对应前面哪一篇 |
|---|---|---|---|
| `id` | str | 消息唯一标识（前缀 `msg-` + 日期 + 序号） | — |
| `timestamp` | str | ISO 8601 UTC 时间戳 | — |
| `from` / `to` | str | 收发方标识（前缀 `agent:`） | 01/02 的调用关系 |
| `type` | str | 消息类型（本例 `command`；可扩展 `query`/`response`/`event`） | 03/04 的调度指令 |
| `priority` | int | 优先级（与 04 篇的 `Task.priority` 同族） | **04 篇** |
| `context_ref` | list | 上下文引用（关联的记忆/任务 ID） | **02/06 篇**的状态与上下文 |
| `payload` | obj | 业务负载：`function` + `args`（**本质是 function calling 的参数**） | 全章的工具调用 |
| `auth` | obj | 认证：`token` + `signature`（**签名验签**） | —（本章未实现） |

**⚠️ 本篇无任何可运行代码** —— 纯注释 JSON 示例，不需要（也不能）执行。

**验收标准**：
- V-08-A：文件可被 `python` 解析（注释 + 裸 JSON 块）—— ⚠️ 见风险。
- V-08-B：grep 关键字 `payload` / `context_ref` / `auth` / `priority` 均命中。
- V-08-C：_无运行输出_（纯设计参考）。

**已知风险 / 诚实标注**：
- 🔴 **裸 JSON 块会让文件无法运行** —— 文件第 3-22 行是一个裸露的 `{...}` JSON 字面量，**不在任何字符串/注释中**。Python 解析到第 3 行 `{` 会把它当作**集合/字典字面量表达式**，到 `"id": "msg-..."` 处报 `SyntaxError`。**该文件不是合法 Python 源码**（见缺口 G-12）。
  - 教材本意应是 `"""..."""` 包裹的字符串或全行注释。**建议修复**：给 JSON 块加三引号包裹。
- ⚠️ **文件名拼写错误** —— `agnet` 应为 `agent`（见缺口 G-13）。**保留原样**作为教材勘误证据。
- ⚠️ **`auth.signature` 无验签算法说明** —— 只有字段名，无实现（本章未涉及安全层）。
- ⚠️ **`type` 枚举未定义** —— 只给了 `command` 一个值，未给出完整类型枚举（对比 char10 的 A2A 协议有完整的 `TaskState` 枚举）。

**教材问题（文件头注释实录）**：
> `# 9 Agent间通信协议格式`
> `# 以Qwen3.0智能体系统中应用的标准通信格式为例，一条完整的Agent通信消息如下所示（结构化抽象）：`
> 【结构性缺陷】教材把这 21 行当成一个独立「例子文件」，但内容其实是**一段需要包在字符串或代码块里**的 JSON——直接保存为 `.py` 会 `SyntaxError`。教学上它是有价值的**设计参考**（字段设计很完整：标识/时间/收发/类型/优先级/上下文引用/负载/认证八要素），但**不能作为可运行例子**。

---

## 7. 全章验收清单（V-01 ~ V-14）

### 7.1 运行层验收

| 编号 | 验收项 | 期望 |
|---|---|---|
| V-01 | `python 01_...py` | 三步调度链日志 + 财经顾问报告（含 GDP 数字） |
| V-02 | `python 02_...py` | 3 条 `[状态更新]` + 完整用户报告 |
| V-03 | `python 03_...py` | 轮询严格 1→2→3；加权随机且 agent_3 偏多 |
| V-04 | `python 04_...py` | 顺序 `fetch_news→model→report→graph`，总耗时 ≥4s |
| V-05 | `python 05_...py` | 三条「启动」连续 + 总耗时 ≈1.7s + 加速比 ≈2.59x |
| V-06 | `python 06_...py` | 每个 task 2 条消息、角色序列 `['user','assistant']` |
| V-07 | `python 07_...py` | 日志不交错、顺序随机；写入阶段 ≥1.5s |
| V-08 | `python 08_...py` | **预期 `SyntaxError`**（裸 JSON 块）——记录为已知缺陷 |

### 7.2 契约层验收

| 编号 | 契约 | 对应 | 验证方式 |
|---|---|---|---|
| V-09 | 无可执行 `from qwen_agent`（C-01） | 全章 | grep 只命中注释 |
| V-10 | 子 Agent 均为纯类 + `name/description`（C-02） | 01-05 | grep `class XxxAgent` |
| V-11 | LLM 调用均带 `result_format='message'`（C-03） | 01-07 | grep 命中 8 处（06 篇 2 次） |
| V-12 | 每个文件有 `os.environ.get('DASHSCOPE_API_KEY')`（C-04） | 01-07 | grep 命中 7 处 |
| V-13 | 骨架类（SharedState/TaskDispatcher/TaskExecutor/ParallelExecutor/ContextScope/SharedLog）均存在且方法名完整（C-05） | 02-07 | grep 类名与 5-6 个方法名 |
| V-14 | 每个文件头含「改写前的问题」+「改写策略」（C-08） | 01-07 | grep 关键词 |

### 7.3 学习层验收

- [ ] 能说出 01（直接传递）与 02（黑板共享）的**代码级**差异（`call(summary)` vs `call("")` + 状态池）。
- [ ] 能默写 `counter % N` 轮询调度。
- [ ] 能解释「重池实现加权」为什么等价于按权重概率。
- [ ] 能说出 04 篇为什么 `report` 先于 `graph` 执行。
- [ ] 能解释 05 篇 `start()` 在循环内、`join()` 在循环外的必要性。
- [ ] 能说出 05 篇的加速比及其**真实原因**（`sleep` 释放 GIL，非 CPU 并行）。
- [ ] 能说出为什么 06 篇的「分桶隔离」优于「加锁保护共享 list」。
- [ ] 能指出 07 篇的反模式（`sleep` 在锁内）及生产级替代（生产者-消费者）。
- [ ] 能默写 08 篇消息信封的八个字段。

---

## 8. 已知缺口与后续改进（Gap Analysis）

| 编号 | 等级 | 缺口 | 影响 | 建议改进 | 对照章节 |
|---|---|---|---|---|---|
| G-01 | 🟠 | 全章 `os.environ.get('DASHSCOPE_API_KEY')` **无空值校验** | key 未设时报错晦涩 | 启动时校验并友好提示 | chapter12 |
| G-02 | 🟠 | 全章 **LLM 调用无 try/except + 无重试** | 网络抖动直接中断线程/脚本 | 加重试 + 异常兜底 | chapter08（降级） |
| G-03 | 🟠 | 01/02 篇**幻觉放大链**（上游硬编码 → 下游编造细节） | 报告可信但全是幻觉 | 数据源加校验 + prompt 加约束 | chapter08-02 |
| G-04 | 🟠 | 02 篇状态池**无 key 命名规范/无类型约束** | 写错 key 静默返回 `None` | 定义 key 常量 + TypedDict | chapter05（TypedDict） |
| G-05 | 🟠 | 03 篇**权重小样本不收敛**（3 次 ≠ 60%） | 演示给人错误印象 | 演示改成 100 次 + 统计打印 | — |
| G-06 | 🟠 | 04 篇 **DAG 无环检测** | 循环依赖 → 静默不执行任何任务 | 加入环检测 + 报错 | — |
| G-07 | 🟠 | 04 篇 `Task.func` **无参**，下游拿不到上游 `result` | 任务间无法真正传数据 | 改为 `func(**deps_results)` | chapter05（状态传递） |
| G-08 | 🟠 | 05 篇**未说明 GIL 与选择原则** | 误以为 threading 能加速 CPU 任务 | 补注释：I/O→threading、CPU→multiprocessing | — |
| G-09 | 🟠 | 06 篇 `ContextScope.contexts` **顶层 dict 无锁** | 并发 `create()` 严格说有竞争 | 加锁或用 `defaultdict` + 文档说明 | — |
| G-10 | 🟠 | 06 篇 `append()` **静默忽略**未创建的 task_id | 忘调 `create()` → 消息丢失无警告 | 改为自动创建或抛异常 | — |
| G-11 | 🔴 | 07 篇**锁内做耗时操作**（`sleep(0.5)`） | 反模式，教学演示但易被误学 | 注释强化 + 给出生产者-消费者替代 | — |
| G-12 | 🔴 | 08 篇**裸 JSON 块导致 `SyntaxError`** | 文件无法运行 | 用 `"""..."""` 包裹 JSON | — |
| G-13 | 🟡 | 08 篇**文件名拼写错误**（`agnet` → `agent`） | 文件名不规范 | 重命名（可保留原文件作勘误） | — |
| G-14 | 🟡 | 全章**无日志框架**（全用 `print`） | 无法控制级别/输出到文件 | 引入 `logging` | — |
| G-15 | 🟡 | 05/06/07 篇**无 `join(timeout=)`** | 线程卡死则永久阻塞 | 加超时 + 超时后清理 | — |
| G-16 | 🟡 | 全章**并发量硬编码为 3** | 无法体现规模化行为 | 参数化 + 压力测试 | chapter12 |
| G-17 | 🟡 | 07 篇**读了但未用读写锁**（教材提 RWLock 但代码只有 Lock） | 描述与实现落差 | 注释说明 or 实现 RWLock | — |
| G-18 | 🟡 | 全章**无 `destroy()` 调用**（06 篇定义了但没用） | 长跑内存持续增长 | 任务结束后回收上下文 | — |

### 缺口优先级建议

- **P0（正确性）**：G-11（锁内耗时反模式）、G-12（08 篇 SyntaxError）
- **P1（教学准确性）**：G-05（权重小样本）、G-08（GIL 说明）、G-17（RWLock 落差）
- **P2（健壮性）**：G-01、G-02、G-06、G-07、G-09、G-10、G-15、G-18
- **P3（整洁）**：G-04、G-13、G-14、G-16

---

## 附录 A：统一改写范式（全章共用替换表）

```python
# ===== 教材原写法（不可运行） =====
from qwen_agent.agent import Agent
from qwen_agent.context import Message
from qwen_agent.tools import Tool

class MyAgent(Tool):
    def __init__(self):
        super().__init__(name="my_agent", description="...")
    def call(self, query: str) -> str:
        return "..."

agent = Agent(tools=[MyAgent()])
result = agent.chat(messages=[Message(role="user", content="...")])

# ===== 改写后（可运行） =====
import os
import dashscope
dashscope.api_key = os.environ.get('DASHSCOPE_API_KEY')

class MyAgent:                          # ← 去掉虚构继承
    def __init__(self):
        self.name = "my_agent"           # ← 属性替代 super().__init__
        self.description = "..."
    def call(self, query: str) -> str:
        return "..."

response = dashscope.Generation.call(    # ← 替换 agent.chat()
    model="qwen-plus",
    messages=[{"role": "user", "content": "..."}],   # ← Message → dict
    temperature=0.3,
    max_tokens=512,
    result_format='message'               # ← 必填
)
result = response.output.choices[0].message.content
```

## 附录 B：三种协作模式对照（01 vs 02 vs 05-07）

| 维度 | 直接传递（01） | 黑板共享（02） | 并行+隔离+同步（05-07） |
|---|---|---|---|
| 耦合度 | 高（上下游紧耦合） | 低（写入者/读取者解耦） | 极低（各跑各的） |
| 数据流 | 单向链式（返回值传递） | 多写多读共享池 | 各线程独立 + 少量共享写 |
| 并发 | 串行 | 串行（本系列实现） | **真正并行** |
| 调度 | 主控硬编码顺序 | 主控硬编码顺序 | 无明显顺序（并行） |
| 适用 | 固定流水线 | 共享上下文的多 Agent | 独立任务 + 需要汇总 |
| 风险 | 上游低质量 → 下游幻觉放大 | 黑板成瓶颈 | 并发安全（隔离 + 锁） |
| 代表代码 | `forecast_tool.call(summary)` | `report_tool.call("")` | `Thread.start/join` + `Lock` |

## 附录 C：调度策略对照（03 vs 04）

| 维度 | 03 轮询 | 03 加权 | 04 DAG |
|---|---|---|---|
| 决策函数 | `counter % N` | `random.choice(pool)` | `heappop` 取 `-priority` 最小 |
| 前提 | 无依赖，Agent 等价 | 无依赖，Agent 有权重 | **有依赖约束** |
| 分配 | 严格均匀 | 概率性（按权重） | 先解锁后择优 |
| 数据结构 | 计数器 | 重池 list | 优先级堆（heapq） |
| 收敛性 | N 次一循环（完全确定） | **小样本不收敛** | 完全确定（给定图与优先级） |
| 复杂度 | O(1) | O(1)（`random.choice`） | O(V+E)（每步扫描全表解锁） |
| 风险 | 忽略 Agent 性能差异 | 小样本误判 | 无环检测 |

## 附录 D：并发安全三原则的代码位置

| 原则 | 代码位置 | 关键行 |
|---|---|---|
| ① 能隔离就不共享 | `06_上下文切换与隔离设计.py` `ContextScope` | `self.contexts[task_id] = []`（每任务独立桶） |
| ② 能用免锁工具就不手写锁 | （本章未演示）`queue.Queue` | —— |
| ③ 必须共享时才用 Lock | `05` `ParallelExecutor.lock` / `07` `SharedLog.lock` | `with self.lock:` |

## 附录 E：五条跨章关联

| 本篇 | 关联章节 | 关联点 |
|---|---|---|
| 02 `SharedState` | char02-03 `PersistentJSONMemory` | JSON 持久化思想同族（内存版 vs 落盘版） |
| 03 `dispatch()` | char05-02 LangGraph 条件边 | **路由函数同一家族** |
| 04 `TaskExecutor` | char08-01 状态机 | 状态建模思想同族（DAG 就是状态图） |
| 05 `Threading` | char05-10 多 Agent 广播图 | **fan-out 同一家族**（框架版 vs 手写版） |
| 07 `write_log` | char07-05 持久化日志 | 追加写 + 时间戳同族 |

**核心认识**：生产级多 Agent 框架只是把本篇的手写模式（直接传递 / 黑板 / 调度 / 并发 / 协议）做成了**声明式 API**——理解了本篇七篇的手写逻辑，再看任何多 Agent 框架都不会觉得是黑盒。

| 生产框架 | 对应本篇概念 | 升级点 |
|---|---|---|
| AutoGen（微软） | 01 直接传递 + 08 通信协议 | 自动消息路由、人工介入、代码执行 |
| CrewAI | 02 黑板共享 + 03 调度策略 | Role 定义、Process 编排、Memory 持久化 |
| LangGraph 多 Agent | 04 DAG + 05 并行 | 声明式图拓扑、checkpoint、human-in-the-loop |
| MetaGPT | 01-07 全部 + 08 协议 | 软件公司角色扮演、SOP 流水线 |
