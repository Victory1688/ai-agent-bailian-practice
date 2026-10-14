# 第 3 章 规范说明书（spec.md）——大模型开发基础

> **SDD 定位**：本文回答 *「把大模型用起来，需要掌握哪些基础能力」*。
> **上篇（意图与学习路径）**回答 *为什么学、学什么、怎么学*；
> **下篇（契约与验收）**回答 *每个文件到底承诺了什么、怎么验证、还缺什么*。
> **主线**：本章是**「从模型到服务」的基础设施篇**——9 个例子依次演示
> **远程调用 → 本/云部署取舍 → 微调 → 并发调度 → OpenAI 协议 → Function Calling → 批处理/流式 → 内容审查 → 可信度评估**。
> 如果说 chapter02 讲「Agent 怎么组装」，本章讲「模型这一块怎么用、怎么接、怎么控」。
>
> 适用范围：`D:/AiWorkOut/aiAgentCode/chapter03/`（9 个 .py / 1453 行）。
> 契约字段一律**从代码事实反推**，不臆造；教材简化点与改写依据一并留痕。

---

# 上篇：意图与学习路径

## 1. 章意图（Why）

### 1.1 教材原版想解决什么

教材用一章讲「大模型开发基础」，实际是**9 个并列的能力点**，每个用一个完整例子演示：

| 教材概念 | 想说明什么 |
|---|---|
| 远程调用大模型 | 用 API 方式调 SaaS 模型（含消息构造 + temperature） |
| 本地部署 | 把模型权重下载到本地显卡跑推理 |
| LoRA 微调 | 冻结主模型、只训低秩矩阵，轻量定制 |
| GPU 资源调度 | 模型并行 + 多实例部署 + 多线程异步 |
| ChatCompletion 接口 | 用 FastAPI 实现 OpenAI 兼容服务 |
| 函数调用标准结构 | tools 说明书 → 模型决策 → 本地执行 → 回传 |
| 并行处理与流式接口 | 批处理提吞吐 + 流式降感知延迟 |
| 敏感词过滤 | 生成前 + 生成后两层内容审查 |
| 可信度评估 | 用逐 token 概率判断幻觉风险 |

### 1.2 教材原版的三大硬门槛

**这 9 个例子中的 7 个（03~09）在普通电脑上根本跑不起来**，卡在三个门槛：

| 门槛 | 涉及例子 | 具体障碍 |
|---|---|---|
| 🔴 **必须有 CUDA 显卡** | 03/04/05/06/07/08/09 | `assert torch.cuda.device_count() >= 1`、`.cuda()` 在 CPU 机器上直接报错 |
| 🔴 **必须下载数 GB 权重** | 03/04/05/06/07/08/09 | `Qwen/Qwen-235B`（数百 GB）、`Qwen/Qwen-1.8B`（约 3.6GB） |
| 🟠 **必须装重依赖** | 03~09 | `torch` + `transformers` + `peft` + `datasets` + `accelerate`（合计数 GB） |

此外 01 篇还有**地域门槛**：`openai` 老版 SDK 直连 OpenAI，国内无法访问且未配 `OPENAI_API_KEY`。

### 1.3 本章改写要解决什么

**核心改写策略**：把「本地权重 + GPU 前向」整体替换为「云端 API 调用」，但**逐 Step 保留教材的教学结构**，让读者仍能看懂「原本在做什么」。

| 教材原实现 | 改写后 | 教学点是否保留 |
|---|---|---|
| `openai.ChatCompletion.create` | `dashscope.Generation.call` | ✅ 远程调用范式 |
| `AutoTokenizer` + `AutoModelForCausalLM.from_pretrained(...).cuda()` | 删除加载步骤，直接 `Generation.call` | ✅ 用注释保留原代码 + 说明差异 |
| `model.generate(...)` | `dashscope.Generation.call(model, messages, ...)` | ✅ 参数语义一一映射 |
| `peft.LoraConfig` + `Trainer.train()` | `FineTunes.call(mode="lora", hyper_parameters={...})` | ✅ 超参映射表 |
| GPU 副本 + `threading.Thread` | 云端槽位 + `threading.Thread`（**架构原样**） | ✅ 并发调度架构 |
| 假流式（整段生成后切片 `sleep`） | 真流式（`stream=True` + `incremental_output=True`） | ✅ **升级**（不是降级） |
| 假 Function Calling（关键词硬编码） | 真 Function Calling（`tools=tools` + 循环） | ✅ **补齐**（原代码缺失） |
| `output_scores=True` + `torch.topk` 取概率 | OpenAI 兼容模式 `logprobs` + `top_logprobs` | ✅ 同等能力，不同载体 |

### 1.4 本章最该带走的三句话

1. **「本地部署」与「云端调用」是可替换的部署形态**——前者要显卡、要权重、要显存管理；后者只要网络和一个 key。教学代码应该教**架构思想**（并发、批处理、流式），而不是绑定硬件。
2. **OpenAI 协议是行业通用方言**——`/v1/chat/completions` 的请求体（`model/messages/temperature/max_tokens/stream`）与响应体（`choices[].message.content`）是事实标准。实现它，任何「会说 OpenAI 方言」的客户端都能无缝接入你的服务。
3. **高级能力（Function Calling / 流式 / logprobs）都定义在协议里**——不是某个 SDK 的私有魔法。掌握协议 = 掌握可迁移能力。

---

## 2. 学习路径（9 文件 / 1453 行）

按「调用 → 部署 → 训练 → 调度 → 协议 → 工具 → 并行 → 安全 → 评估」的顺序阅读：

| # | 文件 | 行数 | 核心机制 | 读完后你应能说出 |
|---|---|---|---|---|
| 01 | `01_远程调用大模型语义助手.py` | 95 | `build_message` + `dashscope.Generation.call` + 批量循环 | 远程调用的最小闭环（消息构造 → 请求 → 取 content） |
| 02 | `02_模拟Qwen本地调用.py` | 86 | 本地部署 vs 云端调用的逐 Step 对照 | 两种部署形态的差异与取舍 |
| 03 | `03_模型的LoRA微调控制.py` | 223 | 数据构造 → `Files.upload` → `FineTunes.call`（含超参映射） | LoRA 四要素（r/alpha/dropout/target）及云端映射 |
| 04 | `04_模拟支持多线程并发的GPU推理系统.py` | 176 | `threading.Thread` + 轮询分发 + **串行/并发对照实验** | 并发为什么提吞吐（用真实耗时证明） |
| 05 | `05_模拟ChatCompletion接口.py` | 151 | FastAPI `/v1/chat/completions` + 真流式 SSE | OpenAI 协议长什么样、真流式与假流式的区别 |
| 06 | `06_支持Qwen模型函数调用标准结构.py` | 205 | `tools` 说明书 + 两轮 Function Calling 循环 | 真 Function Calling 与「假关键词匹配」的区别 |
| 07 | `07_并行处理与实时流式接口.py` | 202 | `ThreadPoolExecutor` 批处理 + 真流式 | 批处理与流式各自解决什么问题 |
| 08 | `08_审查敏感词过滤系统.py` | 147 | **Trie 前缀树** + 生成前/后双层过滤 | 为什么用 Trie、两层防线各拦什么 |
| 09 | `09_大模型的可信度评估.py` | 168 | OpenAI 兼容模式 `logprobs` + `top_logprobs` + 置信度汇总 | 如何用逐 token 概率量化幻觉风险 |

### 阅读路线建议

- **第一遍（基础 2 篇）**：01 → 02。把「调用」和「部署形态」这两个前置概念建立起来。
- **第二遍（协议 2 篇）**：05 → 06。抓住「OpenAI 协议」这条主线（服务化 + Function Calling）。
- **第三遍（并发与流式 2 篇）**：04 → 07。04 是裸线程，07 是线程池 + 流式，成对看。
- **第四遍（能力 3 篇）**：03（训练）→ 08（安全）→ 09（评估）。三块相对独立的高级能力。
- **对照读法**：04（线程并发）↔ 07（线程池批处理）；05（假流式→真流式）与 07（同款升级）互为印证。

---

## 3. 五条工程主线（本章反复出现的设计决策）

### 主线一：改动「模型加载」，保留「教学结构」

改写全章反复遵守一个纪律：**逐 Step 对应**。

```
教材 Step 1: 检测 GPU / 加载模型      → 改写：删掉（云端托管，无本地加载）
教材 Step 2: 构造 prompt / messages   → 改写：原样保留（build_message / build_prompt）
教材 Step 3: model.generate 推理      → 改写：dashscope.Generation.call
教材 Step 4: 解码 / 取 content        → 改写：response.output.choices[0].message.content
教材 Step 5: 并发 / 流式 / 后处理     → 改写：原样保留
```

**为什么**：这是**学习型改写**——读者的认知负担在于「云端调用替代了哪一步」，逐 Step 对照才能让差异一目了然。

### 主线二：`messages` 数组是新的「prompt」

教材里大量出现 `build_prompt()`——因为**裸基座模型不认识 `messages` 数组**，必须手工拼成带角色标记的大字符串：

```
[系统提示]：xxx
[用户]：yyy
[助手]：        ← 让模型续写
```

改写后**这些 `build_prompt` 全部消失**（或被 `build_messages` 替代），因为 Chat 模型**原生理解 role/content 结构**。

| 概念 | 裸基座模型 | Chat 模型（本章改写后） |
|---|---|---|
| 输入 | 拼成一个大字符串 | `messages=[{role,content},...]` |
| 角色标记 | 手工 `[用户]：` / `[助手]：` | `role` 字段 |
| 截取回复 | `split("[助手]：")[-1]` | `response...message.content` |
| 是否能 Function Calling | ❌ 完全不支持 | ✅ `tools=` 参数 |

**这是全章最重要的认知跃迁**：从「拼字符串」到「发结构」。

### 主线三：真流式 vs 假流式

| | 假流式（教材原版） | 真流式（改写后） |
|---|---|---|
| 生成方式 | 整段生成完毕 | `stream=True` 边生成边返回 |
| 切片 | 生成后切成 N 字符片 | 模型原生分块 |
| 首字延迟 | = **整段生成时间** | = **生成第一个 token 的时间** |
| 节奏 | `time.sleep(0.05)` 模拟 | 真实生成节奏 |
| 协议 | 无 `data:` 前缀、无 `[DONE]` | `data: {...}\n\n` + `data: [DONE]\n\n` |

**关键参数**：`incremental_output=True` —— 每次只返回**新增**内容，而非全量重复。

### 主线四：OpenAI 协议的两个「门」

百炼平台同时提供两扇门，本章都用到：

| 门 | 端点 | 用法 | 出现在 |
|---|---|---|---|
| **原生 SDK** | `dashscope.Generation.call(...)` | Python 函数调用 | 01/02/04/05/06/07/08 |
| **OpenAI 兼容模式** | `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions` | HTTP POST + Bearer | **09（唯一）** |

**为什么 09 必须走兼容模式**：`logprobs` / `top_logprobs` 这两个参数**只有 OpenAI 协议层暴露**，dashscope 原生 `Generation.call` 不返回逐 token 概率。**这是「协议选择决定能力边界」的活教材**。

### 主线五：内容审查的两层防线

08 篇的核心架构（可复用到任何 Agent 系统）：

```
用户输入 ──→ [第一层：生成前过滤] ──命中──→ 直接拒绝（不调模型，省时省钱）
                    │ 通过
                    ↓
                模型生成
                    │
                    ↓
模型输出 ──→ [第二层：生成后过滤] ──命中──→ 拦截（不返回给用户）
                    │ 通过
                    ↓
                 返回用户
```

**两层缺一不可**：
- 只有第一层 → 模型可能在输出里「说出」敏感词（如被诱导补全）；
- 只有第二层 → 已经浪费了一次推理成本。

---

## 4. 学习检查清单（读完自测）

- [ ] 能写出远程调用的最小四步（建 key → 构消息 → 调用 → 取 content）。
- [ ] 能说出本地部署 vs 云端调用的三个取舍维度（硬件/成本/数据）。
- [ ] 能说出 LoRA 的 `r` / `lora_alpha` / `lora_dropout` 各控制什么。
- [ ] 能解释 04 篇为什么要做「串行 vs 并发」对照实验。
- [ ] 能说出真流式与假流式的首字延迟差异。
- [ ] 能说出 `data: [DONE]` 的作用。
- [ ] 能指出教材 06 篇的「假 Function Calling」具体假在哪里。
- [ ] 能解释为什么用 Trie 而不是「逐个 `text.count(word)`」。
- [ ] 能说出 08 篇两层过滤各自拦什么、为什么不能只留一层。
- [ ] 能解释 09 篇为什么必须走 OpenAI 兼容模式。

---

# 下篇：契约与验收

## 5. 全局技术约束（C-xx）

### C-01 模型统一 `qwen-plus`，不再加载本地权重

**约束**：任何文件**不得** `from transformers import ...`（08 篇的遗留 import 除外，见其契约），不得 `from_pretrained`、不得 `.cuda()`。
**实现**：所有推理走 `dashscope.Generation.call(model='qwen-plus', ...)`。
**验收**：9 个文件 grep `from_pretrained` 应**零命中**（只允许在注释块）。

### C-02 API Key 来自环境变量

```python
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key      # 原生 SDK 用法
# 或（兼容模式）
headers={"Authorization": f"Bearer {api_key}"}
```
**约束**：不得硬编码 key。
**已知风险**：`os.environ.get()` 无空值校验（见缺口 G-02）。

### C-03 调用统一携带 `result_format='message'`

```python
response = dashscope.Generation.call(model='qwen-plus', messages=..., result_format='message')
text = response.output.choices[0].message.content
```
**约束**：除 09 篇（走 HTTP 兼容模式）外，所有 `Generation.call` 必须带 `result_format='message'`。
**理由**：否则 `response.output` 是字符串，`.choices[0]` 报错。

### C-04 推理函数永不抛异常（CLI 类）

**约束**：01/02/04/07/09 的推理函数内部 `try/except`，失败返回错误说明字符串。
**例外**：05/06/08 是 FastAPI 端点，允许把错误转成 HTTP 错误结构（08 显式返回 `{"flag":"model_error"}`）。
**验收**：断网时 CLI 例子不崩溃而是打印错误。

### C-05 参数语义与教材本地版一致

| 本地版参数 | 云端参数 | 语义 |
|---|---|---|
| `max_new_tokens` | `max_tokens` | 回复长度上限 |
| `temperature`（+ `do_sample=True`） | `temperature` | 采样随机性 |
| `output_scores=True` + `topk(k)` | `logprobs=True` + `top_logprobs=k` | 逐 token 概率 + 前 k 候选 |
| `output_dir`（训练） | `FineTunes.call` + 控制台 | 训练产物位置 |

**约束**：改写时在代码注释中标注「与原版 XXX 语义一致」。
**验收**：每个 `Generation.call` 附近的注释能对应到教材原参数。

### C-06 OpenAI 协议响应结构固定（05/06/07/09）

```jsonc
// 非流式
{"id": "...", "object": "chat.completion",
 "choices": [{"message": {"role": "assistant", "content": "..."}}]}
// 流式（SSE）
"data: {\"choices\": [{\"delta\": {\"content\": \"...\"}}]}\n\n"
"data: [DONE]\n\n"
```
**约束**：流式响应必须带 `data: ` 前缀、JSON 体、双换行分隔、`[DONE]` 结束标记。
**验收**：curl 流式请求能看到逐块到达的 `data:` 行 + 末尾 `[DONE]`。

### C-07 FastAPI 服务直接传 app 对象启动

**约束**：
```python
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000|8080)
```
**禁止** `uvicorn.run("filename:app")`——中文文件名无法作为模块导入，占位符 `filename` 直接 `ImportError`。
**理由**：这是教材原版的一个真实 bug，改写已修复。

### C-08 服务端口约定

| 文件 | 端口 | 端点 |
|---|---|---|
| 05 | 8080 | `/v1/chat/completions` |
| 06 | 8080 | `/v1/chat/function_call` |
| 07 | 8000 | `/v1/chat/batch`、`/v1/chat/stream` |
| 08 | 8000 | `/v1/chat/audit` |
| 09 | 8000 | `/v1/chat/with_confidence` |

**约束**：同一端口内多个服务不可同时启动；05/06 与 07/08/09 分属 8080 / 8000 两组，可各组选一个并行验证。

### C-09 流式必须 `stream=True` + `incremental_output=True`

**约束**：真流式生成器两个参数缺一不可。
**理由**：只开 `stream=True` 会返回**全量累积**内容（每次重复前面所有字），必须叠加 `incremental_output=True` 才是增量。

### C-10 教材原代码以注释保留

**约束**：每个文件头部以注释块保留教材原版实现（`# from transformers import ...` / `# model.generate(...)`），并注明为何不可运行。
**验收**：9 篇均有「原写法」注释块 + 改写说明。

### C-11 关键差异必须显式对照

**约束**：改写点需以「原写法：X ← 问题；改写：Y ← 原因」的形式在注释中成对出现。
**实例**：05「假流式 → 真流式」、06「假 Function Calling → 真 Function Calling」、09「output_scores → logprobs」。

### C-12 不引入未声明的依赖

**约束**：改写后代码的顶层依赖限定为：`dashscope`、`fastapi`、`pydantic`、`uvicorn`、`requests`、`concurrent.futures`（标准库）。
**例外**：08 篇保留了 `from transformers import AutoTokenizer, AutoModelForCausalLM`（见其契约的缺口说明）。

---

## 6. 逐文件契约（F-01 ~ F-09）

---

### F-01 `01_远程调用大模型语义助手.py`（95 行）——远程调用篇

**意图**：用百炼替代 OpenAI，演示「远程调用」最小闭环 + 批量推理。

**消息构造契约（`build_message`，教材原逻辑保留）**：
```python
def build_message(user_prompt: str) -> List[Dict[str, str]]:
    return [
        {"role": "system", "content": "你是一位语言学家，擅长解释中文成语的典故、来历与含义"},
        {"role": "user",   "content": user_prompt},
    ]
```
**教学点**：`system` 锚定身份，`user` 放具体请求——这是**角色分离**的最小体现。

**推理契约（`chat_with_llm`）**：
```python
def chat_with_llm(prompt, temperature=0.5, max_tokens=300) -> str
```
- `messages = build_message(prompt)`；
- `dashscope.Generation.call(model='qwen-plus', messages, temperature, max_tokens, result_format='message')`；
- `return reply.strip()`；
- `except Exception` → `f"调用失败: {str(e)}"`。

**批量契约（`batch_inference`）**：遍历 5 个成语（破釜沉舟/卧薪尝胆/指鹿为马/望梅止渴/画龙点睛），返回 `{成语: 解释}` 字典。

**输出**：`>>> 开始批量调用阿里百炼大模型` + 5 段 `【成语】\n解释`。

**验收标准**：
- V-01-A：5 个成语均有非空解释，含典故/含义内容。
- V-01-B：`temperature=0.5` 传参生效（可改参数观察风格变化）。
- V-01-C：断网/无 key 时不崩，返回「调用失败: ...」。

**已知风险**：**串行单条循环**——5 个成语依次调用，总耗时 = 5 × 单次（对比 04/07 的并发）。

**教材问题（文件头注释实录）**：
> 原写法：OpenAI 老版本 SDK 调用方式，且未配置 `OPENAI_API_KEY`（国内无法直连 OpenAI 服务）。
> `openai.ChatCompletion.create(...)` → `dashscope.Generation.call(...)` 百炼平台调用；但参数 `temperature` / `max_tokens` / 异常兜底逻辑原样保留。

---

### F-02 `02_模拟Qwen本地调用.py`（86 行）——部署形态篇

**意图**：用**逐 Step 对照**的方式，讲清「本地部署」与「云端调用」的差异。

**Step 对照契约**（教材 4 步 → 改写后）：

| 教材原 Step | 内容 | 改写后 |
|---|---|---|
| Step 1 | 安装依赖（`torch`/`transformers`/`qwen`） | 注释保留，说明为何不需要 |
| Step 2 | 加载 Qwen-235B 模型（`from_pretrained(..., device_map="auto", torch_dtype=float16)`） | **删除加载**——云端托管 |
| Step 3 | `build_prompt(user_input)` | **原样保留** |
| Step 4 | `model.generate(**inputs, max_new_tokens, do_sample, temperature)` | `dashscope.Generation.call(...)` |
| Step 5 | 批量测试循环 | **原样保留** |

**推理契约（`run_inference`）**：
```python
def run_inference(prompt: str, max_tokens: int = 128, temperature: float = 0.7)
```
- `messages=[{"role":"user","content":prompt}]`（原版是纯字符串 prompt → 保持 prompt 内容不变）；
- `max_tokens=128`（对应 `max_new_tokens=128`）；
- `temperature=0.7`（对应原 `do_sample=True` + `temperature`）；
- `except` → `f"调用失败: {str(e)}"`。

**主流程契约**：**模块级直接执行**（无 `if __name__`），`idioms = ["画蛇添足","纸上谈兵","掩耳盗铃","望梅止渴","指鹿为马"]` 逐个推理打印。

**验收标准**：
- V-02-A：5 个成语各打印一段解释，无异常。
- V-02-B：文件头注释块完整保留原 `transformers` 代码（供对照）。

**已知风险 / 设计点**：
- ⚠️ **无 `if __name__ == "__main__"`**——`import` 该模块会**立即执行** 5 次 API 调用（见缺口 G-10）。
- ⚠️ 模型名写的是 `Qwen-235B`（教材原文）——实际百炼并无该名，改写已换 `qwen-plus`；**注释中的 `Qwen-235B` 保留是刻意的**（用于说明「本地要装什么」）。

**教材问题（文件头注释实录）**：
> 本地部署 = 把模型权重下载到本地显卡上跑推理。Qwen-235B 这种规模的模型需要专业级多卡环境（数百 GB 显存），普通电脑装不下也跑不动——所以改用百炼云端调用。
> 改写思想：把"加载模型 + 本地推理"整体替换为"远程调用云端模型"，但 `build_prompt` 的提示词构造、`max_tokens`/`temperature` 的参数语义、批量测试循环全部保留。

---

### F-03 `03_模型的LoRA微调控制.py`（223 行）——微调篇

**意图**：把教材的本地 LoRA 微调「9 步流程」，映射到百炼云端的「构造数据 → 上传 → 提交 → 等待 → 下载」。

**Step 对照契约**：

| 教材本地 Step | 改写后云端 Step |
|---|---|
| Step 1 加载 Qwen-1.8B + Tokenizer | —（云端托管） |
| Step 2 `LoraConfig(...)` | Step 3 的 `hyper_parameters` 字典 |
| Step 3 `get_peft_model` | —（云端执行） |
| Step 4 `Dataset.from_dict(data_dict)` | **Step 1 `build_training_data()` 返回 JSONL** |
| Step 5 `tokenizer(prompt, ...)` 预处理 | —（云端处理） |
| Step 6 `TrainingArguments(...)` | Step 3 的 `hyper_parameters` 字典 |
| Step 7~9 `Trainer.train()` + `save_pretrained` | **Step 3 `FineTunes.call`** |

**超参映射契约（教材注释明确列出）**：

| 本地参数 | 云端 `hyper_parameters` 键 | 值 |
|---|---|---|
| `lora_config.r` | `lora_r` | 8 |
| `lora_config.lora_alpha` | `lora_alpha` | 16 |
| `lora_config.lora_dropout` | `lora_dropout` | 0.1 |
| `train_args.learning_rate` | `learning_rate` | 3e-4 |
| `train_args.num_train_epochs` | `epoch_count` | 3 |
| `train_args.per_device_train_batch_size` | `batch_size` | 2 |

**函数契约**：

| 函数 | 签名 | 返回 |
|---|---|---|
| `build_training_data()` | `() -> str` | 6 条情感分类样本的 JSONL 字符串（`{"messages":[{user},{assistant}]}`） |
| `upload_dataset(jsonl_content, file_name="lora_sentiment_train.jsonl")` | → `str \| None` | `Files.upload(purpose='fine_tune')` 成功 → `file_id`；否则 `None` |
| `submit_lora_finetune(file_id, model="qwen-plus")` | → resp | `FineTunes.call(model, training_file_ids=[file_id], mode="lora", hyper_parameters)` |
| `check_finetune_status(fine_tune_id)` | → `str \| None` | `FineTunes.get(id).output["status"]` |

**数据格式契约**（百炼要求）：
```jsonl
{"messages": [{"role":"user","content":"请判断以下句子的情感倾向：客服态度很好，处理问题及时"}, {"role":"assistant","content":"正面"}]}
```
**6 条样本**：3 正面 + 3 负面（客服态度/物流速度/价格优惠 vs 屏幕亮度/死机/音质续航）。

**上传后清理契约**：`upload_dataset` 在 `Files.upload` 后 `try: os.remove(temp_path)`（避免留下临时文件）。

**错误处理契约**：`submit_lora_finetune` 非 200 时打印 `status/code/message` + **可能原因**（`403 Model.AccessDenied`：账号未开通微调权限）+ 解决方案。

**验收标准**：
- V-03-A：`build_training_data()` 返回 6 行 JSONL，每行 `json.loads` 成功且含 `messages`。
- V-03-B：`upload_dataset` 返回非空 `file_id`（需账号有上传权限）。
- V-03-C：`submit_lora_finetune` 若被拒（403），打印的提示信息完整（含「申请微调权限」指引）。
- V-03-D：临时 JSONL 文件在上传后被删除。

**已知风险**：
- 🔴 **个人账号默认无微调权限**——`403 Model.AccessDenied` 是**当前最常见的失败**（代码注释明确承认此点）。**因此本文件的实际「成功路径」难以验证**，本质上是一个**「提交演示」**（见缺口 G-01）。
- ⚠️ 用 `qwen-plus` 作微调基座——注释提醒「需是百炼支持微调的模型」，实际可用性取决于平台策略。
- ⚠️ 长任务（几十分钟~几小时）——`check_finetune_status` 只在 `run_lora_finetune_demo` 的**打印文本**里提及，**未被实际调用**（缺口 G-11）。
- 无 `FineTunes.wait()` 阻塞等待（仅在打印中提及）。

**教材问题（文件头注释实录）**：
> 这段代码展示 LoRA 微调的完整原理流程（9 步），对理解微调机制非常有价值。但它需要：下载 Qwen-1.8B 权重（约 3.6GB）+ CUDA 显卡 + PEFT/datasets 依赖数 GB + 训练耗时数十分钟。普通电脑没有独立显卡或显存不够时必然跑不动——所以改写为百炼云端微调。
> 改写思想：① 本地「配置→数据→训练→保存」四步映射到云端「上传数据→提交任务→等待训练→下载权重」；② 本地 `LoraConfig` 的每个参数映射到 `FineTunes.call` 的 `hyper_parameters` 字典。

---

### F-04 `04_模拟支持多线程并发的GPU推理系统.py`（176 行）——并发调度篇

**意图**：演示「多实例部署 + 多线程调度」，并**用真实耗时证明并发提吞吐**。

**Step 对照契约**：

| 教材 Step | 改写后 |
|---|---|
| Step 1 检测 GPU 数量（`assert torch.cuda.device_count() >= 1`） | `INSTANCE_IDS = [0, 1]`（云端槽位，无 GPU 限制） |
| Step 2 每卡加载模型副本 | 删除 + `print("云端实例由百炼平台托管，本地无需加载模型副本。")` |
| Step 3 `run_inference(device_index, input_text)` | **签名不变**，内部换 `Generation.call` |
| Step 4 `prompts` 列表 | **原样保留**（4 条：Transformer/多模态/LoRA/AI Agent） |
| Step 5 `threading.Thread` + `idx % len(device_ids)` + `join` | **原样保留**（轮询分发） |

**推理契约（`run_inference(instance_index, input_text)`）**：
- `start = time.time()` → 调用 → `end = time.time()`；
- 打印 `[实例-{i}] 推理耗时：{round(end-start,2)}秒` 与 `输出结果：{decoded[:60]}...`；
- `except` → `[实例-{i}] 调用失败：{str(e)}`；
- **显存清理动作（`del` + `torch.cuda.empty_cache()`）删除**，注释说明「云端无本地显存占用」。

**对照实验契约（本文件教学精华）**：

| 实验 | 函数 | 行为 | 产出 |
|---|---|---|---|
| A 串行 | `run_serial()` | 4 个 prompt 全部路由到实例 0，逐个执行 | `串行总耗时` |
| B 并发 | `run_concurrent()` | 4 个线程，`idx % 2` 分发到 0/1 实例，`join` 等待 | `并发总耗时` |

**主流程契约**：先 A 后 B，最后打印 `吞吐对比：串行 X秒 vs 并发 Y秒` + `并发加速比：约 Z 倍`。

**验收标准**：
- V-04-A：实验 A 总耗时 ≈ 4 × 单次耗时（如单次 3s → 约 12s）。
- V-04-B：实验 B 总耗时 < A，加速比 > 1。
- V-04-C：`[实例-0]` 与 `[实例-1]` 都有输出（证明轮询分发生效）。
- V-04-D：`INSTANCE_IDS` 改为 `[0]` 后，实验 B 不再并发（退化），对照明显。

**已知风险**：
- ⚠️ **云端并发受平台 QPS/并发限制**——加速比可能被限流压低（见缺口 G-03）。
- ⚠️ `threading.Thread` 无异常捕获（`run_inference` 内部有，但线程对象的异常不外传）。
- ⚠️ 无 `daemon=True`——异常时可能阻碍退出。
- 并发实验的 4 个线程**同时**发起，可能触发百炼的瞬时并发上限。

**教材问题（文件头注释实录）**：
> 这段代码展示"多实例部署 + 多线程调度"的完整架构，是理解推理服务并发的经典教材。但它需要：本机有 CUDA 显卡 + 下载 Qwen-1.8B 权重 + GPU 显存。没有独立显卡的电脑在 Step 1 的 `assert` 就会中断——所以改写为云端并发调用。
> 额外增加：串行版对照实验——用真实耗时证明"并发提升吞吐"，没有 GPU 也能看到效果。

---

### F-05 `05_模拟ChatCompletion接口.py`（151 行）——OpenAI 协议篇

**意图**：用 FastAPI 实现 **OpenAI 兼容**的 `POST /v1/chat/completions`（含真流式）。

**请求/响应契约**：
```python
class Message(BaseModel):    role: str;  content: str
class ChatRequest(BaseModel):
    model: str
    messages: list[Message]
    temperature: float = 0.7
    max_tokens: int = 256
    stream: bool = False
```
```jsonc
// 非流式响应
{"id": "cmpl-local-001", "object": "chat.completion",
 "choices": [{"message": {"role": "assistant", "content": result}}]}
```

**`build_messages` 契约**：把 Pydantic `Message` 列表转成 dict 列表 —— **替代了教材的 `build_prompt`**（教材注释保留：原版需手工拼 `[系统提示]：`/`[用户]：`/`[助手]：`）。

**流式契约（`stream_response`）**：
```python
responses = dashscope.Generation.call(
    model='qwen-plus', messages=messages, max_tokens=max_tokens, temperature=temperature,
    result_format='message',
    stream=True,                 # 流式
    incremental_output=True      # 增量（只返新增）
)
for response in responses:
    chunk = response.output.choices[0].message.content or ""
    if chunk:
        yield f"data: {json.dumps({'choices': [{'delta': {'content': chunk}}]}, ensure_ascii=False)}\n\n"
yield "data: [DONE]\n\n"
```

**端点契约**：
| 方法 | 路径 | 分支 |
|---|---|---|
| POST | `/v1/chat/completions` | `req.stream` → `StreamingResponse(..., media_type="text/event-stream")`；否则 → 普通 JSON |

**验收标准**：
- V-05-A：非流式请求返回含 `choices[0].message.content` 的 JSON，`object == "chat.completion"`。
- V-05-B：`stream=true` 时响应为逐块 `data: {...}` 行，以 `data: [DONE]` 结束。
- V-05-C：`curl` 单行命令（文件末尾注释提供）可复现。
- V-05-D：`uvicorn.run(app, ...)` 传 app 对象，能正常启动（不是 `"filename:app"`）。

**已知风险**：
- ⚠️ 流式 `json.dumps(..., ensure_ascii=False)` 会产生**含中文的 SSE 行**——符合规范，但某些前端需注意编码。
- ⚠️ **非流式响应缺 `usage` / `id` 固定为 `cmpl-local-001`**——不完全符合 OpenAI 规范（见缺口 G-04）。
- ⚠️ `stream_response` 是**同步生成器**，但被 `async def` 端点直接返回——FastAPI 能处理（会自动跑在 threadpool），但**混用 sync/async 语义**需注意。
- 无鉴权（无 `Authorization` 校验）。

**教材问题（文件头注释实录）**：
> 原写法：本地加载 Qwen-1.8B 做推理（无 GPU 环境跑不动，模型加载部分改用百炼云端调用）。
> `build_prompt`（裸基座模型手动拼角色标记）：改写后 dashscope 原生支持 `messages` 数组，不再需要手动拼接——这正是 Chat 接口协议的价值：角色结构由服务端理解。
> 流式：原写法"假流式"——先整段生成完毕，再切成 10 字符一片用 `time.sleep` 模拟打字机效果。改写："真流式"——`stream=True` + `incremental_output=True`。

---

### F-06 `06_支持Qwen模型函数调用标准结构.py`（205 行）——Function Calling 篇

**意图**：把教材的**假** Function Calling（关键词硬编码）改成**真** Function Calling（模型自主决策）。

**「假」与「真」对照契约**：

| 教材原版（假） | 改写后（真） |
|---|---|
| 模型没看到 `tools` 说明书 | `tools=tools` 传给模型 |
| `if "调用函数" in output_text:` 硬编码判断 | `tool_calls = getattr(message, 'tool_calls', None)` |
| `if "get_weather" in output_text: return {...固定参数...}` | 模型自主给 `arguments` |
| 换输入就对不上 | 任意输入都可正确决策 |

**工具三件套契约**：

| 工具 | 执行体 | 参数 |
|---|---|---|
| `get_weather(city: str)` | `f"{city}的当前天气是晴，气温25°C"` | `city: string`（required） |
| `calculate_sum(a: float, b: float)` | `f"{a} + {b} = {int(a)+int(b)}"` | `a: number`, `b: number`（required） |

**`run_function_call` 契约（两轮循环）**：

| 轮次 | 行为 |
|---|---|
| 第 1 轮 | `Generation.call(messages, tools=tools, temperature=0.3, max_tokens=512)` |
| 分支 A | 无 `tool_calls` → `{"response": message.content, "tool_calls": []}` |
| 分支 B | 有 → `messages += [message]` → 逐个执行 → 回填 `role=tool` → 第 2 轮 |
| 第 2 轮 | `Generation.call(messages_list)`（**不带 tools**）→ `final_content` |
| 返回 | `{"response": final_content, "tool_calls": executed_calls}` |

**`executed_calls` 契约**：`[{"name", "arguments", "result"}, ...]` —— 供客户端了解本轮发生了什么调用。

**端点契约**：`POST /v1/chat/function_call` → `{messages_list → run_function_call → result}`。

**验收标准**：
- V-06-A：问「请告诉我北京的天气」→ `tool_calls` 含 `get_weather`，`arguments.city` 为「北京」（或含北京）。
- V-06-B：问「帮我算一下 8 + 12」→ `tool_calls` 含 `calculate_sum`，`result` 为 `"8 + 12 = 20"`。
- V-06-C：问「今天心情不错」→ `tool_calls == []`，`response` 为自然语言。
- V-06-D：`response` 是对 `result` 的自然语言复述（证明模型读到工具结果）。

**已知风险**：
- ⚠️ **第 2 轮不带 `tools`** —— 这是刻意的（结束调用），但意味着**不支持「多轮工具调用」**（一次请求最多调一轮工具）。对比 chapter02/13 的 `while True` 循环（见缺口 G-05）。
- ⚠️ 第 2 轮无 `try/except` —— 失败会 500。
- ⚠️ `ChatRequest` 里的 `stream` 字段**声明未使用**（死字段）。
- `tool_registry` 与 `tools` 需手工保持同步（无自动校验）。

**教材问题（文件头注释实录）**：
> 原代码的 FastAPI 骨架、`function_registry`、`dispatch_function` 都是好教材。但"函数调用提取"是假的——它用关键词匹配（"调用函数" / "get_weather"）硬编码返回固定结构，模型根本没看到工具说明书，也没有自主决策调不调函数。
> 问题：模型没看到工具说明 → 不会主动说"调用函数"；返回值硬编码 → 换个输入就对不上。
> 改写核心：① `function_registry` 的 value 里补上完整的 `tools` 说明书；② `dispatch_function` 逻辑原样保留（本地执行体）；③ 端点内部走真正的 Function Calling 循环。

---

### F-07 `07_并行处理与实时流式接口.py`（202 行）——批处理与流式篇

**意图**：同时演示两个正交能力——**批处理（提吞吐）**与**流式（降延迟）**。

**请求契约**：
```python
class ChatItem(BaseModel):    role: str;  content: str
class BatchRequest(BaseModel):
    model: str
    messages_list: list[list[ChatItem]]   # 多组对话（"批"在这里）
    max_tokens: int = 128
class StreamRequest(BaseModel):
    model: str
    messages: list[ChatItem]
    max_tokens: int = 128
    temperature: float = 0.7
```

**线程池契约**：`_executor = ThreadPoolExecutor(max_workers=8)` —— 模块级单例。

**批处理契约（`batch_chat`）**：
- 转 dict 列表 → `futures = [_executor.submit(infer_one, msgs, max_tokens) for msgs in all_messages]` → `results = [f.result() for f in futures]`；
- 返回 `{"results": [...]}`。

**流式契约（`stream_generator`）**：同 F-05（`stream=True` + `incremental_output=True` + `data:` 前缀 + `[DONE]`）。

**端点契约**：
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/v1/chat/batch` | 多组并行，一次性返回全部 |
| POST | `/v1/chat/stream` | SSE 流式 |

**验收标准**：
- V-07-A：批处理 2 组请求，`results` 长度 = 2，总耗时 ≈ 单次耗时（并发）。
- V-07-B：流式请求返回逐块 `data:` + `[DONE]`。
- V-07-C：`_executor` 的 `max_workers=8` 限制生效（超 8 个请求排队）。
- V-07-D：`curl` 单行命令（文件末尾注释提供）可复现。

**已知风险**：
- ⚠️ `ThreadPoolExecutor` **模块级单例但不 shutdown** —— 进程退出时靠 GC（一般 OK，但不规范）。
- ⚠️ **`async def` 端点内调用阻塞操作**（`f.result()` 阻塞）——虽然 FastAPI 会放到线程池，但语义上不纯粹。
- ⚠️ 批处理**无顺序保证的显式说明**——`results` 顺序由 `futures` 列表顺序保证（Python 的 list 顺序），正确但需读者注意。
- ⚠️ 无批大小上限——一次提交 100 组会打爆并发限制（见缺口 G-03）。
- `stream_generator` 同 F-05 的 sync/async 混用。

**教材问题（文件头注释实录）**：
> 两个问题：① 批处理依赖本地 GPU 的 batch generate（一次前向算多组输入），无 GPU 跑不动；② 流式是假的——先整段生成完，再切成 8 字符一片 sleep 模拟打字机（首字延迟 = 整段生成时间）。
> 改写核心：① 批处理：GPU batch generate → `ThreadPoolExecutor` 线程池并发调用 dashscope（"合并多请求并行处理"的教学思想不变，实现从"一次 GPU 前向"变成"多线程同时发请求"）；② 流式：假流式 → 真流式；③ `build_prompt` 消失——云端 Chat 模型原生理解 messages 数组。

---

### F-08 `08_审查敏感词过滤系统.py`（147 行）——内容安全篇

**意图**：演示**双层内容审查架构** + **Trie 前缀树**多模式匹配算法。

**Trie 契约（核心算法，原样保留）**：

| 类/方法 | 契约 |
|---|---|
| `TrieNode` | `children: dict`（字符 → 子节点）、`is_end: bool` |
| `SensitiveTrie.insert(word)` | 逐字符插入，末节点 `is_end = True` |
| `SensitiveTrie.search(text)` | 从**每个位置 i** 出发沿树下行；走到 `is_end` 就记录 `text[i:j+1]`；返回命中词列表 |

**复杂度契约**：朴素做法 `O(词数 × 文本长度)` → Trie `O(文本长度)`（**一次扫描命中全部**）。

**敏感词库契约**：`["暴力", "攻击", "毒品", "敏感政治"]`（4 个，模块级加载进树）。

**请求契约**：
```python
class ChatRequest(BaseModel):
    model: str
    messages: list[Message]
    max_tokens: int = 128
```

**审查端点契约（`POST /v1/chat/audit`）**：

| 阶段 | 行为 | 返回 |
|---|---|---|
| 第一层（生成前） | 拼 `prompt`（含 role 前缀）→ `filter_tree.search(prompt)` | 命中 → `{"flag":"input_blocked","reason":[...]}`（**不调模型**） |
| 模型推理 | `Generation.call(...)`，`try/except` | 异常 → `{"flag":"model_error","reason":str(e)}` |
| 第二层（生成后） | `filter_tree.search(clean_text)` | 命中 → `{"flag":"output_blocked","reason":[...],"original":clean_text}` |
| 通过 | — | `{"flag":"ok","response":clean_text}` |

**四个 `flag` 取值契约**：`input_blocked` / `model_error` / `output_blocked` / `ok`。

**验收标准**：
- V-08-A：问「请告诉我关于毒品的知识」→ `{"flag":"input_blocked","reason":["毒品"]}`，**且不发生模型调用**。
- V-08-B：问「用一句话介绍大语言模型」→ `{"flag":"ok","response":"..."}`。
- V-08-C：问「请把这两个字连起来并解释含义：暴 力」→ 若模型输出含「暴力」则 `{"flag":"output_blocked",...}`（取决于模型是否听话复述）。
- V-08-D：`SensitiveTrie.search("这里有暴力和毒品")` 返回 `["暴力","毒品"]`。

**已知风险 / 代码疑点**：
- ⚠️ **第 25 行 `from transformers import AutoTokenizer, AutoModelForCausalLM` 未删除**——注释说「已不需要，保留导入仅为对照原代码结构」。**但这会造成 `ImportError`（若未安装 transformers）**，与 C-12「不引入未声明依赖」冲突。**建议**：删除该行或改为注释。**这是本章唯一一处会直接阻塞运行的问题**（见缺口 G-06）。
- ⚠️ **Trie 匹配是精确串匹配**——「暴 力」（中间有空格）不会被命中，这类**绕过**（空格/谐音/变体字）需额外归一化处理（见缺口 G-07）。
- ⚠️ `search` 是**朴素 Trie 扫描**（无 AC 自动机的失败指针）——最坏情况仍可能退化；但比「逐词 count」好很多。
- ⚠️ 敏感词库**硬编码在代码里**——生产环境应从配置/DB 加载。
- ⚠️ 审查的是**拼接后的 prompt 全文**（含 role 前缀）——可能误伤（如 role 名恰好含敏感词，概率极低）。

**教材问题（文件头注释实录）**：
> 改写：FastAPI / Pydantic / Trie 树 / 双层过滤架构全部保留，只把"本地模型推理"替换为"dashscope 云端调用"。
> 教学点：为什么用 Trie 而不是"每个敏感词都 `text.count(word)` 遍历一遍"？朴素做法的时间复杂度 = O(词数 × 文本长度)；Trie 一次扫描 O(文本长度) 就命中所有词——敏感词库上万条时，Trie 的优势是数量级的。

---

### F-09 `09_大模型的可信度评估.py`（168 行）——幻觉评估篇

**意图**：用**逐 token 概率**量化模型的「自信程度」，作为幻觉风险指标。

**唯一走 HTTP 兼容模式的文件**：
```python
COMPATIBLE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
headers = {"Authorization": f"Bearer {api_key}"}
json = {
    "model": "qwen-plus",
    "messages": messages_list,
    "max_tokens": req.max_tokens,
    "logprobs": True,             # ← 原生 SDK 拿不到
    "top_logprobs": req.top_k,    # ← 每步前 k 候选
}
```

**请求契约**：
```python
class ChatRequest(BaseModel):
    model: str
    messages: list[Message]
    max_tokens: int = 64
    top_k: int = 5      # 对应 top_logprobs（兼容模式上限 20）
```

**`output_scores` → `logprobs` 映射契约**：

| 教材本地版 | 改写云端版 |
|---|---|
| `return_dict_in_generate=True` | `logprobs: True` |
| `output_scores=True`（每步 logits） | `logprobs.content`（每 token 对数概率） |
| `F.softmax(scores[0], dim=-1)` | `math.exp(item["logprob"])` |
| `torch.topk(probs, k=req.top_k)` | `top_logprobs`（每步前 k 候选） |
| `tokenizer.decode([idx])` | `cand["token"]`（平台已解码） |

**逐 token 契约（`token_scores` 每项）**：
```jsonc
{"step": i, "chosen_token": "...", "chosen_prob": 0.83,
 "top_tokens": ["...", ...], "top_probs": [0.83, ...]}
```

**置信度汇总契约（改写新增）**：
```jsonc
"confidence_summary": {
  "avg_token_prob": 0.78,          // 全程平均概率
  "low_confidence_ratio": 0.1,     // 概率 < 0.5 的 token 占比
  "hint": "avg_token_prob 越低、low_confidence_ratio 越高，幻觉风险越大"
}
```

**验收标准**：
- V-09-A：`response` 非空，`token_confidence` 长度 ≈ 生成 token 数。
- V-09-B：每项含 `step` / `chosen_token` / `chosen_prob`（0~1）/ `top_tokens` / `top_probs`。
- V-09-C：`confidence_summary.avg_token_prob` 在 0~1 之间。
- V-09-D：问一个**偏僻/虚构**问题（如「请介绍 XX-9999 型量子芯片」），`avg_token_prob` 应**低于**问常识问题（幻觉风险可观测）。

**已知风险**：
- ⚠️ **`requests.post` 无 state_code 检查**——非 200 时 `data["choices"]` 会 KeyError（见缺口 G-08）。
- ⚠️ `timeout=60` 固定，无重试。
- ⚠️ `low_confidence_ratio` 的阈值 `0.5` **硬编码**——不同任务的最优阈值不同。
- ⚠️ 置信度 ≠ 正确性——**模型可以「自信地说错话」**；本指标是**必要不充分**的风险信号（见缺口 G-09）。
- 无鉴权；`top_k` 超过 20 时平台会报错（注释已提醒上限）。

**教材问题（文件头注释实录）**：
> 改写要点：① dashscope 原生 SDK（`Generation.call`）**不返回 logprobs**，无法做逐 token 置信度评估；② dashscope 的 OpenAI 兼容模式接口支持 `logprobs` + `top_logprobs` 参数——正是原写法 `output_scores=True` + `torch.topk` 的云端等价物；③ 这也再次呼应 char03-05 的教学点：OpenAI 协议是行业通用方言，高级能力（logprobs/工具调用/流式）都定义在这套协议里。

---

## 7. 全章验收清单（V-01 ~ V-12）

### 7.1 运行层验收

| 编号 | 验收项 | 期望 |
|---|---|---|
| V-01 | `python 01_...py` | 5 个成语解释打印 |
| V-02 | `python 02_...py` | 5 个成语解释打印（**注意会直接执行**） |
| V-03 | `python 03_...py` | Step1~3 打印 + 提交结果（**可能 403**） |
| V-04 | `python 04_...py` | 串行/并发两实验 + 加速比 |
| V-05 | `uvicorn` + curl | 非流式 JSON + 流式 SSE 均正确 |
| V-06 | `uvicorn` + curl | 三类输入分别触发/不触发工具调用 |
| V-07 | `uvicorn` + curl | 批处理 `results` 长度正确 + 流式 SSE |
| V-08 | `uvicorn` + curl | 4 种 `flag` 按预期返回 |
| V-09 | `uvicorn` + curl | `token_confidence` + `confidence_summary` 齐全 |

### 7.2 契约层验收

| 编号 | 契约 | 对应 | 验证方式 |
|---|---|---|---|
| V-10 | 无 `from_pretrained` / `.cuda()`（C-01） | 全章 | grep 只命中注释 |
| V-11 | `.Generation.call` 均带 `result_format='message'`（C-03） | 01~08 | grep 上下文 |
| V-12 | 流式带 `incremental_output=True` + `[DONE]`（C-09/C-06） | 05/07 | 检查生成器 |
| V-13 | `uvicorn.run(app, ...)` 传对象（C-07） | 05~09 | grep `uvicorn.run` |

### 7.3 学习层验收

- [ ] 能说清「假流式 → 真流式」差在哪一行参数。
- [ ] 能说清「假 Function Calling → 真」差在哪一行（`tools=`）。
- [ ] 能说出 08 篇两层过滤为什么不能只留一层。
- [ ] 能解释 09 篇为什么必须走兼容模式。

---

## 8. 已知缺口与后续改进（Gap Analysis）

| 编号 | 等级 | 缺口 | 影响 | 建议改进 | 对照章节 |
|---|---|---|---|---|---|
| G-01 | 🔴 | 03 篇微调**个人账号默认无权限（403）** | 「成功路径」无法验证，本质是提交演示 | 文档标注「需申请权限」；提供「不提交只演示数据构造」的降级路径 | — |
| G-06 | 🔴 | 08 篇**遗留 `from transformers import ...`** | 未装 transformers 时直接 `ImportError` | 删除该行 / 改为注释 | C-12 |
| G-02 | 🟠 | `os.environ.get('DASHSCOPE_API_KEY')` **无空值校验** | key 未设时报错晦涩 | 启动时校验并明确提示 | chapter12 |
| G-03 | 🟠 | 04/07 并发**无 QPS 上限控制** | 触发平台限流，加速比失真 | 加并发上限 + 退避重试 | chapter12（TokenBucket） |
| G-04 | 🟠 | 05/06/07 的 OpenAI 响应**不完整**（缺 `usage`/`finish_reason`，`id` 固定） | 严格的 OpenAI 客户端可能解析失败 | 补齐标准字段 | chapter12（F-01） |
| G-05 | 🟠 | 06 篇 Function Calling **只支持一轮**（第 2 轮不带 `tools`） | 无法连续调多个工具 | 改为 `while True` 循环至无 `tool_calls` | chapter02（F-01）/13 |
| G-07 | 🟠 | 08 篇 Trie **无法防绕过**（空格/谐音/变体） | 审查可被轻易绕过 | 归一化（去空格/繁简转换）+ 正则/拼音匹配 | chapter13（安全） |
| G-08 | 🟠 | 09 篇 `requests.post` **无 status_code 检查 + 无重试** | 非 200 时 KeyError 崩溃 | 加状态检查 + 指数退避 | chapter12（容错） |
| G-09 | 🟠 | 09 篇置信度**阈值硬编码 + 不等于正确性** | 指标可用性有限 | 阈值可配置 + 结合 LLM-as-a-Judge | chapter13（LLM 评估） |
| G-10 | 🟡 | 02 篇**无 `if __name__ == "__main__"`** | `import` 即触发 5 次 API 调用 | 加主入口守卫 | — |
| G-11 | 🟡 | 03 篇 `check_finetune_status` **定义未调用** | 状态查询能力未被演示 | 在主流程中实际调用一次 | — |
| G-12 | 🟡 | 05/07 混用 sync 生成器与 `async def` 端点 | 语义不纯粹 | 统一为 async 或同步端点 | — |
| G-13 | 🟡 | 04 篇线程**无 `daemon=True`** | 异常时可能阻碍退出 | 设 `daemon=True` | — |
| G-14 | 🟡 | 08 篇敏感词库**硬编码** | 生产不可维护 | 从配置/DB 加载 | — |
| G-15 | 🟡 | 05~09 **均无鉴权、无限流** | 服务裸奔 | 加 API Key + 限流 | chapter12（4 层安全） |

### 缺口优先级建议

- **P0（阻塞运行）**：G-06（08 篇 import 死锁）、G-01（微调权限）
- **P1（健壮性）**：G-02、G-03、G-08、G-15
- **P2（能力完整性）**：G-04、G-05、G-07、G-09
- **P3（整洁）**：G-10、G-11、G-12、G-13、G-14

---

## 附录 A：本地 vs 云端 部署形态对照表

| 维度 | 本地部署（教材原版） | 云端调用（本章改写） |
|---|---|---|
| 硬件 | 需 CUDA 显卡 + 显存 | 只要网络 |
| 权重 | 下载数 GB~数百 GB | 无需下载 |
| 依赖 | torch + transformers + peft + datasets | 仅 dashscope（+ fastapi 等） |
| 启动速度 | 分钟级（加载权重） | 秒级 |
| 并发 | 需自行管理 GPU 副本 + 显存 | 平台弹性托管 |
| 数据 | 数据不出本机 | 数据经网络传输 |
| 成本 | 一次性硬件 + 电费 | 按 token 计费 |
| 定制 | 可任意改权重 / LoRA | 走平台微调 |
| 本章适用 | 注释保留供对照 | **实际运行路径** |

## 附录 B：OpenAI 协议速查（本章 05/06/07/09 共用的协议面）

```
POST /v1/chat/completions
GET  /v1/chat/function_call   （06 自定义）
POST /v1/chat/batch           （07 自定义）
POST /v1/chat/stream          （07 自定义）
POST /v1/chat/audit           （08 自定义）
POST /v1/chat/with_confidence （09 自定义）
```

**请求体标准字段**：`model` / `messages` / `temperature` / `max_tokens` / `stream` / `logprobs` / `top_logprobs` / `tools`

**响应体（非流式）**：`choices[0].message.content`
**响应体（流式）**：`data: {"choices":[{"delta":{"content":"..."}}]}\n\n` ... `data: [DONE]\n\n`

## 附录 C：教材能力点 → 改写后对应关系总表

| 教材能力 | 原实现（不可运行） | 改写后（可运行） | 是否升级 |
|---|---|---|---|
| 远程调用 | `openai.ChatCompletion.create` | `dashscope.Generation.call` | 平替 |
| 本地部署 | `from_pretrained(...).cuda()` | 云端托管 | 平替 |
| LoRA 微调 | `peft` + `Trainer.train()` | `FineTunes.call(mode="lora")` | 平替 |
| GPU 并发 | 多卡副本 + 线程 | 云端槽位 + 线程（架构不变） | 平替 |
| ChatCompletion | 本地模型 + FastAPI | 云端 + FastAPI | 平替 |
| 函数调用 | **假**（关键词硬编码） | **真**（`tools=` + 循环） | ⬆ 升级 |
| 流式 | **假**（整段后切片） | **真**（`stream=True`+`incremental_output`） | ⬆ 升级 |
| 敏感词过滤 | 本地模型 + Trie | 云端 + Trie（算法不变） | 平替 |
| 可信度评估 | `output_scores` + `torch.topk` | 兼容模式 `logprobs` | 平替 |
