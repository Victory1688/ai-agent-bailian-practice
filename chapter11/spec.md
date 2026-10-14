# chapter11 · Spec（规格说明书）

> **本章主题**：把 Agent 部署成真实 Web 服务 —— 基于 Flask 的 A2A Agent HTTP 端点
> **对应教材**：《AI Agent 开发：零基础构建复合智能体》例 11-1（API 与 SDK 支持）
> **代码规模**：1 个文件 / 350 行
> **平台改写目标**：阿里百炼（DashScope SDK）+ 生产级错误处理 + A2A Agent Card 衔接
> **文档定位**：上篇讲"为什么这样设计、怎么学"，下篇讲"代码契约是什么、怎样算验收通过"
> **生成依据**：`01_实现基于Flask的Web服务.py` 源码逐行核对 + `arch_汇总说明.md` 实测记录（**未臆造**）

---

# 上篇：意图与学习路径

## 1. 章意图（Why）

### 1.1 一句话命题

> **理解了协议（char10）之后，怎么把 Agent 从"进程内对象"变成"外部可调用的 Web 服务"？**

char10 的 A2A 全部发生在 Python `main` 里 —— `A2AServer` 和 `A2AClient` 都是进程内对象，靠直接函数调用"模拟"通信。
char11 迈出**部署的第一步**：用 Flask 把 Agent 暴露成真实 HTTP 端点，让 APP、网站、其他 Agent 都能通过 HTTP POST 调用它。

### 1.2 全章 6 个核心概念（教材主线）

| # | 概念 | 在本章的落点 | 代码位置 |
|---|------|-------------|---------|
| 1 | **HTTP 服务框架** | Flask 应用 + 路由装饰器 | `app = Flask(__name__)`、`@app.route(...)` |
| 2 | **REST 端点设计** | 4 个端点：发现/健康/问答/错误处理 | `/well-known/agent.json`、`/health`、`/ask`、404/405 handler |
| 3 | **请求-响应契约** | 输入 JSON 字段 + 输出 JSON 字段 + 状态码 | `ask()` 的 Step 1~4，`jsonify({...})` |
| 4 | **多模型后端分发** | 一个端点背后挂两个 LLM | `if model == "qwen": ... else: ...` |
| 5 | **分层错误处理** | try/except 三层 + 6 种状态码 | `ask()` 的 `except ValueError / RequestException / Exception` |
| 6 | **A2A 协议衔接** | Agent Card 声明式身份 | `AGENT_CARD` 常量 + `agent_card()` |

### 1.3 教材原版的三类问题（已注释保留在源码 24-47 行）

源码开头把教材原版的"死法"逐条注释保留，这是本章最有价值的学习材料：

| 编号 | 教材原版问题 | 后果 | 改写方向 |
|------|-------------|------|---------|
| ① | **DashScope 端点过时**：用 `api/v1/services/aigc/text-generation/generation` | 该 v1 端点已下线，请求必然失败 | 改用 `dashscope.Generation.call`（与前 10 章统一） |
| ② | **API Key 命名混乱**：`QWEN_API_KEY` 实际指向 DashScope | 读者按字面理解会去申请"通义千问的 Key" | 统一为 `DASHSCOPE_API_KEY`（与前 10 章一致） |
| ③ | **错误处理粗糙**：只判断 `status_code == 200` | 任何非 200 都变成静默失败，无错误信息 | try/except 三层 + 6 种 HTTP 状态码 |
| ④ | **无 A2A Agent Card 端点** | 与 char10 协议层彻底脱节 | 新增 `GET /well-known/agent.json` |
| ⑤ | **无健康检查** | 生产部署不可接受（无法做存活探针） | 新增 `GET /health` |
| ⑥ | **无 main self-test** | 只能 `flask run` 手动验证，无法自动回归 | 后台线程启 Flask → self-test → 自动退出 |

> **学习提醒**：这 6 条不是"教材写错了"那么简单 —— 它们精确对应了一个玩具 Demo 走向生产服务时必须补齐的 6 块拼图。**看懂这 6 条，就理解了"能跑的代码"和"能上线的服务"的差距。**

### 1.4 改写映射表（教材 → 阿里百炼平台）

| 维度 | 教材原版 | 本章改写后 | 落点 |
|------|---------|-----------|------|
| LLM SDK | `requests.post` 直调过时 URL | `dashscope.Generation.call` | `call_dashscope()` |
| API Key 变量 | `QWEN_API_KEY` | `DASHSCOPE_API_KEY` | 模块级 58 行 |
| 模型名 | `qwen3-14b`（旧格式参数） | `qwen-plus` + `result_format='message'` | `DASHSCOPE_MODEL` |
| 参数格式 | `{"model":..., "input": prompt}` | `messages=[{role, content}]` | `call_dashscope()` |
| 响应路径 | 未明确 | `response.output.choices[0].message.content` | `call_dashscope()` 返回 |
| 第二后端 | 教材提及但未落地 | `call_deepseek()` 完整实现 | `requests.post` + v1 端点 |
| 服务框架 | Flask（保留） | Flask 3.1.3（保留） | `app = Flask(__name__)` |
| 发现端点 | 无 | `GET /well-known/agent.json` | `agent_card()` |
| 健康端点 | 无 | `GET /health` | `health()` |
| 错误处理 | `status_code == 200` | try/except 三层 | `ask()` Step 3 |
| main 入口 | `app.run(port=5000)` 阻塞 | 后台线程 + self-test + `sys.exit` | `__main__` 块 |

### 1.5 与前后章的衔接

```
char09 多 Agent 协作（进程内调度）
   ↓
char10 A2A 协议层（进程内对象对话：Agent Card / Message / Task / JSON-RPC）
   ↓
char11 Flask HTTP 部署 ← 本章：协议层 → 真实 Web 端点（外部可调用）
```

**char11 不是"从零开始"，而是 char10 协议层的 HTTP 暴露。** 映射关系：

| char10 进程内概念 | char11 HTTP 端点 |
|------------------|-----------------|
| Agent Card 常量 | `GET /.well-known/agent.json` |
| `A2AServer.message_send()` | `POST /ask` |
| `A2AServer.verify_auth()` | `ask()` 里加 Authorization 检查（可扩展） |
| `dashscope.Generation.call` | `call_dashscope()` 复用同样模式 |
| JSON-RPC 信封 | 可扩展：新增 `POST /a2a`（与 char10 完全对齐） |

---

## 2. 学习路径表

### 2.1 文件清单（1 个文件 / 350 行）

| 序号 | 文件名 | 行数 | 学习重点 |
|------|--------|------|---------|
| 01 | `01_实现基于Flask的Web服务.py` | 350 | Flask 路由设计 + 分层错误处理 + 多后端分发 + self-test |

> **本章只有 1 个文件** —— 这是 13 章里最"聚焦"的一章：它不讲新算法，讲的是**工程化落地**。

### 2.2 源码分段阅读表

| 区段 | 行号 | 内容 | 读完应该知道 |
|------|------|------|-------------|
| A. 教材问题注释 | 1-47 | 6 条问题 + 改写说明 + 原版代码注释保留 | 玩具 Demo 的 6 个缺口 |
| B. 导入与常量 | 49-67 | Flask / dashscope / requests 初始化 | 三个后端依赖 + 端口 + 模型名 |
| C. Agent Card | 70-103 | `AGENT_CARD` 字典 | A2A 声明式身份的两个 skills |
| D. LLM 调用层 | 106-154 | `call_dashscope()` / `call_deepseek()` | 两种调用方式的差异 |
| E. 路由层 | 157-244 | 4 个路由 + 2 个错误处理器 | 每个端点的输入输出契约 |
| F. self-test | 247-328 | `_wait_server()` / `run_self_test()` | 4 项自动验收 |
| G. main 入口 | 331-350 | 后台线程启服务 + selftest + 退出码 | 为什么用 `threading` |

### 2.3 推荐学习顺序

```
1. 读 A 段（教材 6 条问题）        → 建立"工程化 vs 玩具"的问题意识
2. 读 C 段（AGENT_CARD）           → 理解 A2A 声明式身份
3. 读 D 段（两个 call_* 函数）     → 对比 SDK 调用 vs HTTP 直调
4. 读 E 段（路由层）               → 掌握 4 个端点的请求-响应契约
5. 读 F+G 段（self-test + main）   → 学会"服务代码如何自验证"
6. 直接运行脚本                     → 看 4 项 self-test 输出
```

---

## 3. 工程主线（本章 3 条主线）

### 主线一：**服务化的本质 = 把函数契约翻译成 HTTP 契约**

同一个"问答"能力，在 char08 是 `agent.process(user_input)`，在 char11 是 `POST /ask`。
变化的是**边界**，不变的是**契约**：

```
函数契约                     HTTP 契约
─────────────────────       ──────────────────────────
输入: user_input (str)  →    输入: {"question": "...", "model": "...", "system_prompt": "..."}
处理: agent 内部逻辑     →    处理: 参数校验 → 分发 → LLM 调用
输出: response (str)    →    输出: {"answer", "model", "elapsed_ms", "timestamp"}
异常: raise Exception   →    异常: HTTP 4xx/5xx + {"error": {"code", "message"}}
```

**关键洞察**：`ask()` 函数的四步结构（解析 → 校验 → 调用 → 返回），就是把函数体内的"顺序执行"显式拆成了可独立失败、可独立反馈的四个阶段。

### 主线二：**错误处理的层次感 —— 谁的错误，谁的锅**

`ask()` Step 3 的三段 except，精确对应了三类责任方：

```python
except ValueError as e:              # → 400：调用方参数问题（如 Key 缺失）
except requests.RequestException:    # → 502：上游 API 的锅（Bad Gateway）
except Exception:                    # → 500：本服务自己的锅（Internal Error）
```

**HTTP 状态码语义对照**：

| 状态码 | 语义 | 本章触发场景 | 责任方 |
|--------|------|-------------|--------|
| 400 | Bad Request | JSON 解析失败 / question 为空 / model 不支持 / Key 缺失 | **调用方** |
| 404 | Not Found | 路径不存在 | 调用方 |
| 405 | Method Not Allowed | GET 调 POST 端点 | 调用方 |
| 500 | Internal Server Error | 未知内部异常 | **本服务** |
| 502 | Bad Gateway | DeepSeek API 超时/报错 | **上游** |

> **工程纪律**：4xx 是"你的问题"，5xx 是"我的问题"。混淆二者会让调用方无从排障 —— 这也是教材原版 `status_code == 200` 最大的问题：**它把所有错误都变成了没有身份的 500。**

### 主线三：**"能跑"与"能上线"的 6 块拼图**

教材原版 6 条问题，正好构成生产化 checklist：

```
① 端点正确性      → 能不能调通（SDK vs 过期 URL）
② 配置规范        → 配置命名是否自解释（Key 命名统一）
③ 错误可观测      → 出错时能不能定位（分层 try/except）
④ 服务可发现      → 别人怎么知道你能干什么（Agent Card）
⑤ 服务可探活      → 负载均衡怎么判断你活着（/health）
⑥ 服务可自验证    → CI 里怎么自动回归（main self-test）
```

**这 6 条可以平移到任何 Web 服务** —— 这是本章超出"Agent"范畴、值得带走的通用工程知识。

---

## 4. 学习检查清单

读完本章，请自查以下问题（答不上来 = 需要重读）：

### 概念层
- [ ] 为什么"进程内对象通信"（char10）不够，还需要 HTTP 部署（char11）？
- [ ] A2A Agent Card 的作用是什么？为什么路径必须是 `/.well-known/agent.json`？
- [ ] `/health` 端点和 `/ask` 端点在同一次故障中表现有何不同？（提示：探活 vs 业务）
- [ ] 为什么 502 归给"上游"，500 归给"自己"？

### 代码层
- [ ] `call_dashscope()` 为什么必须传 `result_format='message'`？不传会怎样？
- [ ] 响应路径 `response.output.choices[0].message.content` 中每一层分别是什么？
- [ ] `call_deepseek()` 里 `resp.raise_for_status()` 的作用是什么？不写会怎样？
- [ ] `request.get_json(force=True, silent=False)` 的两个参数分别控制什么？
- [ ] 为什么 `app.run()` 要放在**后台线程**里（`daemon=True`）？
- [ ] `use_reloader=False` 是为了防止什么？（提示：main 重启 → 端口冲突）

### 工程层
- [ ] 如果要加第三个模型（如 Claude），需要改哪几处？（答：加一个 `call_xxx()` + `/ask` 里加 `elif` + Agent Card 加一个 skill）
- [ ] 为什么 404/405 也要自定义 JSON 错误处理？（答：统一错误格式，调用方无需解析 HTML）
- [ ] 生产环境下 `app.run()` 应该换成什么？（答：waitress / gunicorn）

---

# 下篇：契约与验收

## 5. 全局技术约束（C-xx）

| 编号 | 约束 | 说明 | 违反后果 |
|------|------|------|---------|
| C-01 | **框架版本** | Flask ≥ 3.0（实测 3.1.3） | 低版本无 `request.get_json(force=...)` 部分行为 |
| C-02 | **DashScope 必须走 SDK** | `dashscope.Generation.call`，禁止直调 `api/v1/...` | v1 端点已下线，请求必然失败 |
| C-03 | **必须传 `result_format='message'`** | 否则返回结构不是 OpenAI 风格，`response.output.choices` 取不到 | `AttributeError` / 取到 None |
| C-04 | **API Key 命名统一** | `DASHSCOPE_API_KEY`（不接受 `QWEN_API_KEY`） | 与前 10 章环境变量不一致，切换困难 |
| C-05 | **DeepSeek 用标准 v1 端点** | `https://api.deepseek.com/v1/chat/completions` | 无 SDK 依赖，用 `requests` 直调 |
| C-06 | **响应必须为 JSON** | 所有路径（含 404/405/异常）统一 `jsonify` | 调用方需要区分 HTML/JSON 两套解析逻辑 |
| C-07 | **错误格式统一** | `{"error": {"code": int, "message": str}}` | 调用方错误处理代码分叉 |
| C-08 | **端口固定 5000** | `PORT = 5000` 常量 | Agent Card 的 endpoint 字段硬引用该端口 |
| C-09 | **Flask 必须后台线程启动** | `threading.Thread(daemon=True)` | 阻塞主线程 → self-test 永不执行 |
| C-10 | **`use_reloader=False`** | 禁用 Flask 自动重载 | reloader 会 fork 子进程 → 端口冲突 / self-test 打到自己 |
| C-11 | **self-test 必须有超时** | `_wait_server(timeout=10)` | 服务启动失败时脚本永久挂起 |
| C-12 | **main 返回退出码** | `sys.exit(0 if success else 1)` | CI 无法判定成败 |
| C-13 | **必须注册 404/405 handler** | `@app.errorhandler(404/405)` | Flask 默认返回 HTML 错误页，破坏 JSON 契约 |
| C-14 | **`elapsed_ms` 从调用前开始计时** | `t0 = time.time()` 放在 Step 3 之前 | 把参数校验时间也算进去，指标失真 |

---

## 6. 逐文件契约（F-xx）

### F-01：`01_实现基于Flask的Web服务.py`（350 行）

#### F-01.0 文件级定位

| 项 | 内容 |
|----|------|
| **意图** | 把 Agent 问答能力暴露为 Flask HTTP 服务，支持双 LLM 后端，具备 A2A 发现、健康检查、分层错误处理与自动 self-test |
| **输入** | 环境变量 `DASHSCOPE_API_KEY`（必需）、`DEEPSEEK_API_KEY`（可选）；HTTP 请求 |
| **处理** | 4 个路由 + 2 个错误处理器 + 2 个 LLM 调用函数 + self-test |
| **输出** | HTTP JSON 响应；控制台 self-test 报告；进程退出码 |
| **依赖** | `flask`、`dashscope`、`requests`、`os`、`sys`、`time`、`threading` |

---

#### F-01.1 模块级常量与初始化（49-67 行）

**意图**：集中声明服务运行参数与上游凭证。

```python
import os, sys, time, threading, requests
from flask import Flask, request, jsonify

import dashscope
dashscope.api_key = os.environ.get("DASHSCOPE_API_KEY")

app = Flask(__name__)

PORT = 5000
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DASHSCOPE_MODEL = "qwen-plus"
```

| 契约项 | 内容 |
|--------|------|
| **输入** | 环境变量 `DASHSCOPE_API_KEY` / `DEEPSEEK_API_KEY` |
| **处理** | 模块导入时读取环境变量并绑定到 `dashscope.api_key` |
| **输出** | 模块级 `app` / `PORT` / `DASHSCOPE_MODEL` 等常量 |
| **验收标准** | ① `DASHSCOPE_API_KEY` 缺失时 `dashscope.api_key` 为 `None`，调用时才报错（**非导入时报错**）② `DEEPSEEK_API_KEY` 为惰性读取（`call_deepseek` 内校验） |
| **已知风险** | Key 缺失只在**调用时**暴露，而非启动时 fail-fast。生产建议启动即校验 |

> **契约要点**：Key 读取策略是**惰性**的 —— 保证 `import` 阶段永不失败（便于 CI 在无 Key 环境下做静态检查）。

---

#### F-01.2 `AGENT_CARD` 常量（70-103 行）

**意图**：以声明式方式描述本 Agent 的身份与能力，供外部发现。

```python
AGENT_CARD = {
    "name": "flask-chat-agent",
    "description": "基于 Flask 的 A2A 协议 Agent 服务，支持 DashScope (qwen-plus) 和 DeepSeek 双模型",
    "endpoint": f"http://localhost:{PORT}/a2a",
    "version": "1.0.0",
    "authentication": {"schemes": ["bearer"], "bearer": {...}},
    "capabilities": {"streaming": False, "pushNotifications": False},
    "skills": [
        {"id": "chat_dashscope", "description": "...", "tags": ["问答","dashscope","qwen"], ...},
        {"id": "chat_deepseek", "description": "...", "tags": ["问答","deepseek"], ...},
    ],
}
```

| 契约项 | 内容 |
|--------|------|
| **字段** | `name` / `description` / `endpoint` / `version` / `authentication` / `capabilities` / `skills` |
| **skills 数组** | 长度必须 **恰好为 2**（`chat_dashscope` + `chat_deepseek`） |
| **验收标准** | `/well-known/agent.json` 返回的 JSON 中 `name == "flask-chat-agent"` 且 `len(skills) == 2` |
| **已知风险** | ① `endpoint` 指向 `http://localhost:5000/a2a`，但 **`/a2a` 路由并未实现**（arch 文档第八节列为"生产级扩展方向 ④"）→ 这是"声明超前于实现"的典型例子 ② `endpoint` 硬编码 `localhost`，生产部署需改为真实域名 |

> **教学要点**：Agent Card 是**声明式契约** —— 它描述了"我承诺提供什么"。`capabilities.streaming=False` 明确告知调用方"我不支持流式"，避免调用方误期待 SSE。

---

#### F-01.3 `call_dashscope()`（110-126 行）

**意图**：用 dashscope SDK 调用 `qwen-plus`，与前 10 章保持统一的调用模式。

```python
def call_dashscope(prompt: str, system_prompt: str = "你是一个专业的问答助手，回答简洁准确。") -> str:
    response = dashscope.Generation.call(
        model=DASHSCOPE_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=512,
        result_format='message',      # ★ 强制必需
    )
    return response.output.choices[0].message.content
```

| 契约项 | 内容 |
|--------|------|
| **输入** | `prompt: str`（用户问题）、`system_prompt: str`（默认"你是一个专业的问答助手，回答简洁准确。"） |
| **处理** | 组装 `messages`（system + user 两段）→ `Generation.call` |
| **输出** | `str` —— LLM 生成的文本 |
| **参数** | `model="qwen-plus"`、`temperature=0.3`（偏确定性）、`max_tokens=512`、`result_format='message'` |
| **响应路径** | `response.output.choices[0].message.content` |
| **验收标准** | ① 传入 `"1+1 等于几？"` 返回含数字的答案 ② 未设置 Key 时抛异常（由上层转 500/400） |
| **已知风险** | ① **未做 SDK 调用异常捕获** —— 依赖 `ask()` 的兜底 `except Exception` ② `temperature=0.3` 是问答场景的合理值，但硬编码不可配置 ③ 无重试机制（网络抖动即失败） |

**关键契约：`result_format='message'`**

| 取值 | 返回结构 | `response.output.choices` |
|------|---------|--------------------------|
| 不传（默认 `'text'`） | `output.text` | ❌ 不存在，`AttributeError` |
| `'message'` | `output.choices[0].message.content` | ✅ OpenAI 风格 |

> **这是前 10 章反复踩过的坑，本章作为"统一模式"再次固化。**

---

#### F-01.4 `call_deepseek()`（129-154 行）

**意图**：用 `requests` 直调 DeepSeek Chat API（无 SDK 依赖），验证"一个端点挂多个后端"的扩展性。

```python
def call_deepseek(prompt: str, system_prompt: str = "你是一个专业的问答助手，回答简洁准确。") -> str:
    if not DEEPSEEK_API_KEY:
        raise ValueError("DEEPSEEK_API_KEY 环境变量未设置")     # → 上层转 400
    headers = {"Content-Type": "application/json",
               "Authorization": f"Bearer {DEEPSEEK_API_KEY}"}
    data = {"model": "deepseek-chat",
            "messages": [{"role":"system","content":system_prompt},
                         {"role":"user","content":prompt}],
            "max_tokens": 512}
    resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=data, timeout=30)
    resp.raise_for_status()                                      # → 上层转 502
    choices = resp.json().get("choices", [])
    if not choices:
        raise ValueError("DeepSeek 响应无 choices")
    return choices[0]["message"]["content"]
```

| 契约项 | 内容 |
|--------|------|
| **输入** | 同 `call_dashscope()` |
| **前置校验** | `DEEPSEEK_API_KEY` 缺失 → `raise ValueError`（→ HTTP 400） |
| **请求** | POST + `Bearer` 认证 + `json=data` + `timeout=30` |
| **输出** | `str` —— `choices[0]["message"]["content"]` |
| **验收标准** | ① Key 缺失时抛 `ValueError` ② 上游 4xx/5xx 时 `raise_for_status()` 抛 `HTTPError`（`RequestException` 子类 → 502） ③ 响应无 `choices` 时抛 `ValueError` |
| **已知风险** | ① `timeout=30` 较长，网关层需另设超时 ② 无重试 ③ `data` 里未传 `temperature`（用 DeepSeek 默认值，与 qwen 的 0.3 不一致） |

**两后端对照**

| 维度 | `call_dashscope()` | `call_deepseek()` |
|------|-------------------|------------------|
| 调用方式 | dashscope SDK | `requests.post` |
| 认证 | SDK 内部读取 `dashscope.api_key` | 显式 `Bearer` header |
| 端点 | SDK 内置 | `https://api.deepseek.com/v1/chat/completions` |
| 超时控制 | SDK 默认 | `timeout=30` |
| 错误传播 | 裸异常 → 上层 `except Exception` → 500 | `RequestException` → 502（**更精确**） |
| `temperature` | 0.3（显式） | 未传（默认） |
| 响应取值 | 属性链 `.output.choices[0].message.content` | 字典链 `["choices"][0]["message"]["content"]` |

> **工程洞察**：`call_deepseek()` 的错误处理**比** `call_dashscope()` **更规范** —— `raise_for_status()` + `ValueError` 提供了精确的分类。`call_dashscope()` 因为"信任 SDK"，反而丢失了错误分类能力（统一落到 500）。这是 SDD 值得记录的**不对称**。

---

#### F-01.5 `agent_card()` 路由（161-167 行）

```python
@app.route("/well-known/agent.json", methods=["GET"])
def agent_card():
    return jsonify(AGENT_CARD)
```

| 契约项 | 内容 |
|--------|------|
| **方法** | GET |
| **输入** | 无 |
| **输出** | `AGENT_CARD` 的 JSON 序列化结果，HTTP 200 |
| **验收标准** | `name == "flask-chat-agent"`、`len(skills) == 2` |
| **已知风险** | A2A 规范路径是 **`.well-known`（带点）**。源码注释写"规范路径 `/.well-known/agent.json`"，但**装饰器实际注册的是 `/well-known/agent.json`（无点）** —— 见 F-01.9 缺口记录。 |

---

#### F-01.6 `health()` 路由（170-178 行）

```python
@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "version": AGENT_CARD["version"],
        "models": [DASHSCOPE_MODEL, "deepseek-chat"],
    })
```

| 契约项 | 内容 |
|--------|------|
| **方法** | GET |
| **输出** | `{"status": "ok", "timestamp": "...", "version": "1.0.0", "models": ["qwen-plus", "deepseek-chat"]}` |
| **验收标准** | ① `status == "ok"` ② `version` 与 `AGENT_CARD["version"]` **单一来源**（不重复硬编码） |
| **已知风险** | ① **不检查上游可达性** —— 即使 DashScope 挂了也返回 `ok`（"浅健康检查"） ② 无 `/ready` 与 `/live` 区分（K8s 场景不足） |

> **设计亮点**：`version` 字段从 `AGENT_CARD["version"]` 读取，避免了两处版本号不一致的经典 bug。

---

#### F-01.7 `ask()` 路由（181-234 行）★ 核心

**意图**：问答核心业务路由，四阶段处理 + 分层错误反馈。

```python
@app.route("/ask", methods=["POST"])
def ask():
    # Step 1: Content-Type 校验 + JSON 解析
    try:
        data = request.get_json(force=True, silent=False)
    except Exception as e:
        return jsonify({"error": {"code": 400, "message": f"Invalid JSON: {e}"}}), 400
    if not data:
        return jsonify({"error": {"code": 400, "message": "Request body is empty"}}), 400

    # Step 2: 参数校验
    question = data.get("question", "").strip()
    if not question:
        return jsonify({"error": {"code": 400, "message": "question field is required"}}), 400
    model = data.get("model", "qwen").lower()
    system_prompt = data.get("system_prompt", "你是一个专业的问答助手，回答简洁准确。")
    if model not in ("qwen", "deepseek"):
        return jsonify({"error": {"code": 400, "message": f"Unsupported model: {model}"}}), 400

    # Step 3: 调用 LLM（分层错误处理）
    t0 = time.time()
    try:
        if model == "qwen":
            answer = call_dashscope(question, system_prompt)
        else:
            answer = call_deepseek(question, system_prompt)
    except ValueError as e:
        return jsonify({"error": {"code": 400, "message": str(e)}}), 400
    except requests.RequestException as e:
        return jsonify({"error": {"code": 502, "message": f"Upstream API error: {e}"}}), 502
    except Exception as e:
        return jsonify({"error": {"code": 500, "message": f"Internal error: {e}"}}), 500

    elapsed = int((time.time() - t0) * 1000)

    # Step 4: 返回结果
    return jsonify({
        "answer": answer,
        "model": f"{'qwen-plus' if model == 'qwen' else 'deepseek-chat'}",
        "elapsed_ms": elapsed,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
```

**请求契约**

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `question` | str | ✅ | — | 用户问题，`strip()` 后不可为空 |
| `model` | str | ❌ | `"qwen"` | 枚举 `qwen` \| `deepseek`，大小写不敏感（`.lower()`） |
| `system_prompt` | str | ❌ | "你是一个专业的问答助手，回答简洁准确。" | 系统提示词 |

**响应契约（成功 200）**

| 字段 | 类型 | 说明 |
|------|------|------|
| `answer` | str | LLM 生成的答案 |
| `model` | str | 实际使用的模型名（`qwen-plus` 或 `deepseek-chat`） |
| `elapsed_ms` | int | 从 Step 3 开始的耗时（毫秒） |
| `timestamp` | str | UTC ISO8601（`%Y-%m-%dT%H:%M:%SZ`） |

**响应契约（失败）**

`{"error": {"code": <http_code>, "message": "<描述>"}}` + 对应 HTTP 状态码。

**错误矩阵**

| 触发条件 | 抛出点 | 捕获点 | HTTP | message |
|---------|-------|-------|------|---------|
| body 非合法 JSON | `get_json` | Step 1 | 400 | `Invalid JSON: {e}` |
| body 为空 | — | Step 1 | 400 | `Request body is empty` |
| `question` 为空/全空格 | — | Step 2 | 400 | `question field is required` |
| `model` 非枚举值 | — | Step 2 | 400 | `Unsupported model: {model}` |
| `DEEPSEEK_API_KEY` 缺失 | `call_deepseek` | Step 3 `ValueError` | 400 | `DEEPSEEK_API_KEY 环境变量未设置` |
| DeepSeek 响应无 choices | `call_deepseek` | Step 3 `ValueError` | 400 | `DeepSeek 响应无 choices` |
| 上游 API 超时 / 非 2xx | `requests` | Step 3 `RequestException` | 502 | `Upstream API error: {e}` |
| 其他未知异常 | 任意 | Step 3 `Exception` | 500 | `Internal error: {e}` |

| 契约项 | 内容 |
|--------|------|
| **验收标准** | ① 空 `question` 返回 400 ② `model=qwen` + 合法问题返回 200 且 `answer` 非空 ③ `elapsed_ms` 为正整数 ④ `model` 字段返回真实模型名（非用户输入值） |
| **已知风险** | ① **`system_prompt` 无长度限制** —— 恶意超长输入可致 token 爆量 ② **无请求限流**（rate limit）—— `/ask` 可被无限刷 ③ `elapsed_ms` 只覆盖 LLM 调用，不含参数校验和 JSON 序列化 ④ `force=True` 使 Content-Type 校验失效（见 F-01.9 G-03） |
| **设计亮点** | ① `model` 字段**回显真实模型名**而非用户输入（`qwen` → `qwen-plus`），避免调用方收到模糊信息 ② 三段 `except` 按"责任方"精确分层 |

---

#### F-01.8 错误处理器（237-244 行）

```python
@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": {"code": 404, "message": "Not Found"}}), 404

@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({"error": {"code": 405, "message": "Method Not Allowed"}}), 405
```

| 契约项 | 内容 |
|--------|------|
| **意图** | 覆盖 Flask 默认 HTML 错误页，保证**所有响应都是 JSON** |
| **输出** | 与业务错误同格式的 `{"error": {"code", "message"}}` |
| **验收标准** | GET `/ask` → 405 JSON；GET `/nonexistent` → 404 JSON |
| **已知风险** | 只处理 404/405，**未处理 500**（未加 `@app.errorhandler(500)`）—— 未捕获异常仍会返回 Flask 默认 HTML 页 |

---

#### F-01.9 self-test（247-328 行）

**意图**：让服务代码具备**自验证**能力 —— 不依赖手工 curl，脚本跑完即知成败。

```python
def _wait_server(url: str, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            requests.get(url, timeout=2)
            return True
        except requests.RequestException:
            time.sleep(0.5)
    return False

def run_self_test():
    base = f"http://localhost:{PORT}"
    ok = True
    # 等待就绪 → Test1 /health → Test2 agent.json → Test3 /ask(qwen) → Test4 参数校验
    ...
    return ok
```

**四项测试契约**

| 测试 | 方法 + 路径 | 断言 | 期望输出 |
|------|------------|------|---------|
| Test 1 | GET `/health` | `data["status"] == "ok"` | `[通过] status=ok, version=1.0.0` |
| Test 2 | GET `/well-known/agent.json` | `name == "flask-chat-agent"` 且 `len(skills) == 2` | `[通过] name=flask-chat-agent, skills=2` |
| Test 3 | POST `/ask` `{"question":"1+1 等于几？请直接给出数字。","model":"qwen"}` | `data.get("answer")` 非空 | `[通过] answer=2..., elapsed=801ms` |
| Test 4 | POST `/ask` `{"question":"","model":"qwen"}` | `r.status_code == 400` | `[通过] 空 question 返回 400` |

| 契约项 | 内容 |
|--------|------|
| **验收标准** | 四项全通过 → 打印"全部 4 项 self-test 通过"；任一失败 → "存在失败项" |
| **已知风险** | ① **Test 3 是真实 API 调用**，消耗 token 且依赖网络 —— CI 中不稳定 ② Test 3 的断言过弱（只要有 answer 即可，不校验内容正确性）③ **无 Test 5 验证 deepseek 分支**（因 `DEEPSEEK_API_KEY` 可选，故意跳过）④ `/well-known` 路径（无点）与 A2A 规范 `.well-known` 不一致 |

---

#### F-01.10 main 入口（331-350 行）

```python
if __name__ == "__main__":
    def _run_server():
        app.run(host="0.0.0.0", port=PORT, use_reloader=False)

    server_thread = threading.Thread(target=_run_server, daemon=True)
    server_thread.start()

    success = run_self_test()

    print(f"\n服务已在后台线程启动，可手动调用：")
    print(f"  curl http://localhost:{PORT}/health")
    ...
    sys.exit(0 if success else 1)
```

| 契约项 | 内容 |
|--------|------|
| **意图** | 一行命令完成"启服务 → 自测 → 退出"，适配 CI |
| **关键设计** | ① 后台线程（`daemon=True`）避免 `app.run()` 阻塞 ② `use_reloader=False` 防止 reloader fork 导致端口冲突 ③ `sys.exit(0/1)` 提供 CI 可读的退出码 |
| **验收标准** | 运行脚本 → 输出 4 项 self-test → 进程自动退出，退出码 0（全通过）或 1（有失败） |
| **已知风险** | ① `host="0.0.0.0"` 暴露到局域网，开发机有安全风险 ② 服务随 `sys.exit` 终止，**无法作为常驻服务使用** —— 生产需去掉 main 块，改用 `waitress-serve` / `gunicorn` ③ 脚本只输出 curl 提示，不实际常驻 |

> **设计哲学**：这个 main 块的定位是 **"可执行文档"** —— 它证明了"服务能以编程方式启动、自测、关闭"，而不是"提供一个生产服务进程"。真实部署应绕过该块。

---

## 7. 全章验收清单（V-xx）

> 验收 = 运行 `01_实现基于Flask的Web服务.py` 后逐项核对。

| 编号 | 验收项 | 验证方式 | 通过标准 |
|------|--------|---------|---------|
| V-01 | 依赖可导入 | `python -c "import flask, dashscope, requests"` | 无 `ImportError` |
| V-02 | 脚本可运行 | `python 01_实现基于Flask的Web服务.py` | 无语法错误，打印 self-test 标题 |
| V-03 | 服务可启动 | self-test 的"等待 Flask 服务器就绪" | 10s 内就绪 |
| V-04 | 健康检查 | Test 1 | `status=ok`, `version=1.0.0` |
| V-05 | Agent Card | Test 2 | `name=flask-chat-agent`, `skills=2` |
| V-06 | 问答端到端 | Test 3（`model=qwen`） | `answer` 非空，`elapsed_ms` 为正 |
| V-07 | 参数校验 | Test 4（空 question） | HTTP 400 + JSON 错误体 |
| V-08 | 退出码正确 | `echo $?` | 全通过 → 0 |
| V-09 | 统一错误格式 | `curl -X GET localhost:5000/ask` | 405 + JSON `{"error":{"code":405,...}}` |
| V-10 | 404 统一格式 | `curl localhost:5000/nonexistent` | 404 + JSON 错误体 |
| V-11 | 非法 JSON 处理 | `curl -X POST /ask -d 'not-json'` | 400 + `Invalid JSON` |
| V-12 | model 枚举校验 | `{"question":"hi","model":"gpt"}` | 400 + `Unsupported model: gpt` |
| V-13 | model 回显真实名称 | Test 3 响应 | `model == "qwen-plus"`（非 "qwen"） |
| V-14 | 时间戳格式 | 各响应 `timestamp` | 匹配 `%Y-%m-%dT%H:%M:%SZ` |
| V-15 | 双后端可扩展性 | 读代码确认 | 加第三个模型只需 1 函数 + 1 elif + 1 skill |

---

## 8. 已知缺口（Gap Analysis，G-xx）

> **本节是 spec 的核心价值** —— 忠实记录代码与理想状态之间的差距。**均基于源码事实，未臆造。**

### 8.1 教材原版问题（源码 1-47 行注释实录）

| 编号 | 教材问题 | 严重级 | 本章处理 |
|------|---------|-------|---------|
| G-01 | DashScope v1 端点已下线（`api/v1/services/aigc/text-generation/generation`） | 🔴 致命 | ✅ 已改 `dashscope.Generation.call` |
| G-02 | API Key 命名混乱（`QWEN_API_KEY`） | 🟡 中 | ✅ 已统一 `DASHSCOPE_API_KEY` |
| G-03 | 错误处理粗糙（只判 `status_code == 200`） | 🔴 高 | ✅ 已改三层 try/except |
| G-04 | 无 A2A Agent Card 端点（与 char10 脱节） | 🟡 中 | ✅ 已加 `/well-known/agent.json` |
| G-05 | 无健康检查（生产不可接受） | 🟡 中 | ✅ 已加 `/health` |
| G-06 | 无 main self-test（无法自动回归） | 🟢 低 | ✅ 已加 4 项 self-test |

### 8.2 本章改写后**仍然存在**的缺口

| 编号 | 缺口 | 位置 | 严重级 | 影响 | 建议 |
|------|------|------|-------|------|------|
| G-07 | **A2A 规范路径不匹配** —— 注释写 `/.well-known/agent.json`，实际注册 `/well-known/agent.json`（**无点**） | 161 行 | 🔴 高 | A2A 客户端按规范路径探测将 404 | 改为 `@app.route("/.well-known/agent.json")` |
| G-08 | **`/a2a` 端点未实现** —— Agent Card 的 `endpoint` 字段指向 `/a2a`，但无对应路由 | 77 行 | 🟡 中 | 声明超前于实现，调用方按 Card 调用会 404 | 实现 `POST /a2a`（接收 JSON-RPC 信封）或修正 Card |
| G-09 | **`call_dashscope()` 无异常分类** —— 裸调 SDK，任何错误统一落 500 | 116-126 | 🟡 中 | 与 `call_deepseek()` 的 502 分级不对称 | 加 `try/except` 区分网络错误与参数错误 |
| G-10 | **无 500 错误处理器** —— 只注册 404/405 | 237-244 | 🟡 中 | 未捕获异常返回 HTML，破坏 JSON 契约 | 加 `@app.errorhandler(500)` |
| G-11 | **`force=True` 使 Content-Type 失效** —— 注释说"Content-Type 校验"，实际强制解析 | 192 行 | 🟡 中 | 无法拒绝非 `application/json` 的请求 | 去掉 `force=True` 或显式校验 header |
| G-12 | **`system_prompt` 无长度限制** | 205 行 | 🟡 中 | 超长输入致 token 爆量 / 成本失控 | 加长度上限校验 |
| G-13 | **无请求限流**（rate limit） | `ask()` 全局 | 🟡 中 | `/ask` 可被无限刷，API 费用失控 | 加 flask-limiter 或网关限流 |
| G-14 | **`/health` 是浅检查** —— 不验证上游可达 | 170-178 | 🟢 低 | 上游挂了仍报 `ok` | 增加可选的上游探测（deep mode） |
| G-15 | **Test 3 真实调用不稳定的 CI 友好性** | 300-311 | 🟢 低 | 消耗 token、依赖网络 | 加 `--mock` 开关或跳过标记 |
| G-16 | **无 deepseek 分支测试** | self-test | 🟢 低 | 双后端只验证了一个 | Key 存在时补 Test 5 |
| G-17 | **`elapsed_ms` 覆盖范围窄** —— 只含 LLM 调用 | 213 行 | 🟢 低 | 忽略参数校验/序列化开销（通常可忽略） | 若要端到端指标，t0 移到函数入口 |
| G-18 | **`host="0.0.0.0"` 开发机暴露** | 335 行 | 🟢 低 | 局域网可访问，存在风险 | 开发用 `127.0.0.1` |
| G-19 | **无 CORS 支持** | 全局 | 🟢 低 | 浏览器端跨域调用受限 | `pip install flask-cors` |
| G-20 | **`AGENT_CARD["endpoint"]` 硬编码 localhost** | 77 行 | 🟢 低 | 生产部署需手动改 | 从环境变量注入 base URL |
| G-21 | **改用例的双后端 temperature 不一致** —— qwen=0.3，deepseek 未传 | 122 / 141-148 | 🟢 低 | 语义不一致，难以对比 | deepseek 显式传 `temperature=0.3` |

### 8.3 缺口分布统计

| 严重级 | 数量 | 编号 |
|--------|------|------|
| 🔴 致命/高 | 1 | G-07 |
| 🟡 中 | 6 | G-08, G-09, G-10, G-11, G-12, G-13 |
| 🟢 低 | 8 | G-14 ~ G-21 |
| ✅ 已修复（教材问题） | 6 | G-01 ~ G-06 |
| **合计** | **21** | — |

---

## 附录 A：端点速查表

| 方法 | 路径 | 用途 | 认证 | 返回 |
|------|------|------|------|------|
| GET | `/well-known/agent.json` | A2A Agent Card 发现 | 无 | `AGENT_CARD` |
| GET | `/health` | 健康检查 | 无 | `{status, timestamp, version, models}` |
| POST | `/ask` | 问答（核心业务） | 无 | `{answer, model, elapsed_ms, timestamp}` |
| ANY | `*`（不存在） | 404 handler | — | `{"error":{"code":404,...}}` |
| 错误方法 | 已注册路径 | 405 handler | — | `{"error":{"code":405,...}}` |

---

## 附录 B：环境变量

| 变量 | 必需 | 用途 | 缺失行为 |
|------|------|------|---------|
| `DASHSCOPE_API_KEY` | ✅ | DashScope SDK 认证 | 调用 `call_dashscope()` 时失败（`dashscope.api_key=None`） |
| `DEEPSEEK_API_KEY` | ❌ | DeepSeek Bearer 认证 | `call_deepseek()` 抛 `ValueError` → HTTP 400 |

---

## 附录 C：依赖版本

| 依赖 | 版本 | 来源 | 用途 |
|------|------|------|------|
| Flask | 3.1.3 | pip | HTTP 路由 + 请求处理 |
| dashscope | 最新稳定版（本地 1.22.1） | pip | qwen-plus SDK |
| requests | 最新版 | pip | DeepSeek 直调 + self-test 客户端 |
| threading | stdlib | Python 内置 | 后台启动 Flask |
| os / sys / time | stdlib | Python 内置 | 环境变量 / 退出码 / 计时 |

**解释器**：`D:/MyCode/Python/Python313/python.exe`（3.13.15）

---

## 附录 D：实测记录（源自 `arch_汇总说明.md`）

```
Test 1  GET  /health                     → status=ok, version=1.0.0
Test 2  GET  /well-known/agent.json       → name=flask-chat-agent, skills=2
Test 3  POST /ask (model=qwen, 真实 API)  → answer=2, elapsed=801ms   ✅
Test 4  POST /ask 空 question 参数校验    → 400 question field is required
```

**改写前后对照（节选自 arch 文档第六节）**

| 维度 | 教材原版 | 改写后（生产级） |
|------|---------|----------------|
| DashScope 端点 | 过时 v1 URL（已下线） | SDK `Generation.call` |
| API Key 命名 | `QWEN_API_KEY`（混乱） | `DASHSCOPE_API_KEY`（统一） |
| Agent Card | 无 | `GET /.well-known/agent.json` |
| 健康检查 | 无 | `GET /health` |
| 错误处理 | `status_code == 200` | 三层 try/except + 6 种状态码 |
| 错误格式 | 裸字符串 | `{"error": {"code", "message"}}` |
| main 入口 | `app.run()` 阻塞 | 后台线程 → self-test → 自动退出 |
| 响应元信息 | `{"answer": ...}` | + `model` + `elapsed_ms` + `timestamp` |
| 404/405 | Flask 默认 HTML | 统一 JSON |

---

## 附录 E：生产化扩展路线（源自 arch 文档第八节）

| # | 扩展项 | 技术选型 | 解决缺口 |
|---|--------|---------|---------|
| 1 | 浏览器跨域调用 | `flask-cors` | G-19 |
| 2 | 替换开发服务器 | `waitress`（Windows）/ `gunicorn`（Linux） | 常驻部署 |
| 3 | LLM 调用下沉异步队列 | Celery / RQ | G-13（限流/排队） |
| 4 | 接收完整 JSON-RPC 信封 | 新增 `POST /a2a` | G-08 |
| 5 | 一键部署 | Dockerfile + docker-compose.yml | — |

---

## 附录 F：与 char10 的衔接清单

| char10 概念 | char11 落点 | 状态 |
|------------|------------|------|
| Agent Card | `AGENT_CARD` + `GET /well-known/agent.json` | ✅ 已落地（路径待修正，见 G-07） |
| `message/send` | `POST /ask` | ✅ 已落地（语义等价，非 JSON-RPC） |
| `verify_auth()` | 无（Card 声明 `bearer` 但未校验） | ⚠️ 未落地 |
| JSON-RPC 信封 | 无 | ⚠️ 列为扩展方向 ④ |
| Task 状态机（7 态） | 无（同步问答，无任务生命周期） | ⚠️ 未落地 |
| Artifact | 无（直接返回 `answer` 字符串） | ⚠️ 未落地 |

> **结论**：char11 完成了 A2A 的**入口层**（发现 + 问答）HTTP 化，但**任务生命周期**（Task/Artifact/JSON-RPC）留给了后续扩展。这是"先跑通主链路，再补协议完整性"的务实路径。

---

*Spec 版本：v1.0 · 生成日期：2026-10-12 · 依据源码：`01_实现基于Flask的Web服务.py`（350 行，逐行核对）*
