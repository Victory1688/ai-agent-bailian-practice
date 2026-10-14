# 第 7 章 规范说明书（spec.md）——上下文工程：表示 / 路由 / 持久化 / 合并

> **SDD 定位**：本文回答 *「上下文（context）本身怎么设计」*。
> **上篇（意图与学习路径）**回答 *为什么学、学什么、怎么学*；
> **下篇（契约与验收）**回答 *每个文件到底承诺了什么、怎么验证、还缺什么*。
> **主线**：char01-06 都在「**用**」上下文（`messages` 列表、LangGraph `State` 字典、RAG 检索结果），
> 但从未「**设计**」上下文。char07 是全系列**第一次把上下文当作一等公民**——
> 从**数据结构定义**（01/02）→ **路由分发**（03/04）→ **持久化存储**（05/06）→ **筛选合并**（07），
> 完整覆盖上下文的**全生命周期**。
>
> 适用范围：`D:/AiWorkOut/aiAgentCode/chapter07/`（7 个 .py / 847 行）。
> 契约字段一律**从代码事实反推**，不臆造；教材简化点与改写依据一并留痕。

---

# 上篇：意图与学习路径

## 1. 章意图（Why）

### 1.1 教材原版想解决什么

教材用一章讲「上下文工程」，把上下文当作独立工程对象，拆成四层：

| 教材概念 | 想说明什么 |
|---|---|
| 上下文段结构化表示 | 一段上下文应包含**哪些字段**（role/content/type/task_id/meta）才能既**可追溯**又**可恢复** |
| 多段标注的智能体系统 | 用 **system / memory / input / tool** 四类标注，把「该怎么说话 / 用户喜欢什么 / 事实是什么」分门别类 |
| 上下文标注与路由机制 | 用户请求 → **关键词路由** → 分发到不同处理模块（qwen / deepseek / tool） |
| 模型分支路由与入口决策 | 单一模型无法兼顾专业度与效率，需要**模型网络 + 入口决策**（qwen / deepseek / hybrid） |
| 持久化上下文日志 | **JSONL 追加写**——任务恢复、用户画像、故障审计的基础 |
| 提示词缓存与快速回放 | **MD5 hash + JSON 覆盖写**——高频 prompt 直接复用，避免重复构建 |
| 动态上下文合并策略 | **分类 / 加权 / 裁剪 / 重排序**——在 Token 限制下选出信息密度最高的组合 |

### 1.2 教材原版的三大断点

本章 7 个例子**全部无法直接运行**，卡在三处：

| 断点 | 涉及例子 | 具体表现 |
|---|---|---|
| 🔴 **虚构框架 `qwen_agent`** | 01-07 全部 | `from qwen_agent.agent import Agent` / `from qwen_agent.tools import Tool` / `from qwen_agent.context import Message` —— 该框架在真实环境不存在（char02 起已多次确认），`ImportError` |
| 🔴 **虚构 Tool 继承 + 虚构 Agent 实例化** | 01-07 全部 | `class XxxTool(Tool): super().__init__(name=..., description=...)` 与 `agent = Agent(tools=[...]); agent.chat(messages=[Message(...)])` |
| 🟠 **相对路径写文件（不在脚本目录）** | 05/06 | `LOG_FILE = "agent_context_log.jsonl"` / `CACHE_FILE = "prompt_cache.json"` —— **相对路径的基准是「运行目录」而非「脚本目录」**，日志/缓存会落到不可预期的位置（char06 gensim 相对路径的同款教训） |

另外两个**教材简化点（刻意为之，保留）**：
- 01/02/03/04/06/07 篇的 **DeepSeek 全是模拟函数**——`call_deepseek_v1()` / `call_deepseek_tool()` / `call_deepseek_module()` / `call_deepseek()` / `EconomicPredictor.call()` / `MacroForecastTool.call()`，直接返回拼好的假字符串。**标题里的「DeepSeek」是教材的营销标签，同 char06-09 的假标题**。
- 06 篇的 `tool_output` 是**硬编码字符串**，未真实调 `EconomicPredictor.call()`（教学简化）。

### 1.3 本章改写要解决什么

| 教材原实现 | 改写后 | 教学点 |
|---|---|---|
| `from qwen_agent.agent import Agent` | `import dashscope` + `dashscope.Generation.call` | 唯一的真实 LLM 调用点变得可见 |
| `from qwen_agent.tools import Tool` | 删除 | — |
| `from qwen_agent.context import Message` | 删除（03 篇 `build_context_message` 直接返回 dict） | Message 的真身就是 dict |
| `class XxxTool(Tool)` + `super().__init__(name=..., description=...)` | `class XxxTool:` + `self.name/self.description` 属性 | **最小改动**——类名与 `call()` 签名不变 |
| `agent.chat(messages=[Message(...)])` | `dashscope.Generation.call(model="qwen-plus", messages=[...], result_format='message')` | 参数语义一一对应 |
| `LOG_FILE = "agent_context_log.jsonl"`（相对） | `os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_context_log.jsonl")` | **绝对路径**——文件落到脚本目录 |
| `CACHE_FILE = "prompt_cache.json"`（相对） | 同上（脚本目录绝对路径） | 同上 |
| `call_deepseek_*` 模拟函数 | **原样保留** | 教学简化，注释说明「真接可走 openai-compatible」 |

**改写纪律**：本章是「**数据结构优先**」的章节——所有**纯 Python 数据结构与算法**原样保留：
`build_context_segment` / `build_segment` / `create_log_segment` / `persist_segment` / `determine_route` / `route_decision` / `hash_prompt` / `load_prompt_cache` / `save_prompt_cache` / `check_prompt_cache` / `dynamic_merge_context`。
**这些才是本章的教学资产**——它们是**框架无关**的，换成任何 Agent 框架都成立。

### 1.4 本章最该带走的三句话

1. **字段设计跟着用途走**——要按时间筛选就加 `timestamp`，要跨任务隔离就加 `task_id`。全章字段演进：01 篇**五字段**（role/content/type/task_id/meta）→ 05 篇**七字段**（+id/timestamp/model）→ 07 篇**四字段**（-task_id/meta +timestamp）。**字段不是越多越好，而是刚好够用**。
2. **持久化目的决定存储格式**——**审计日志用「追加写 JSONL」**（只增不减、每段即时落盘）、**缓存用「覆盖写 JSON」**（整体替换、一次写完）。格式差异直接反映**数据生命周期**的差异。
3. **标注前缀让 LLM 注意力更精准**——02 篇用 `[TYPE]`（`[SYSTEM]` / `[MEMORY]` / `[TOOL]`），07 篇升级为 `[ROLE-TYPE]`（`[USER-INPUT]` / `[ASSISTANT-RESPONSE]`）。**显式标注信息性质，是廉价而有效的 prompt 工程手段**。

---

## 2. 学习路径（7 文件 / 847 行）

按「表示 → 路由 → 持久化 → 合并」的四层顺序阅读：

| # | 文件 | 行数 | 核心机制 | 读完后你应能说出 |
|---|---|---|---|---|
| 01 | `01_上下文段结构化表示.py` | 106 | `build_context_segment` **五字段** + 摘要工具（取最近 4 段） | 上下文段应该包含哪些字段、为什么 |
| 02 | `02_多段标注的智能体系统.py` | 107 | **四类标注**（system/memory/input/tool）+ `[TYPE]` 前缀拼接 | 不同性质的上下文为什么要分类标注 |
| 03 | `03_具备多路由控制策略的agent.py` | 135 | `determine_route()` **if/elif 单关键词** + 硬编码子任务拆分 | 关键词路由的最小实现 + 它的脆弱性 |
| 04 | `04_模型分支路由与入口决策逻辑.py` | 117 | `route_decision()` **`any()` 生成器** + `HybridAnalysisTool` fan-out | 组合分支路由 + 多模型融合入口 |
| 05 | `05_结构化上下文段的持久化日志记录.py` | 126 | `create_log_segment` **七字段** + `persist_segment` **JSONL 追加写** | 审计日志的字段设计与写入策略 |
| 06 | `06_提示词缓存与快速回放机制.py` | 123 | `hash_prompt`（MD5）+ **缓存三件套** `load/save/check` | 精确匹配缓存的实现与加速比 |
| 07 | `07_动态上下文合并策略能力的agent.py` | 133 | `dynamic_merge_context` **三级筛选**（system 全留 → tool 最新 1 → 历史最近 4） | Token 预算下的上下文裁剪策略 |

### 阅读路线建议

- **第一遍（表示层 2 篇）**：01 → 02。**先看数据结构，再看怎么用**。01 定义了「一个上下文段长什么样」，02 演示「四类不同性质的段如何组装成完整 prompt」。注意 02 的 `build_segment` 与 01 的 `build_context_segment` **完全同构（只改了函数名）**。
- **第二遍（路由层 2 篇）**：03 → 04。03 是一对一路由（一个请求 → 一个模块），04 是一对多融合（一个请求 → 多模型 → 融合）。**对比两种写法**：03 用 `"x" in query` 硬拼，04 用 `any(k in query for k in [...])` 生成器表达式（**可扩展性明显更好**）。
- **第三遍（持久化层 2 篇）**：05 → 06。05 是**审计日志**（JSONL 追加），06 是**缓存**（JSON 覆盖）。**同样是「把东西存下来」，两种格式选择完全不同**——请对照理解「用途决定格式」。
- **第四遍（合并层 1 篇）**：07。把前面所有零件用起来——**从上下文池里挑信息，拼成最优 prompt**。
- **关键呼应**：
  - 01 / 02 / 07 的 `build_segment` 家族是同构演化（字段增减）。
  - 05 / 06 共用「脚本目录绝对路径」的路径处理模式。
  - 03 / 04 是同一个「路由」问题的两代写法（04 更好）。

---

## 3. 四条工程主线（本章反复出现的设计决策）

### 主线一：字段设计跟着用途走（三次演进）

| 篇 | 字段数 | 字段 | 为什么这样设计 |
|---|---|---|---|
| 01 | **5** | `role` / `content` / `type` / `task_id` / `meta` | 通用最小集——要区分角色、要分类、要隔离任务、要留扩展位 |
| 02 | **5** | 同上（函数名改 `build_segment`） | 与 01 同构，但 `type` 取值扩展到 `system`/`memory`/`tool` |
| 05 | **7** | `id` / `timestamp` / `task_id` / `role` / `type` / `model` / `content` | **审计日志要唯一标识、要按时间排序、要知道谁产生的内容** |
| 07 | **4** | `role` / `content` / `type` / `timestamp` | **合并策略要按时间倒序取最新**——`task_id`/`meta` 用不上就删掉 |

**核心认识**：**字段是「用途需求」的直接投影**。
- 要「按时间倒序取最新」→ 必须有 `timestamp`（07）；
- 要「跨任务隔离」→ 必须有 `task_id`（01/02/05）；
- 要「唯一标识一条记录」→ 必须有 `id`（05）；
- 要「知道是哪个模型产生的」→ 必须有 `model`（05）。

### 主线二：路由函数 = 确定性决策（03 的两代写法）

| | 03 篇 `determine_route` | 04 篇 `route_decision` |
|---|---|---|
| 写法 | `if "政策" in user_input or "法律" in user_input:` | `if any(k in query for k in ["政策", "法规", "概述", "总结"]):` |
| 扩展性 | 🔴 差——**加关键词要改代码结构**（`or` 链越写越长） | ✅ 好——**加关键词只改列表**（一行一个） |
| 可读性 | 尚可（关键词少时） | 更好（列表一目了然） |
| 分支数 | 4（qwen/deepseek/tool/default） | 4（qwen/deepseek/hybrid/default） |
| 函数签名 | `determine_route(user_input: str) -> str` | `route_decision(query: str) -> str` |
| 共同点 | **都是纯函数**——输入字符串，输出路由名，无副作用、无状态 | 同左 |

**为什么这是「同一家族」**：char05-02 的 LangGraph 条件边路由函数（`add_conditional_edges(node, route_fn, mapping)` 里的 `route_fn`）**就是这个模式**。理解了 03/04，再看 LangGraph 的路由就不再是黑盒。

### 主线三：持久化目的决定存储格式（05 vs 06）

| 维度 | 05 审计日志 | 06 提示词缓存 |
|---|---|---|
| 文件 | `agent_context_log.jsonl` | `prompt_cache.json` |
| 格式 | **JSONL**（一行一个 JSON 对象） | **JSON**（一个大字典） |
| 写入 | **`open(..., "a")` 追加写** | **`open(..., "w")` 覆盖写** |
| 粒度 | **每段即时落盘**（调一次写一次） | **一次写完整个字典** |
| 数据结构 | 无序的**流水账** → `readlines()[-5:]` 取最后 5 条 | 有键的**字典** → `cache[hash] = answer` |
| 为什么 | 审计要**只增不减、不可篡改、可追溯顺序**——追加写天然满足 | 缓存要**整体替换、快速查找**——覆盖写 + dict 天然满足 |
| 生命周期 | 永久保留 | 可淘汰（当前无淘汰策略 → 缺口 G-09） |

**核心认识**：**「追加写」适合流水（顺序敏感、只读历史）；「覆盖写」适合状态（当前值敏感、整体替换）**。这是所有存储设计的通用判断。

### 主线四：标注前缀让 LLM 注意力更精准（02 → 07 升级）

| 篇 | 前缀格式 | 例子 |
|---|---|---|
| 02 | `[{s['type'].upper()}] {s['role']}: {content}` | `[SYSTEM] system: 你是一位熟悉中国经济政策的政府咨询顾问...` |
| 07 | `[{seg['role'].upper()}-{seg['type']}] {content}` | `[USER-INPUT] 2022年GDP增长率是多少？` |

**02 → 07 的升级**：02 把 `type` 和 `role` 分开写（`[SYSTEM] system:` —— **冗余**，两个词说的是同一件事），07 合并成一个标签（`[USER-INPUT]` —— **紧凑且信息完整**）。

**为什么有效**：LLM 的注意力机制对**显式结构化标记**敏感——用 `[USER-INPUT]` 而不是裸文本，模型更容易把这段识别为「用户当前问题」而非「历史里的某句话」。

---

## 4. 学习检查清单（读完自测）

- [ ] 能默写上下文段的**五字段**结构（01）与**七字段**结构（05）。
- [ ] 能说出为什么 07 篇删掉了 `task_id` 和 `meta` 字段。
- [ ] 能说出「system / memory / input / tool」四类标注各自解决什么问题（02）。
- [ ] 能写出一个 `[TYPE]` / `[ROLE-TYPE]` 前缀拼接的代码片段。
- [ ] 能说出 03 篇 `determine_route` 与 04 篇 `route_decision` 的**写法差异**及各自的优劣。
- [ ] 能解释「为什么 04 篇的 `any(k in query for k in [...])` 比 03 篇的 `or` 链更好扩展」。
- [ ] 能说出 03 篇的 `tool` 分支**为什么永远不会触发**。
- [ ] 能说出 04 篇的 `hybrid` 分支**为什么永远不会触发**。
- [ ] 能说出 JSONL 追加写与 JSON 覆盖写各自适合什么场景。
- [ ] 能解释「MD5 精确匹配缓存」的加速比来源，以及它的**致命局限**（同义改写不命中）。
- [ ] 能默写 07 篇的三级筛选策略（system 全留 → tool 最新 1 → 历史最近 4）。
- [ ] 能说出 07 篇「按条数截断」的**锯齿效应**（可能把一问一答切成孤儿段）。

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
    def call(self, query: str) -> str: ...
```
**约束**：**类名与 `call()` 签名保持不变**（最小改动原则）。
**实例对照**：

| 文件 | 类名 | `call()` 签名 |
|---|---|---|
| 01 | `StructuredContextQueryTool` | `call(self, query: str) -> str` |
| 02 | `FiscalForecastTool` | `call(self, query: str) -> str`（**无 `self.description`**） |
| 03 | `DataSummaryTool` | `call(self, query: str) -> str` |
| 04 | `HybridAnalysisTool` | ⚠️ **`call(self, inputs: Dict[str, str]) -> str`**（**唯一的 Dict 输入签名**） |
| 05 | `DeepSeekPredictor` | `call(self, query: str) -> str` |
| 06 | `EconomicPredictor` | `call(self, query: str) -> str` |
| 07 | `MacroForecastTool` | `call(self, query: str) -> str` |

⚠️ **04 篇的 `call` 签名是特例** —— 它接收 `Dict[str, str]`（`{"policy": ..., "forecast": ...}`），因为它是 fan-out 融合工具。改写时**必须保留这个签名**（C-05 骨架约束）。

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
**验收**：grep `result_format='message'` 命中 01/02/03(×2)/04/05/06/07 共 8 处。

### C-04 API Key 来自环境变量

```python
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key
```
**已知风险**：无空值校验（见缺口 G-01）。

### C-05 数据结构与算法骨架必须原样保留

**约束**：以下**纯 Python 函数/类**逐字保留，不得重构：

| 篇 | 必须保留 |
|---|---|
| 01 | `build_context_segment(role, content, segment_type, task_id, meta=None)` + `StructuredContextQueryTool.call` 的「取最近 4 段」逻辑 |
| 02 | `build_segment(...)` 同构版 + 四类标注的组装顺序（system → memory → input → tool） |
| 03 | `determine_route(user_input) -> str` 的 if/elif 结构 |
| 04 | `route_decision(query) -> str` 的 `any()` 生成器写法 + `HybridAnalysisTool.call(Dict)` |
| 05 | `create_log_segment(...)` 七字段 + `persist_segment()` 的 `open(..., "a")` 追加写 |
| 06 | `hash_prompt` / `load_prompt_cache` / `save_prompt_cache` / `check_prompt_cache` 缓存三件套 |
| 07 | `dynamic_merge_context(segments, task_type) -> str` 三级筛选 |

**理由**：本章是「**数据结构教学章**」——这些函数本身就是教学内容，框架无关，是要带走的东西。

### C-06 模拟函数原样保留（不真接 DeepSeek）

**约束**：`call_deepseek_v1` / `call_deepseek_tool` / `call_deepseek_module` / `call_qwen3` / `call_deepseek` **不得**改为真实 API 调用。
**理由**：
- 教学重点是「**路由结构**」而非「多模型接入」；
- 真接 DeepSeek 会引入第二把 API Key + 第二套 SDK，偏离本章重心。

**但必须留痕**：注释中说明真接方式（01 篇已示范）：
```python
# 真接 DeepSeek 可以按 dashscope 兼容模式（openai-compatible）改写：
#   import openai; client = openai.OpenAI(base_url="https://api.deepseek.com")
```

### C-07 文件路径必须基于脚本目录（绝对路径）

**约束**：所有写文件的路径必须形如：
```python
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_context_log.jsonl")
```
**原写法注释保留**：`# 原写法：LOG_FILE = "agent_context_log.jsonl"（相对路径，写到运行目录而非脚本目录）`。
**理由**：char06 gensim 相对路径的同款教训——**相对路径的基准是「当前工作目录」而非「脚本目录」**，从别处 `python chapter07/05_...py` 运行会把日志写到调用者的目录。

### C-08 文件头注释必须包含三要素

**约束**：每个文件的头部注释块必须包含：
1. **核心矛盾/痛点**（教材原意）；
2. **改写前的问题**（编号列出：虚构框架 / 模拟函数 / 相对路径）；
3. **改写策略**（分条列出保留了什么、替换了什么）。

### C-09 「原写法（注释保留）」必须紧贴改写点

**约束**：每处改写都要在紧邻位置保留 `# 原写法：...` 注释。

### C-10 日志 `model` 字段如实填写（不美化）

**约束**：05 篇 `create_log_segment(..., model=..., ...)` 的 `model` 字段必须**如实**记录真实模型名（`qwen-plus`），不得沿用教材虚构的 `"qwen-3.0"`。
**实例**（05 篇注释）：
```python
# 原写法：model 字段为 "qwen-3.0"（教材虚构版本号），改写后如实记录
seg = create_log_segment("system", system_prompt, "system_prompt", "qwen-plus", task_id)
```
**理由**：日志的价值在于**真实可追溯**——写假版本号会让审计失去意义。

### C-11 实测发现写入注释（路由死代码 / 加速比）

**约束**：能实测验证的结论必须在注释中留痕。
**实例**：
- 03 篇：`sub_tasks[0] "分析2023年的财政数据"` 注释标 `route → tool`，但实际命中 `deepseek` 分支；**三个子任务没有一个同时含「调用」和「工具」，tool 分支永不触发**；
- 06 篇：缓存命中时 **13.8s → 0.78s（17.7x 加速）**。

**理由**：这是学习型代码最有价值的部分——**可复现的一手观察**。

### C-12 教材假标题如实标注

**约束**：教材中「标题与实现不符」的地方必须在注释中明确指认。
**实例**（01 篇注释）：
> 原代码注释说"调用DeepSeek-V1模型 API（此处用虚拟请求替代）"——确实是模拟，标题里的"DeepSeek"同 char06-09 的假标题，改写时保持原状。

---

## 6. 逐文件契约（F-01 ~ F-07）

---

### F-01 `01_上下文段结构化表示.py`（106 行）——五字段表示篇

**意图**：回答「**一个上下文段应该长什么样**」——在「可追溯、可恢复」与「灵活适应动态变化」之间取得平衡。

**核心数据结构契约（本篇灵魂，原样保留）**：
```python
def build_context_segment(role: str, content: str, segment_type: str, task_id: str, meta: Dict = None) -> Dict:
    """构建标准上下文段结构：五字段（role/content/type/task_id/meta）"""
    return {
        "role": role,           # 角色：user / system / tool / model
        "content": content,     # 上下文内容
        "type": segment_type,   # 段落类型：input / response / observation
        "task_id": task_id,     # 所属任务标识（跨任务隔离）
        "meta": meta or {}      # 附加元信息：时间戳、状态码、来源等
    }
```

**五字段语义契约**：

| 字段 | 类型 | 语义 | 为什么需要 |
|---|---|---|---|
| `role` | str | `user` / `system` / `tool` / `model` | 让 LLM 区分「谁说的话」 |
| `content` | str | 内容正文 | 信息载体 |
| `type` | str | `input` / `response` / `observation` | **让代码能按类型筛选**（见下） |
| `task_id` | str | 任务标识（本例 `t001`） | **跨任务隔离**——多任务共池时能分开 |
| `meta` | dict | 附加元信息（`source` / `is_mock` 等） | 扩展位——不污染核心字段 |

**摘要工具契约**：
```python
class StructuredContextQueryTool:
    def call(self, query: str) -> str:
        relevant = [seg for seg in self.segments if seg["type"] in ["input", "response"]]
        context_summary = "\n".join([f"{seg['role']}: {seg['content']}" for seg in relevant[-4:]])
        return f"【对话上下文】\n{context_summary}\n【用户问题】\n{query}"
```
**关键逻辑**：**先按 `type` 筛出 `input`/`response`，再取最近 4 段**——这是「字段设计服务用途」的第一个证据（因为有了 `type` 字段，才能做这个筛选）。

**主流程契约**：
- 构建 3 个段（user input → model response → user input），全部 `task_id="t001"`；
- `structured_prompt = context_tool.call("是否存在财政支出快速增长的趋势？")`；
- 调 qwen-plus 得到 `qwen_content`；
- 调 `call_deepseek_v1()` 得到 `deepseek_response`（模拟）；
- **追加 2 个新段**：`("model", qwen_content, "response", "t001")` 和 `("model", deepseek_response, "observation", "t001", meta={"source": "deepseek", "is_mock": True})`；
- `print(json.dumps(context_segments, ensure_ascii=False, indent=2))`。

**验收标准**：
- V-01-A：打印 `调用qwen-plus生成中……` + `--- qwen-plus 回答 ---` + `--- DeepSeek 辅助回答（模拟） ---`。
- V-01-B：`--- 当前上下文段结构（JSON） ---` 后输出 **5 个段**（3 初始 + 2 追加）。
- V-01-C：最后两段的 `type` 分别为 `response` 与 `observation`，后者 `meta` 含 `{"source": "deepseek", "is_mock": true}`。
- V-01-D：`json.dumps` 带 `ensure_ascii=False` —— **中文正常显示**（不是 `\uXXXX`）。

**已知风险 / 诚实标注**：
- ⚠️ **`meta` 是浅拷贝的默认值陷阱** —— `meta or {}` 每次返回新 `{}`（正确）；若写成 `def f(meta={})` 就是经典 Python 陷阱（**本例写法正确**，值得对照）。
- ⚠️ **`relevant[-4:]` 硬编码 4** —— 无 Token 预算意识（07 篇才涉及）。
- ⚠️ **两个模型的结果被平等地追加为 `response` 和 `observation`** —— 但 `observation` 的 `role` 写的是 `"model"`（语义上应是 `"tool"` 或 `"system"`），**role 与 type 的取值空间有重叠歧义**（见缺口 G-04）。
- ⚠️ **`call_deepseek_v1(prompt=...)` 结果被当事实使用** —— 明明是 `is_mock: True` 的假数据，却和真实 qwen 回答并列追加，**下游若不检查 `meta` 就会误用**（见缺口 G-05）。
- ⚠️ **`content` 无长度限制** —— 长文本会把上下文撑爆（07 篇才处理）。

**教材问题（文件头注释实录）**：
> 核心矛盾：如何在保证历史上下文可追溯、任务状态可恢复的同时，让上下文灵活适应任务的动态变化，避免状态僵化导致的逻辑失效？
> 解决方案：采用结构化上下文段表示，每个段包含角色、内容、类型、任务ID、元信息等字段，实现上下文的动态更新与恢复。
> 改写前的问题：1) `qwen_agent.Agent/Tool/Message`——虚构框架（char02 已多次确认不存在）；2) `call_deepseek_v1`——模拟函数（直接返回假数据），保持原样。

---

### F-02 `02_多段标注的智能体系统.py`（107 行）——四类标注篇

**意图**：解决「**上下文该分成哪几类**」——`system`（该怎么说话）/ `memory`（用户喜欢什么）/ `input`（用户问什么）/ `tool`（事实是什么）。

**段落构造契约（与 01 篇完全同构，仅函数名不同）**：
```python
def build_segment(role: str, content: str, seg_type: str, task_id: str, meta: Dict = None) -> Dict:
    """构建结构化上下文段（五字段结构，与 01 篇 build_context_segment 同构）"""
    return {"role": role, "content": content, "type": seg_type, "task_id": task_id, "meta": meta or {}}
```

**四类标注的组装契约（本篇核心教学资产，原样保留）**：

| 序 | 标注 | `role` | `type` | 内容 |
|---|---|---|---|---|
| 1 | **系统提示** | `system` | `system` | `"你是一位熟悉中国经济政策的政府咨询顾问，回答需专业、简明、有依据。"` |
| 2 | **记忆段** | `memory` | `memory` | `"用户偏好获取简明扼要的政策摘要，避免冗长表述。"` |
| 3 | **用户输入** | `user` | `input` | `"请预测2024年中国的财政收入趋势，并说明主要增长来源。"` |
| 4 | **工具结果** | `tool` | `tool` | `tool.call(user_question)` → `call_deepseek_tool()` 返回的假数据 |

**⚠️ 注意 `role` 与 `type` 取值不同** —— 与 01 篇不同，本篇的 **`role` 与 `type` 是两个独立维度**（`role="memory"` + `type="memory"`；`role="tool"` + `type="tool"`）。这实际是把 01 篇的语义更「标签化」了。

**拼接契约（`[TYPE]` 前缀）**：
```python
context_summary = "\n".join(
    [f"[{s['type'].upper()}] {s['role']}: {s['content']}" for s in segments]
)
```
**输出形态**：
```
[SYSTEM] system: 你是一位熟悉中国经济政策的政府咨询顾问，回答需专业、简明、有依据。
[MEMORY] memory: 用户偏好获取简明扼要的政策摘要，避免冗长表述。
[INPUT] user: 请预测2024年中国的财政收入趋势，并说明主要增长来源。
[TOOL] tool: [DeepSeek Tool] 对于'请预测2024年...'的结构化回答：预计2024年财政收入将增长5%左右...
```
⚠️ **注意 `[SYSTEM] system:` 的冗余** —— `type` 与 `role` 说的是同一件事（见主线四）。

**主流程契约**：拼成的 `final_prompt` 前置说明句：
```python
final_prompt = (
    f"以下是结构化上下文段（含系统提示、用户偏好、工具数据和用户问题），"
    f"请基于这些内容给出准确回答：\n{context_summary}"
)
```

**验收标准**：
- V-02-A：打印 `调用qwen-plus生成中……` + `--- qwen-plus 回答 ---`。
- V-02-B：`--- 当前上下文段结构 ---` 后输出 **4 个段**（system / memory / input / tool）。
- V-02-C：回答**体现了系统提示的风格约束**（专业、简明）。
- V-02-D：回答**引用了工具结果**（财政收入增长 5% 左右）。

**已知风险 / 诚实标注**：
- ⚠️ **`FiscalForecastTool` 没有 `description` 属性** —— 其他篇的改写工具类都有 `self.name` + `self.description`，本篇只有 `self.name`（**不一致**）。它的 `call()` 直接转发给 `call_deepseek_tool(query)`，**类本身无实质逻辑**（纯包装层）。
- ⚠️ **`[TYPE] {role}:` 的格式冗余** —— `[SYSTEM] system:` 重复表达同一信息（07 篇修正为 `[ROLE-TYPE]` 单标签）。
- ⚠️ **`memory` 段是硬编码的一句话** —— 没有真正的长期记忆存储/检索（对比 char02-03 的 `PersistentJSONMemory`，见缺口 G-06）。
- ⚠️ **`task_id` 全是 `"t001"`** —— 单任务演示，未体现跨任务隔离的价值。
- ⚠️ **段顺序 = 拼接顺序，无优先级调整** —— 07 篇才涉及重排序。

**教材问题（文件头注释实录）**：
> 核心矛盾：如何在保证历史上下文可追溯、任务状态可恢复的同时，让智能体系统灵活适应任务的动态变化，避免状态僵化导致的逻辑失效？
> 解决方案：采用多段标注的智能体系统，整合三类关键信息——● 系统提示 (System) ——定义智能体的身份与行为风格；● 记忆信息 (Memory) ——保留历史交互，理解用户偏好；● 工具结果 (Tool) ——整合外部数据，辅助事实性推理。
> 三类标注组装成结构化上下文段，让 LLM 同时看到"该怎么说话"、"用户喜欢什么"、"事实是什么"。

---

### F-03 `03_具备多路由控制策略的agent.py`（135 行）——一对一路由篇

**意图**：解决「**用户请求该交给谁处理**」——用关键词匹配把请求路由到 qwen / deepseek / tool 三个模块。

**路由函数契约（本篇核心教学资产，原样保留）**：
```python
def determine_route(user_input: str) -> str:
    """根据关键词判断信息应路由到哪个模块"""
    if "政策" in user_input or "法律" in user_input:
        return "qwen"
    elif "数据" in user_input or "预测" in user_input:
        return "deepseek"
    elif "调用" in user_input and "工具" in user_input:
        return "tool"
    else:
        return "default"
```

**路由优先级契约（if/elif 从上到下）**：

| 序 | 条件 | 返回值 | 说明 |
|---|---|---|---|
| 1 | `"政策" or "法律"` | `qwen` | 政策法律类 → 主模型 |
| 2 | `"数据" or "预测"` | `deepseek` | 数据预测类 → 数据模型 |
| 3 | `"调用" and "工具"` | `tool` | **必须同时含两词** |
| 4 | 其他 | `default` | 兜底 |

**🔴 死代码契约（实测发现，必须标注）**：
```python
sub_tasks = [
    "分析2023年的财政数据",        # 教材注释：route → tool（实测：命中"数据" → deepseek）
    "预测2024年中国GDP的增长情况",  # route → deepseek（实测一致）
    "说明近期的主要财政政策"        # route → qwen（实测一致）
]
```
**两个致命事实**：
1. `sub_tasks[0]` 教材注释标 `route → tool`，但该句含「**数据**」→ 命中**第 2 个分支（deepseek）**；第 3 个分支被 `elif` 顺序**截胡**，**永远到不了**。
2. **三个子任务没有一个同时含「调用」和「工具」** → `tool` 分支两重意义上都是死代码。

**用户输入未使用契约（教材缺陷，必须标注）**：
```python
user_input = "请调用工具分析2023年的财政数据，并预测2024年中国GDP的增长情况，还要说明近期的主要财政政策。"
```
⚠️ **`user_input` 定义后从未被使用** —— 教材的子任务拆分是**硬编码的三条字符串**，与 `user_input` 无关。真实系统应由 LLM 完成「复杂请求 → 原子子任务」的拆分。

**上下文消息构造契约（Message → dict）**：
```python
def build_context_message(role: str, content: str) -> Dict:
    # 原写法：return Message(role=role, content=content)
    return {"role": role, "content": content}
```

**主流程契约**：`for task in sub_tasks:` → `route = determine_route(task)` → 四分支 if/elif → `responses.append(result)` → 最后 `for idx, res in enumerate(responses, 1): print(f"[子任务{idx}] {res}")`。

**验收标准**：
- V-03-A：`→ 已路由至 DeepSeek-V1 处理数据类任务。任务内容：分析2023年的财政数据`（**第 1 个子任务走 deepseek 而非教材注释的 tool**）。
- V-03-B：`→ 已路由至 DeepSeek-V1 处理数据类任务。任务内容：预测2024年中国GDP的增长情况`（第 2 个子任务）。
- V-03-C：`→ 已路由至 Qwen3.0 处理政策类任务。任务内容：说明近期的主要财政政策` + `调用qwen-plus生成中……`（第 3 个子任务走真实 LLM）。
- V-03-D：`--- 多模块合并响应 ---` 后输出 `[子任务1]` / `[子任务2]` / `[子任务3]` 三条。
- V-03-E：**`tool` 分支永不触发**（三个子任务都进不到第 3 个 `elif`）。

**已知风险 / 诚实标注**：
- 🔴 **路由死代码** —— `tool` 分支永不触发（双重原因：`elif` 顺序 + 关键词不满足）。**这是本篇最有价值的实测发现**（见缺口 G-02）。
- 🔴 **`user_input` 完全未使用** —— 拆分是硬编码的，不是从 `user_input` 推导的（见缺口 G-03）。
- ⚠️ **`"数据"` 与 `"工具"` 的语义重叠** —— 「分析2023年的财政**数据**」既像 tool 任务也像 deepseek 任务，关键词路由天然无法处理这种**语义交叉**（这正是 04 篇用 `any()` 列表 + hybrid 分支试图缓解的问题）。
- ⚠️ **子任务拆分无依赖关系** —— 三个子任务是**平铺**的，无 DAG（对比 char09-04 的 `TaskExecutor`）。
- ⚠️ **`responses` 无统一格式** —— 混装真实 LLM 回答与模拟字符串，下游无法区分真假。

**教材问题（文件头注释实录）**：
> 核心代码逻辑：1. 路由规则：定义 `determine_route()` 函数，基于预设关键词判断目标模块。2. 任务拆分：将复杂的用户请求，拆解为多个独立的原子化子任务。3. 循环执行：遍历子任务列表，逐个调用对应模块并行处理。4. 结果合并：汇总各模块返回结果，整理后统一输出给用户。
> 【额外发现（实测）】教材注释与实际路由行为不符——`sub_tasks[0]` "分析2023年的财政数据" 注释标 route → tool，但该句含"数据"且不含"调用"+"工具"，按 `determine_route()` 实际命中 deepseek 分支；**三个子任务没有一个同时含"调用"和"工具"，tool 路由分支永远不会触发**。

---

### F-04 `04_模型分支路由与入口决策逻辑.py`（117 行）——一对多融合路由篇

**意图**：解决「**单一模型无法兼顾专业度与效率**」——建立「模型网络」，按任务特征分发到最擅长的入口，并支持**多模型融合**。

**路由函数契约（与 03 篇对比，本篇写法更好）**：
```python
def route_decision(query: str) -> str:
    """根据语义关键词决策模型入口"""
    if any(k in query for k in ["政策", "法规", "概述", "总结"]):
        return "qwen"
    elif any(k in query for k in ["预测", "趋势", "估计", "数据"]):
        return "deepseek"
    elif any(k in query for k in ["综合分析", "多维度", "对比"]):
        return "hybrid"
    else:
        return "default"
```

**03 vs 04 写法契约对照**：

| 维度 | 03 `determine_route` | 04 `route_decision` |
|---|---|---|
| 关键词匹配 | `"政策" in q or "法律" in q` | `any(k in q for k in [...])` |
| 加关键词的改动量 | **改代码结构**（加 `or`） | **只加列表元素** |
| 每分支关键词数 | 1-2 | 4 |
| 分支名 | `tool` | `hybrid` |

**HybridAnalysisTool 契约（fan-out + fan-in，本篇章独有）**：
```python
class HybridAnalysisTool:
    def call(self, inputs: Dict[str, str]) -> str:
        """组合分析：内部调两个模拟模型，再拼接结果"""
        qwen_result = call_qwen3(inputs["policy"])
        deepseek_result = call_deepseek(inputs["forecast"])
        return f"[组合分析] 综合政策视角：{qwen_result}\n数据预测视角：{deepseek_result}"
```
⚠️ **这是全章唯一的 `Dict` 输入签名** —— 因为 fan-out 需要**多个输入**（一个给 qwen、一个给 deepseek）。

**主流程契约（覆盖三种路由 + default 兜底）**：
```python
user_queries = [
    "请概述近期财政补贴政策的主要方向",                    # → qwen（含"概述"、"政策"）
    "请预测2024年GDP增长趋势",                            # → deepseek（含"预测"、"趋势"）
    "请对近期财政补贴政策与经济增长趋势进行多维度综合分析"   # → hybrid（含"综合分析"、"多维度"）
]
```

**🔴 死代码契约（实测发现，必须标注）**：
> 第 3 条请求 `"请对近期财政补贴政策与经济增长趋势进行多维度综合分析"` **同时含「政策」（第 1 分支关键词）与「综合分析」「多维度」（第 3 分支关键词）** —— 按 `if/elif` 顺序，**第 1 分支先命中，`hybrid` 分支永远到不了**。

**验收标准**：
- V-04-A：第 1 条 → `→ Qwen3.0入口已触发。`（命中 qwen）。
- V-04-B：第 2 条 → `→ DeepSeek-V1入口已触发。`（命中 deepseek）。
- V-04-C：第 3 条 → **`→ Qwen3.0入口已触发。`**（**实测命中 qwen，而非教材预期的 hybrid**）。
- V-04-D：`=== 启动模型入口决策示例系统 ===` 后输出 3 组 `--- 处理第N条请求 ---` + `结果输出：`。
- V-04-E：**`hybrid` 分支与 `default` 分支均未触发**（`default` 的 qwen-plus 调用存在但未执行）。

**已知风险 / 诚实标注**：
- 🔴 **`hybrid` 分支死代码** —— 组**合类分支（hybrid/tool）必须放到最高优先级**，因为其关键词组常常同时包含其他分支的关键词。**这是本篇最有价值的教训**（见缺口 G-02）。
- ⚠️ **`default` 分支的真实 LLM 调用永不执行** —— 三条请求全被前三分支截获，`dashscope.Generation.call` 是**可达但未达**的代码（改写后仍保留，因为它示范了「兜底分支怎么接真实 LLM」）。
- ⚠️ **其余三个分支全走模拟** —— 只有 `default` 分支接了真实 qwen-plus。**结果：本篇运行时「没有一次真实 LLM 调用」**（教学上可以接受，但要如实说明）。
- ⚠️ **`HybridAnalysisTool` 的输入是硬编码的两个字符串** —— `{"policy": "财政补贴政策分析", "forecast": "2024年经济趋势"}`，与用户实际请求无关（同 03 篇 `user_input` 未使用的缺陷）。
- ⚠️ **`call_qwen3` / `call_deepseek` 是模拟函数** —— 名字里的「3.0」是教材虚构版本号。

**教材问题（文件头注释实录）**：
> 核心痛点：单一通用模型处理所有类型的请求时，无法兼顾专业度与响应效率，容易产生算力浪费和回答冗余，导致整体服务体验下降。
> 解决方案：引入"模型分支路由机制"与"入口决策逻辑"，构建模型网络。系统根据任务特征动态分发，精准匹配到最擅长的模型入口进行处理。
> 决策依据 & MCP支持：•维度：用户意图、上下文特征、任务类型、语言风格 •赋能：通过MCP协议在上下文段中嵌入路由指令与入口权重，实现精细化控制。
> 【实测发现】第 3 条请求同时含"政策"与"综合分析"/"多维度"，按 if/elif 顺序被第 1 分支截胡 —— **`hybrid` 分支永远不触发**。

---

### F-05 `05_结构化上下文段的持久化日志记录.py`（126 行）——审计日志篇

**意图**：解决「**任务中断后怎么恢复**」——用 **JSONL 追加写**记录每一次交互，支持状态恢复、用户画像、记忆维护、故障审计。

**七字段日志段契约（本篇核心教学资产，原样保留）**：
```python
def create_log_segment(role: str, content: str, segment_type: str, model: str, task_id: str) -> Dict:
    return {
        "id": str(uuid.uuid4()),                    # 唯一记录号：全局不重复
        "timestamp": datetime.now().isoformat(),    # 交互时间戳：ISO 8601 格式
        "task_id": task_id,                         # 任务编号：跨任务隔离
        "role": role,                               # 角色：system / user / tool / assistant
        "type": segment_type,                       # 类型：system_prompt / input / tool_output / response
        "model": model,                             # 模型来源：哪一方产生的内容
        "content": content                          # 内容体
    }
```

**七字段 vs 01 篇五字段的差异契约**：

| 新增字段 | 用途 | 为什么日志需要 |
|---|---|---|
| `id`（uuid4） | 唯一记录号 | 日志是**流水**——需要能精确定位到某一条 |
| `timestamp`（ISO 8601） | 交互时间 | 审计要**按时间排序/检索**；也天然成为**性能探针** |
| `model` | 模型来源 | 要区分「谁产生的内容」（真实 qwen vs 模拟 deepseek） |

**持久化写入契约（JSONL 追加写）**：
```python
def persist_segment(segment: Dict):
    """每段即时追加写入 JSONL 文件（一行一个 JSON 对象），不缓存不批量"""
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(segment, ensure_ascii=False) + "\n")
```
**关键设计**：
- **`"a"` 追加模式** —— 只增不减，永不覆盖历史；
- **`+ "\n"`** —— JSONL 的灵魂（每行一个独立 JSON 对象，可流式读取）；
- **`ensure_ascii=False`** —— 中文正常存（不是 `\uXXXX`）。

**路径契约（C-07）**：
```python
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_context_log.jsonl")
# 原写法：LOG_FILE = "agent_context_log.jsonl"（相对路径，写到运行目录而非脚本目录）
```

**主流程契约（4 段日志）**：

| 序 | `role` | `type` | `model` | 内容 |
|---|---|---|---|---|
| 1 | `system` | `system_prompt` | `qwen-plus` | `"你是中国国家财政专家助手，所有回答需简洁、严谨、有数据支撑。"` |
| 2 | `user` | `input` | `user` | `"请预测2024年中国GDP增长，并说明依据。"` |
| 3 | `tool` | `tool_output` | `deepseek-v1` | `tool.call(user_input)` |
| 4 | `assistant` | `response` | `qwen-plus` | 真实 qwen-plus 回答 |

⚠️ **`model` 字段有两种语义** —— 段 1/4 是**产生内容的模型**（`qwen-plus`），段 2 是**`user`**（人），段 3 是**`deepseek-v1`**（工具）。**同一个字段承载了「模型」和「来源」两种含义**（见缺口 G-07）。

**回读契约**：
```python
with open(LOG_FILE, "r", encoding="utf-8") as f:
    lines = f.readlines()[-5:]
    for line in lines:
        print(json.loads(line))
```
**`[-5:]` 取最后 5 条** —— JSONL 的行式结构让「读最后 N 条」天然高效（不用解析整个文件）。

**验收标准**：
- V-05-A：打印 `=== 持久化上下文日志系统启动 ===` + 三次 `→ 已调用 DeepSeek-V1 预测模块`。
- V-05-B：`--- 最终回答输出 ---` 后输出真实 qwen-plus 回答。
- V-05-C：`--- 最新上下文日志（展示最后5条） ---` 后输出 **5 个 dict**（含历史运行累计）。
- V-05-D：日志文件 `agent_context_log.jsonl` 存在于 **`chapter07/` 目录**（不是运行目录）。
- V-05-E：**多次运行后文件行数持续累加**（追加写的证据）。

**已知风险 / 诚实标注**：
- ⚠️ **`timestamp` 是免费性能探针** —— 前三段落盘是毫秒级，第 4 段（`response`）晚 **6.5 秒** = qwen-plus 真实耗时。**生产系统的性能审计靠这种时间差定位瓶颈**（见主线）。
- ⚠️ **JSONL 单文件无限增长** —— 无轮转（rotation）、无压缩、无索引，长期运行会变成大文件（见缺口 G-08）。
- ⚠️ **无并发写保护** —— 多进程/多线程同时 `open("a")` 写可能交错（POSIX 下小写入通常原子，但不保证）。
- ⚠️ **无敏感信息脱敏** —— 用户输入原样落盘（生产需脱敏/加密）。
- ⚠️ **`model` 字段语义混装**（见上）。
- ⚠️ **无 schema 版本号** —— 未来加字段会导致新旧日志不兼容。
- ⚠️ **`datetime.now()` 无时区** —— 跨时区部署时时间语义不明（建议 `datetime.now(timezone.utc)`）。
- ⚠️ **`readlines()` 全量加载** —— 只取最后 5 条却读了整个文件（大文件低效）。

**教材问题（文件头注释实录）**：
> 核心必要性：构建日志系统是实现以下关键能力的基础：• 任务中断后的状态恢复 • 长期用户画像的动态构建 • 多轮复杂对话的记忆维护 • 系统异常时的故障快速审计
> 关键日志字段：日志记录需包含高价值的元数据与内容：• 唯一任务编号 (task_id) • 交互时间戳 (timestamp) • 模型响应状态 (state) • 段落类型 / 模型来源 / 内容体
> 改写前的问题：1) `qwen_agent.Agent/Message/Tool`——虚构框架；2) `DeepSeekPredictor`——模拟工具（返回假数据），保持原样；3) `LOG_FILE` 相对路径——运行目录不一定是脚本目录，日志会写到不可预期的位置。
> 【注意】教材提到的 `state`（模型响应状态）字段在代码中**未实现** —— 实际字段是 `model`，教材描述与实现有落差。

---

### F-06 `06_提示词缓存与快速回放机制.py`（123 行）——提示词缓存篇

**意图**：解决「**重复的 prompt 构造与上下文拼接增加计算开销**」——缓存高频 prompt 的组合，命中则直接复用。

**缓存三件套契约（本篇核心教学资产，原样保留）**：

| 函数 | 签名 | 实现 |
|---|---|---|
| `hash_prompt(prompt)` | `str -> str` | `hashlib.md5(prompt.encode("utf-8")).hexdigest()` |
| `load_prompt_cache()` | `-> Dict[str, str]` | 文件不存在返回 `{}`；存在则 `json.load` |
| `save_prompt_cache(cache)` | `Dict -> None` | `open(..., "w")` + `json.dump(..., ensure_ascii=False, indent=2)` |
| `check_prompt_cache(prompt, cache)` | `(str, Dict) -> str` | 算 hash → `cache.get(h, "")`（**未命中返回空串**） |

**缓存决策契约（命中/未命中）**：
```python
cached_output = check_prompt_cache(full_prompt, prompt_cache)
if cached_output:
    print("\n--- 缓存命中，直接回放 ---")
    print(cached_output)
else:
    print("\n--- 未命中缓存，调用模型生成 ---")
    response = dashscope.Generation.call(...)          # 真实 LLM 调用
    generated_answer = response.output.choices[0].message.content
    prompt_cache[prompt_hash] = generated_answer        # 写缓存
    save_prompt_cache(prompt_cache)                     # 落盘
```
**关键机制**：**「未命中返回空串」+ `if cached_output:` 的假值判断** —— 简洁但有个前提（**空串不会是合法的缓存值**，见风险）。

**路径契约（C-07）**：
```python
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompt_cache.json")
# 原写法：CACHE_FILE = "prompt_cache.json"（相对路径，写到运行目录）
```

**prompt 构造契约（硬编码三段式）**：
```python
full_prompt = f"""【系统提示】
{system_prompt}
【外部工具输出】
{tool_output}
【用户提问】
{user_query}
请基于上述内容生成结构化分析结果"""
```
其中 `tool_output` 是**硬编码字符串** `"[Tool] 当前CPI指数为2.1%，PMI为51.4，消费同比上升6.2%"`（未真实调 `EconomicPredictor.call()`）。

**验收标准**：
- V-06-A（首次运行）：`--- 未命中缓存，调用模型生成 ---` + `调用qwen-plus生成中……` + 回答 + `当前缓存条目数量：1`。
- V-06-B（**第二次运行**）：`--- 缓存命中，直接回放 ---` + **相同回答** + `当前缓存条目数量：1`。
- V-06-C：第二次运行**无 `调用qwen-plus生成中……`**（**关键证据**——未调 LLM）。
- V-06-D：**加速比 ≈ 17.7x**（首次 13.8s → 二次 0.78s）。
- V-06-E：`prompt_cache.json` 存在于 `chapter07/` 目录，内含 1 个 `{md5hash: answer}` 键值对。

**已知风险 / 诚实标注（本篇最有价值的实测发现）**：
- 🔴 **MD5 精确匹配的致命局限** —— **prompt 一字不差才命中**；同义改写（「预测2024年GDP」vs「2024年GDP预测」）**永远不命中**。生产需升级为**语义缓存**（embedding 相似度 > 0.95 命中，需 char06 的 `DashScopeEmbeddings`）（见缺口 G-10）。
- ⚠️ **无缓存淘汰策略** —— 无 LRU / LFU / TTL，缓存**只增不减**（长期运行 → 文件膨胀 + 命中率下降）（见缺口 G-09）。
- ⚠️ **「空串 = 未命中」是有隐患的约定** —— 若 LLM 返回空串并被缓存，下次会误判为未命中（**重复调用 LLM**）。
- ⚠️ **`save_prompt_cache` 未做原子写** —— 直接 `open("w")` 覆盖，**写入过程中崩溃会损坏整个缓存文件**（应写临时文件 + `os.replace`）。
- ⚠️ **MD5 非抗碰撞** —— 虽然这里是缓存 key（非安全场景），但用 `hashlib.sha256` 更规范。
- ⚠️ **`tool_output` 硬编码** —— 未真实调 `EconomicPredictor.call()`（教材简化，**导致缓存内容本身是假的**）。
- ⚠️ **缓存的是「完整回答」而非「prompt 嵌入向量」** —— 无法复用不同但相似的 prompt（与语义缓存的根本差异）。
- ⚠️ **无缓存命中率统计** —— 只有 `len(prompt_cache)` 总数，无法知道命中率（**缓存的 ROI 无法度量**）。

**教材问题（文件头注释实录）**：
> 当前痛点与挑战：重复的提示词构造与上下文拼接过程，会显著增加系统的计算开销，不仅造成算力资源的浪费，还会直接导致用户侧的响应延迟，降低体验。
> 核心解决方案：引入"提示词(Prompt)缓存与快速回放"机制，识别并存储高频使用的提示词与上下文组合，在后续请求中直接复用，避免重复构建成本。
> 改写前的问题：1) `qwen_agent.Agent/Message/Tool`——虚构框架；2) `CACHE_FILE` 相对路径——同 05 篇 `LOG_FILE`，写到运行目录而非脚本目录；3) `tool_output` 是硬编码字符串——未真实调 `EconomicPredictor.call()`，教学简化。
> 【实测】缓存命中时 13.8s → 0.78s = **17.7x 加速**。前提是 prompt 一字不差（MD5 精确匹配）。

---

### F-07 `07_动态上下文合并策略能力的agent.py`（133 行）——合并策略篇

**意图**：解决「**无差别拼接所有上下文 → 输入超限 + 语义冲突**」——通过分类、加权、裁剪与重排序，选出信息密度最高的组合。

**四字段段结构契约（简化版）**：
```python
def build_segment(role: str, content: str, segment_type: str, timestamp: float = None) -> Dict:
    return {
        "role": role,
        "content": content,
        "type": segment_type,
        "timestamp": timestamp or time.time()
    }
```
⚠️ **比 01 篇少了 `task_id` 和 `meta`，但新增了 `timestamp`** —— 因为合并策略**要按时间倒序取最新**，`task_id`/`meta` 用不上就删（**字段跟着用途走的第三次演进**）。

**三级筛选合并契约（本篇核心教学资产，原样保留）**：
```python
def dynamic_merge_context(segments: List[Dict], task_type: str) -> str:
    """三级筛选合并：系统提示全保留 → 工具段留最新1条 → 交互历史留最近4条"""
    selected = []

    # 第一级：系统提示全保留（身份设定不可丢）
    system_segments = [s for s in segments if s["type"] == "system"]
    selected.extend(system_segments)

    # 第二级：工具段保留最新1条（按时间戳倒序取第一条——最新事实优先）
    tool_segments = sorted([s for s in segments if s["type"] == "tool"], key=lambda x: -x["timestamp"])
    if tool_segments:
        selected.append(tool_segments[0])

    # 第三级：最近交互保留2轮（input+response 合计最多4条，按时间戳倒序截断）
    history = sorted([s for s in segments if s["type"] in ["input", "response"]], key=lambda x: -x["timestamp"])
    selected.extend(history[:4])

    # 构造合并Prompt：每段前加 [ROLE-TYPE] 标注前缀
    merged = ""
    for seg in selected:
        prefix = f"[{seg['role'].upper()}-{seg['type']}]"
        merged += f"{prefix} {seg['content']}\n"
    return merged
```

**三级策略契约表**：

| 级 | 类型 | 保留策略 | 依据 | 理由 |
|---|---|---|---|---|
| 1 | `system` | **全部保留** | —— | 身份设定是全局约束，不可丢 |
| 2 | `tool` | **只留最新 1 条** | `-timestamp` 倒序取第 1 | 工具结果是「事实快照」——**最新的才有意义** |
| 3 | `input` / `response` | **留最近 4 条** | `-timestamp` 倒序截断 `[:4]` | 对话历史越近越相关（时间窗口策略） |

**标注前缀契约（02 篇的升级版）**：
```python
prefix = f"[{seg['role'].upper()}-{seg['type']}]"    # [USER-INPUT] / [ASSISTANT-RESPONSE] / [SYSTEM-SYSTEM] / [TOOL-TOOL]
```
**对比 02 篇**：`[SYSTEM] system:`（**两个词冗余**）→ `[SYSTEM-SYSTEM]`（更紧凑，但 system 段仍重复）。

**主流程契约（上下文池构建）**：

| 序 | `role` | `type` | 内容 |
|---|---|---|---|
| 1 | `system` | `system` | 国家政策与宏观经济专家 |
| 2 | `user` | `input` | `"2022年GDP增长率是多少？"` |
| 3 | `assistant` | `response` | `"2022年中国GDP增长为3.0%。"` |
| 4 | `user` | `input` | `"2023年预计呢？"` |
| 5 | `assistant` | `response` | `"2023年GDP增长约为5.2%。"` |
| 6 | `tool` | `tool` | `tool.call("2024年GDP预测")` |
| 7 | `user` | `input` | `"请基于历史数据与趋势，判断2024年GDP是否可能超过5.5%？"` |

**选取结果推演**：system 段 1 条 + tool 段最新 1 条（段 6）+ 历史最近 4 条（段 7/5/4/3） = **共 6 段**（段 2 被挤出）。

**验收标准**：
- V-07-A：打印 `=== 启动动态上下文合并策略系统 ===` + `→ DeepSeek-V1 调用中...`。
- V-07-B：`--- 合并后的Prompt结构 ---` 输出 **6 段**，前缀分别为 `[SYSTEM-SYSTEM]` / `[TOOL-TOOL]` / `[USER-INPUT]` / `[ASSISTANT-RESPONSE]` / `[USER-INPUT]` / `[ASSISTANT-RESPONSE]`。
- V-07-C：**`"2022年GDP增长率是多少？"`（段 2）未被选中**（被 `[:4]` 挤出）。
- V-07-D：`--- Qwen3.0 输出结果 ---` 后输出基于合并上下文的回答。
- V-07-E：回答**引用了 2022/2023 的增长数据**（证明历史被保留）。

**已知风险 / 诚实标注**：
- ⚠️ **「按条数截断」有锯齿效应** —— `history[:4]` 可能把**一问一答切成孤儿段**（比如只保留 `assistant` 的回复而丢了对应的 `user` 提问），导致 LLM 语境缺失。**生产应按「对话轮」成对截断**（见缺口 G-11）。
- ⚠️ **无 Token 预算控制** —— `[:4]` 是**条数**限制而非**Token 数**限制；若某段是长文本，4 条也可能超限（生产应用 `tiktoken` 计数）（见缺口 G-12）。
- ⚠️ **`task_type` 参数完全未使用** —— `dynamic_merge_context(segments, task_type)` 的 `task_type="forecast"` 传了但函数体**从不读它**。教材本意应是「按任务类型用不同策略」，**未实现**（见缺口 G-13）。
- ⚠️ **筛选是「规则粗筛」，无语义相关性** —— 只用 `type` 和时间戳，**没有按「与当前问题的语义相关性」挑选**。生产应升级为 **规则粗筛 + 语义精选**（用 char06 的 `DashScopeEmbeddings` 算相似度）。
- ⚠️ **`selected` 顺序 = 拼接顺序，未重排序** —— 教材导语说「分类、加权、裁剪与**重排序**」，但代码只做了**裁剪**，**无加权、无重排序**（拼接顺序是「system → tool → history」，而 history 内部是**时间倒序**，即最新的在前，与自然阅读顺序相反）。
- ⚠️ **`timestamp or time.time()`** —— 若显式传 `timestamp=0` 会被替换为当前时间（**假值陷阱**，虽实践中无害）。
- ⚠️ **`-x["timestamp"]` 排序** —— 降序排序的惯用写法（取负），可读性一般（`reverse=True` 更清晰）。
- ⚠️ **无去重** —— 相同内容的多段会重复保留。

**教材问题（文件头注释实录）**：
> 核心痛点：无差别拼接所有上下文，极易导致输入文本冗长超限。此外，历史信息的随意堆砌，还会引发语义冲突，干扰模型对当前意图的准确理解。
> 解决方案：动态上下文合并策略——通过对上下文段进行分类、加权、裁剪与重排序，有选择地组合最有价值的信息，在保持上下文关联的同时，实现输入内容的最优化。
> 常见实施策略：• 基于时间的窗口截断：保留最近对话，移除遥远的历史。• 基于内容的语义抽取：只保留与当前问题语义强相关的片段。• 基于权重与剪裁：区分用户提问与系统回复，优先保留关键信息。
> 最终目标：在严格遵守模型输入Token限制、保留上下文语义完整性的前提下，为每次模型调用生成结构最优、信息密度最高的提示词（Prompt）。
> 【实现落差】教材导语列了「分类、加权、裁剪、重排序」四动作，代码只实现了**分类 + 裁剪**（加权与重排序未实现）；三个「常见实施策略」中只实现了**基于时间的窗口截断**。

---

## 7. 全章验收清单（V-01 ~ V-14）

### 7.1 运行层验收

| 编号 | 验收项 | 期望 |
|---|---|---|
| V-01 | `python 01_...py` | 5 个上下文段（JSON），中文正常显示 |
| V-02 | `python 02_...py` | 4 个段（system/memory/input/tool），回答体现风格 + 引用工具结果 |
| V-03 | `python 03_...py` | 子任务 1/2 → deepseek，子任务 3 → qwen；**tool 分支不触发** |
| V-04 | `python 04_...py` | 三条分别 → qwen / deepseek / **qwen（非 hybrid）** |
| V-05 | `python 05_...py` | 4 段日志落盘 + 展示最后 5 条 + 文件在 `chapter07/` |
| V-06 | `python 06_...py`（首次） | 未命中 + 调 LLM + 缓存条目 = 1 |
| V-06' | `python 06_...py`（二次） | **命中 + 无 LLM 调用** + 加速 ≈17.7x |
| V-07 | `python 07_...py` | 合并后 6 段 + 段 2 被挤出 + 回答引用历史数据 |

### 7.2 契约层验收

| 编号 | 契约 | 对应 | 验证方式 |
|---|---|---|---|
| V-08 | 无可执行 `from qwen_agent`（C-01） | 全章 | grep 只命中注释 |
| V-09 | 工具类均为纯类 + `name/description`（C-02） | 01-07 | grep `class XxxTool` |
| V-10 | LLM 调用均带 `result_format='message'`（C-03） | 01/02/03/04/05/06/07 | grep 命中 8 处 |
| V-11 | 无相对路径写文件（C-07） | 05/06 | grep `os.path.dirname(os.path.abspath(__file__))` 命中 2 处 |
| V-12 | 骨架函数/类均存在且签名完整（C-05） | 全章 | grep `build_context_segment` / `build_segment` / `create_log_segment` / `persist_segment` / `determine_route` / `route_decision` / `hash_prompt` / `dynamic_merge_context` |
| V-13 | 日志 `model` 字段如实为 `qwen-plus`（C-10） | 05 | grep `"qwen-plus"` 命中 `create_log_segment` 调用 |
| V-14 | 每个文件头含「改写前的问题」+「改写策略」（C-08） | 全章 | grep 关键词 |

### 7.3 学习层验收

- [ ] 能默写五字段（01）与七字段（05）结构。
- [ ] 能说出为什么 07 篇删掉 `task_id`/`meta` 并加入 `timestamp`。
- [ ] 能解释 03 篇 `tool` 分支为什么永不触发（**两个原因**）。
- [ ] 能解释 04 篇 `hybrid` 分支为什么永不触发，并说出修复方式。
- [ ] 能说出 `any(k in q for k in [...])` 相比 `or` 链的优势。
- [ ] 能说出 JSONL 追加写与 JSON 覆盖写各自适合什么场景。
- [ ] 能写出 `hash_prompt` + `check_prompt_cache` 的代码骨架。
- [ ] 能说出 MD5 精确匹配缓存的致命局限（同义改写不命中）。
- [ ] 能默写 07 篇三级筛选策略。
- [ ] 能说出「按条数截断」的锯齿效应及修复方式。

---

## 8. 已知缺口与后续改进（Gap Analysis）

| 编号 | 等级 | 缺口 | 影响 | 建议改进 | 对照章节 |
|---|---|---|---|---|---|
| G-01 | 🟠 | 全章 `os.environ.get('DASHSCOPE_API_KEY')` **无空值校验** | key 未设时报错晦涩 | 启动时校验并友好提示 | chapter12 |
| G-02 | 🔴 | 03 篇 `tool` / 04 篇 `hybrid` **分支死代码** | 分支永不触发，路由设计失效 | **组合类分支放最高优先级** + 加路由单测 | — |
| G-03 | 🟠 | 03 篇 `user_input` **定义后未使用**；04 篇 `inputs` 硬编码 | 子任务拆分与真实请求脱节 | 由 LLM 完成「请求 → 原子子任务」拆分 | chapter05（结构化输出） |
| G-04 | 🟠 | 01 篇 `role` 与 `type` **取值空间重叠歧义**（`observation` 段的 role 写 `model`） | 语义不清，下游难以筛选 | 明确 role/type 的取值枚举与语义边界 | — |
| G-05 | 🟠 | 01 篇**假数据（`is_mock: True`）与真实回答并列存入上下文** | 下游若不检查 meta 会误用假数据 | 假数据单独隔离或加显式标记 | chapter08（降级） |
| G-06 | 🟠 | 02 篇 `memory` 段是**硬编码一句话** | 未体现「长期记忆」的真实存取 | 接入 `PersistentJSONMemory` | chapter02-03 |
| G-07 | 🟠 | 05 篇 `model` 字段**语义混装**（既指模型又指来源/用户） | 字段含义不清，审计困难 | 拆为 `model` + `source` 两字段 | — |
| G-08 | 🟠 | 05 篇 JSONL **单文件无限增长**（无轮转/压缩/索引） | 长期运行文件膨胀、读取变慢 | 按日期分文件 + 压缩归档 | — |
| G-09 | 🟠 | 06 篇**无缓存淘汰策略**（无 LRU/LFU/TTL） | 缓存只增不减，命中率下降 | 加 LRU/TTL + 容量上限 | chapter12（cache） |
| G-10 | 🔴 | 06 篇 **MD5 精确匹配**——同义改写永不命中 | 缓存实际命中率极低 | 升级为**语义缓存**（embedding 相似度 > 0.95） | **chapter06**（DashScopeEmbeddings） |
| G-11 | 🟠 | 07 篇 `history[:4]` **按条数截断**（锯齿效应，可能产生孤儿段） | 丢失提问或回答，语境断裂 | 按**对话轮成对**截断 | — |
| G-12 | 🟠 | 07 篇**无 Token 预算控制**（条数 ≠ Token 数） | 长文本仍可能超限 | 用 `tiktoken` 计数动态截断 | — |
| G-13 | 🟠 | 07 篇 `task_type` 参数**完全未使用** | 教材「按任务类型用不同策略」未实现 | 实现按 task_type 分支的策略表 | — |
| G-14 | 🟠 | 07 篇**无加权、无重排序**（教材导语承诺了但未实现） | 与教材描述不符 | 实现权重排序 + 语义重排 | — |
| G-15 | 🟡 | 06 篇 `save_prompt_cache` **非原子写**（写入中崩溃损坏文件） | 缓存文件可能损坏 | 临时文件 + `os.replace` | — |
| G-16 | 🟡 | 05 篇 `datetime.now()` **无时区** | 跨时区时间语义不明 | 用 `datetime.now(timezone.utc)` | — |
| G-17 | 🟡 | 05 篇 `readlines()` **全量加载** | 只取 5 条却读整个文件 | 用 `deque(f, maxlen=5)` | — |
| G-18 | 🟡 | 06 篇 **「空串 = 未命中」约定有隐患** | LLM 返回空串会重复调用 | 用 `None` 或哨兵值表示未命中 | — |
| G-19 | 🟡 | 05/06 篇**无缓存命中率统计** | 缓存 ROI 无法度量 | 记录 hit/miss 计数 | — |
| G-20 | 🟡 | 全章**无日志框架**（全用 `print`） | 无法控制级别/输出到文件 | 引入 `logging` | — |

### 缺口优先级建议

- **P0（正确性）**：G-02（路由死代码）、G-10（精确匹配缓存低效）
- **P1（教学准确性）**：G-13（`task_type` 未用）、G-14（加权/重排序未实现）、G-07（model 语义混装）
- **P2（健壮性）**：G-01、G-03、G-04、G-05、G-06、G-08、G-09、G-11、G-12、G-15
- **P3（整洁）**：G-16、G-17、G-18、G-19、G-20

---

## 附录 A：上下文段的字段演进（三次设计决策）

```python
# ===== 01/02 篇：五字段（通用最小集） =====
{"role": ..., "content": ..., "type": ..., "task_id": ..., "meta": {...}}

# ===== 05 篇：七字段（审计日志需求） =====
# + id（唯一记录号）  + timestamp（按时间检索）  + model（谁产生的）
{"id": ..., "timestamp": ..., "task_id": ..., "role": ..., "type": ..., "model": ..., "content": ...}

# ===== 07 篇：四字段（合并策略需求） =====
# - task_id / meta（用不上）  + timestamp（按时间倒序取最新）
{"role": ..., "content": ..., "type": ..., "timestamp": ...}
```

**结论**：**字段是「用途需求」的直接投影**——加字段要有明确理由，删字段也要有。

## 附录 B：两种持久化格式对照（05 vs 06）

| 维度 | 05 审计日志 | 06 提示词缓存 |
|---|---|---|
| 文件 | `agent_context_log.jsonl` | `prompt_cache.json` |
| 格式 | JSONL（行式 JSON） | JSON（单个大对象） |
| 写入模式 | `open(..., "a")` **追加** | `open(..., "w")` **覆盖** |
| 数据结构 | 流水（无序 → 按时间排序） | 字典（按 hash 查找） |
| 更新粒度 | 每段即时落盘 | 一次写完整个字典 |
| 读取 | `readlines()[-5:]` 取最后 N 条 | `json.load()` 全量 + `dict.get()` |
| 数据生命周期 | 永久保留 | 可淘汰（当前未实现） |
| 适用场景 | **审计、流水、事件** | **状态、索引、缓存** |
| 关键教训 | 只增不减，不可篡改 | 整体替换，快速查找 |

## 附录 C：路由函数两代写法对照（03 vs 04）

```python
# ===== 03 篇（第一代：or 链） =====
def determine_route(user_input: str) -> str:
    if "政策" in user_input or "法律" in user_input:
        return "qwen"
    elif "数据" in user_input or "预测" in user_input:
        return "deepseek"
    elif "调用" in user_input and "工具" in user_input:   # ← 永远到不了
        return "tool"
    else:
        return "default"

# ===== 04 篇（第二代：any() 生成器，可扩展性更好） =====
def route_decision(query: str) -> str:
    if any(k in query for k in ["政策", "法规", "概述", "总结"]):
        return "qwen"
    elif any(k in query for k in ["预测", "趋势", "估计", "数据"]):
        return "deepseek"
    elif any(k in query for k in ["综合分析", "多维度", "对比"]):   # ← 仍被第1分支截胡
        return "hybrid"
    else:
        return "default"
```

**共同教训**：**组合类分支（`tool` / `hybrid`）必须放在最高优先级**——因为其关键词组常常**同时包含**其他分支的关键词。

## 附录 D：动态合并的三级策略（07）

```python
# 第一级：system 全保留（身份不可丢）
selected = [s for s in segments if s["type"] == "system"]

# 第二级：tool 只留最新 1 条（事实快照取最新）
tool_segments = sorted([s for s in segments if s["type"] == "tool"], key=lambda x: -x["timestamp"])
if tool_segments:
    selected.append(tool_segments[0])

# 第三级：input/response 留最近 4 条（时间窗口）
history = sorted([s for s in segments if s["type"] in ["input", "response"]], key=lambda x: -x["timestamp"])
selected.extend(history[:4])

# 拼接：加 [ROLE-TYPE] 前缀
for seg in selected:
    merged += f"[{seg['role'].upper()}-{seg['type']}] {seg['content']}\n"
```

**对照教材承诺**：教材说「分类、**加权**、裁剪与**重排序**」——**代码只实现了分类 + 裁剪**（加权与重排序未实现，见缺口 G-14）。

## 附录 E：五条跨章关联

| 本篇 | 关联章节 | 关联点 |
|---|---|---|
| 05 `persist_segment`（JSONL 追加写） | char02-03 `PersistentJSONMemory` | JSON 持久化思想同族（追加 vs 全量重写） |
| 03/04 路由函数 | char05-02 LangGraph 条件边 | **路由函数同一家族** |
| 04 `HybridAnalysisTool` fan-out | char05-10 多 Agent 广播图 | **fan-out 同一家族** |
| 06 缓存（精确匹配） | char06 `DashScopeEmbeddings` | **语义缓存升级的直接依赖** |
| 07 合并策略 | char04 `BufferMemory` | 对话管理思想同族（裁剪 vs 全量） |

**核心认识**：char07 的数据结构（段/标注/日志/缓存/合并）都是**框架无关**的——它们是上下文工程的「**元语言**」。char08 的 MCP 真实协议，本质就是 01/02 篇数据结构的**标准化版本**。

| 生产框架/技术 | 对应本篇概念 | 升级点 |
|---|---|---|
| MCP Protocol | 01/02 上下文段结构化 | 标准化协议、双向通信、能力协商 |
| Redis / TTL 缓存 | 06 提示词缓存 | 分布式、TTL 过期、LRU 淘汰 |
| 向量语义缓存（GPTCache） | 06 缓存 + char06 embedding | 相似度匹配，同义改写可命中 |
| tiktoken / Token 预算管理 | 07 动态合并 | 按 Token 精确截断，非条数 |
| LLMLingua / 上下文压缩 | 07 合并策略 | 用 LLM 做摘要压缩，而非规则裁剪 |
