# 《AI Agent 开发：零基础构建复合智能体》× 阿里云百炼 改造执行指南

> 目标：把书里的示例代码从「OpenAI / 通用写法」改成**能在阿里云百炼上直接跑通**的版本。
> 核心结论：**80% 的代码不用改**，因为百炼提供 OpenAI 兼容协议。真正要动的只有四样东西：`base_url`、`api_key`、`model` 名、以及几个平台特有的参数（embedding 批量上限、rerank 接口路径）。
>
> 📌 本文所有接口地址、模型名、SDK 包名均于 **2026-10-10** 核对官方文档得出；带 `⚑ 需核实` 标记的项会随平台迭代变动，动手前请再点一次官方文档。

---

## 一、5 分钟跑通第一个调用

### 1. 环境准备

```bash
# 1) 装依赖（建议先建虚拟环境）
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -U openai python-dotenv requests
```

### 2. 拿 API Key

1. 登录百炼控制台：<https://bailian.console.aliyun.com/>
2. 右上角 ⚙️ → API-KEY → 创建，复制 `sk-` 开头的密钥（**只显示一次**）
3. 记下你的**业务空间 ID（WorkspaceId）**，后面 RAG / 知识库要用

### 3. 配置密钥（不要写进代码）

在项目根目录建 `.env`：

```ini
# .env —— 必须加进 .gitignore，永远不要提交
DASHSCOPE_API_KEY=sk-你的密钥
BAILIAN_WORKSPACE_ID=llm-你的业务空间ID
BAILIAN_APP_ID=你的应用ID          # 用百炼应用/知识库时才需要
BAILIAN_REGION=cn-beijing          # 北京；新加坡/弗吉尼亚等地域端点不同
```

同时在 `.gitignore` 里加一行 `.env`。

### 4. 第一个可执行脚本

`chapter01/01_hello_bailian.py`：

```python
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    # 北京地域的 OpenAI 兼容端点（新加坡/弗吉尼亚等地域不同，见第五节踩坑 5）
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)

resp = client.chat.completions.create(
    model="qwen3.7-plus",          # ⚑ 需核实：以控制台「选择模型」页当前可选名为准
    messages=[
        {"role": "system", "content": "你是一个简洁的助手。"},
        {"role": "user", "content": "用一句话解释什么是 AI Agent。"},
    ],
)
print(resp.choices[0].message.content)
```

```bash
python chapter01/01_hello_bailian.py
```

能打印出回答，说明底座通了 —— 后面所有章节的改造都建立在这三行配置上。

---

## 二、三种接入方式：先选对路，再动手改代码

百炼同时提供三套接口，书里不同章节要用不同的那套，**选错会白折腾**：

| 接入方式 | 端点 | LangChain 接入类 | 支持范围 | 书里对应章节 |
|---|---|---|---|---|
| **① OpenAI 兼容模式**（首选，改动最小） | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `ChatOpenAI` / `OpenAIEmbeddings` | Qwen 全系 + 部分三方模型；**不支持 Qwen-Audio** | 第 4、5、6、7、9 章 |
| **② DashScope 原生协议** | SDK 内置（`/api/v1`） | `ChatTongyi`（社区包） | 全部文本生成模型 + **部署后的自定义模型** | 第 3 章模型部署、rerank、多模态 |
| **③ 百炼应用 API** | `POST /api/v1/apps/{APP_ID}/completion` | 无需框架，直接 HTTP | 平台托管的智能体/工作流（自带知识库、MCP、记忆） | 第 9、10、12 章 |

> ⚠️ **重要提醒**：搜索到的官方资料明确指出，`langchain-community` 与 `dashscope` 这两个包**已停止维护**。新写代码优先走 ① 的 `ChatOpenAI`；只有在需要原生协议能力（如部署模型、rerank、多模态）时才用 ②。书里若用 `from langchain_community.chat_models.tongyi import ChatTongyi`，能跑但属于技术债，建议顺手替换。

### 模型名映射表（书里 → 百炼）

| 书里/示例中的模型 | 百炼对应 | 说明 |
|---|---|---|
| `gpt-4o` / `gpt-4-turbo` | `qwen3.7-max` 或 `qwen3.8-max` | 旗舰，复杂推理/长文 |
| `gpt-4o-mini` | `qwen3.7-plus` | 性价比主力，日常任务首选 |
| `gpt-3.5-turbo` | `qwen3.7-flash` / `qwen3.5-flash` | 高频轻量、意图识别、分类 |
| `text-embedding-ada-002` | `text-embedding-v4` | 向量化，默认输出 **1024 维** |
| `gpt-4-vision`（多模态） | `qwen-vl-max` / `qwen-vl-plus` | 走兼容模式或多模态专用接口 |
| （rerank） | `qwen3-rerank` / `qwen3.7-text-rerank` | 文本重排；多模态用 `qwen3-vl-rerank` |

> ⚑ 需核实：上表右侧是**基于当前模型代际的对应建议**，不是官方一对一映射。请按你的预算与延迟要求在控制台「模型广场」确认可用型号。百炼还提供三方直供模型（如 `deepseek-v4-pro`、`glm-5.2`、`kimi-k3`、`MiniMax-M3`），**需先在控制台开通**才能调用。

---

## 三、逐章改造清单

| 章 | 书里讲什么 | 百炼上怎么改 | 工作量 |
|---|---|---|---|
| 1 | 大模型基础、Transformer、提示词 | 代码仅第 1.4 节 API 调用形态，按第一节替换三件套即可 | 🟢 小 |
| 2 | 四大模块（感知/决策/行动/记忆） | 纯架构章节，无代码改动；模块可对照我们 `arch/` 下的架构图 | ⚪ 无 |
| 3 | 模型部署、微调、多模型路由 | 用百炼「模型部署/微调」产出自定义模型，**走原生协议**调用（兼容模式不支持部署模型）；多模型路由改用百炼模型名数组自实现降级 | 🟡 中 |
| 4 | LangChain、Chain、Tools、Memory | `ChatOpenAI(base_url=兼容端点)` 替换原 LLM 初始化；Tool / Memory 组件不用动 | 🟢 小 |
| 5 | **LangGraph** 状态机、ReAct 循环 | LangGraph 与模型供应商解耦，换 LLM 即可；`create_react_agent` 位置随版本变动，见 4.3 | 🟢 小 |
| 6 | 上下文工程、子智能体、记忆提取 | 记忆逻辑自研保留；Embedding 换 `text-embedding-v4`；也可直接用百炼**长期记忆**能力（见 4.6） | 🟡 中 |
| 7 | 记忆去重、衰减、重整合 | 纯算法章节，只把向量化/相似度换百炼 embedding + rerank | 🟡 中 |
| 8 | 心跳机制、定时任务 | 与模型无关；调用处换成第一节的 client 即可（定时器可用 APScheduler / 系统计划任务） | 🟢 小 |
| 9 | **RAG** 知识库自建 | 两条路：**自建**（embedding+向量库+rerank，见 4.4）或**托管**（百炼知识库+应用 API，见 4.5） | 🟠 大 |
| 10 | **MCP** 协议 | 百炼有 MCP 服务广场（官方托管 20+ 云端服务、50+ 本地服务，智能体最多挂 5 个）；也可自建注册。见 4.7 | 🟡 中 |
| 11 | **A2A** 多智能体 | 百炼「智能体应用 + Agent 2.0」模式原生强化 ReAct 与 Function Call，适合多 Agent 协同 ⚑ 需核实；纯代码侧可沿用 LangGraph 多节点/子图实现 | 🟠 大 |
| 12 | 扣子低代码 | 对应百炼**应用中心**（智能体应用 / 工作流），控制台 30 分钟零代码出原型 | 🟢 小 |
| 13 | 项目实战、评估、部署运维 | 评估 harness 自研保留；监控接百炼用量看板 + 你的日志体系；上线用应用 API 或自建服务 | 🟡 中 |

---

## 四、核心代码改造模板（可直接抄）

### 4.1 基础调用：官方 SDK（最稳）

```python
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)

# 流式 + 末尾带 token 用量（做成本统计很有用）
stream = client.chat.completions.create(
    model="qwen3.7-plus",
    messages=[{"role": "user", "content": "讲个冷笑话"}],
    stream=True,
    stream_options={"include_usage": True},
)
for chunk in stream:
    if chunk.choices and chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

### 4.2 LangChain（对应第 4 章）

```python
import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

llm = ChatOpenAI(
    model="qwen3.7-plus",
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    temperature=0.7,
)

# == 原 OpenAI 写法，只改了上面 3 行 ==
# llm = ChatOpenAI(model="gpt-4o", api_key=os.getenv("OPENAI_API_KEY"))
```

**改动只有三处**：`model` 名、`api_key` 来源、`base_url`。Chain / Prompt / Tool 全部原样保留。

### 4.3 LangGraph ReAct Agent（对应第 5 章）

```python
import os
from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent   # ⚑ 需核实：新版 langchain 1.x 已迁到 langchain.agents

load_dotenv()

@tool
def get_weather(city: str) -> str:
    """查询指定城市的天气，city 为城市名。"""
    return f"{city} 今天晴，25℃"

llm = ChatOpenAI(
    model="qwen3.7-plus",
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)
agent = create_react_agent(llm, [get_weather])

result = agent.invoke({"messages": [("user", "北京今天天气怎么样？")]})
print(result["messages"][-1].content)
```

> ⚑ `create_react_agent` 的函数位置与签名在 LangGraph / LangChain 大版本间变动过，报 `ImportError` 时先查你本地装的版本（`pip show langgraph langchain`），再对照官方文档调整 import 路径，别硬猜。

### 4.4 RAG 自建链路（对应第 9 章）—— 三个必踩的坑都在这里

```python
import os, requests
from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter

load_dotenv()
BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
KEY = os.getenv("DASHSCOPE_API_KEY")

# ① 向量化 —— 这两个参数不设，稍大的知识库必然报错
embeddings = OpenAIEmbeddings(
    model="text-embedding-v4",
    api_key=KEY,
    base_url=BASE,
    check_embedding_ctx_length=False,  # 百炼不接受 OpenAI 的 token 预切分逻辑
    chunk_size=10,                     # 百炼 embedding 单次请求最多 10 条文本，必设！
)

# ② 建库（书里的切片逻辑保留即可）
texts = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50).split_text(
    open("docs/handbook.md", encoding="utf-8").read()
)
store = Chroma(collection_name="kb", embedding_function=embeddings, persist_directory="./chroma_db")
store.add_texts(texts)

# ③ 召回 + 重排（rerank 是第 9 章"优化"那节的关键，能明显抑制幻觉）
docs = store.similarity_search("如何预防感冒？", k=20)

resp = requests.post(
    "https://dashscope.aliyuncs.com/compatible-api/v1/reranks",   # qwen3-rerank 专用路径
    headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
    json={
        "model": "qwen3-rerank",
        "query": "如何预防感冒？",
        "documents": [d.page_content for d in docs],
        "top_n": 5,
        "instruct": "Given a web search query, retrieve relevant passages that answer the query.",
    },
    timeout=30,
)
top_docs = [docs[i["index"]].page_content for i in resp.json()["results"]]
context = "\n\n".join(top_docs)
```

**rerank 的接口分家，别搞混**：

| 模型 | 端点 | 请求体 |
|---|---|---|
| `qwen3-rerank` | `/compatible-api/v1/reranks` | `model` / `query` / `documents` / `top_n` **平级**，无 `input` 包裹 |
| `qwen3.7-text-rerank`、`qwen3-vl-rerank` | `/api/v1/services/rerank/text-rerank/text-rerank` | 需要 `input: {query, documents}` + `parameters` |
| `gte-rerank-v2` | 同上 | ⚠️ **`gte-rerank` 已于 2026-05-30 下线**，别再照抄老教程，统一换 `qwen3-rerank` |

### 4.5 百炼托管知识库 + 应用调用（第 9/12 章的「省事路线」）

如果不想自己维护向量库和切片，直接把文档交给百炼：

- **控制台路线**：应用中心 → 数据管理 → 知识索引 → 创建知识库 → 上传 PDF/Word/Excel/TXT/Markdown，平台自动解析切片入库。
- **代码路线**：用阿里云百炼 SDK（包名 `alibabacloud_bailian20231229`）走 `AddFile → ApplyFileUploadLease → CreateIndex → SubmitIndexJob`。
  ⚠️ **`CreateIndex` 只是初始化作业，必须再调 `SubmitIndexJob`，否则你会得到一个空知识库**（这是最容易卡住的一步）。
- **调用应用**：

```python
import os, requests
from dotenv import load_dotenv

load_dotenv()
APP_ID = os.getenv("BAILIAN_APP_ID")
KEY = os.getenv("DASHSCOPE_API_KEY")

resp = requests.post(
    f"https://dashscope.aliyuncs.com/api/v1/apps/{APP_ID}/completion",
    headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
    json={"input": {"prompt": "查询公司报销流程"}, "parameters": {}},
    timeout=60,
)
print(resp.json()["output"]["text"])

# 多轮对话：回传上一轮的 session_id（1 小时无请求自动失效）
# body: {"input": {"prompt": "...", "session_id": "上次返回的 session_id"}}
# 流式输出：请求头加 X-DashScope-SSE: enable，parameters 里加 "incremental_output": true
```

> 记住：**应用必须先「发布」**，外部接口才能调到它。

### 4.6 记忆模块（对应第 6/7 章）

三条可选路线，按你的控制欲递减：

1. **全自研**（书里写法）：记忆算法保留，只把「向量化 + 相似度」换成 4.4 的 `text-embedding-v4` + 向量库。
2. **半托管**：用百炼 embedding + 你自己的 DB，记忆的衰减/重整合逻辑继续自己写（第 7 章的价值就在这层算法上，别丢）。
3. **全托管**：百炼长期记忆能力（CLI 侧为 `bl memory add / search / list`，支持按 `user_id` 隔离、用户画像 Schema）。

> 建议：第 7 章的记忆去重/冲突/衰减是**书的精华**，直接用平台托管会把这部分学习价值绕过去，学习阶段推荐路线 1。

### 4.7 MCP 接入（对应第 10 章）

三种姿势，从易到难：

1. **控制台零代码**：MCP 服务广场 → 开通（如高德地图、天气、网页解析、Sequential Thinking）→ 在智能体应用里「添加 MCP 服务」。注意：**单个智能体最多同时挂 5 个 MCP 服务**。
2. **Responses API 编程调用**：用 OpenAI 兼容客户端，把 MCP 作为一个 `type: "mcp"` 的工具传入（示例形态参考阿里云开发者社区文章，字段以官方 Responses API 文档为准 ⚑ 需核实）。
3. **自建注册**：把自己的 API 或社区开源 MCP Server 用 `npx` / Python 脚本命令注册到百炼，平台自动托管到函数计算，无需自己买机器。

> 补充：百炼 CLI 提供 `bl mcp list / tools / call / connect`，可以把百炼 MCP 服务直接注册进 Claude Code、Cursor、Qoder 等 Agent 原生配置里，调试很方便。**MCP 能力目前仅对中国站（aliyun.com）账号开放。**

---

## 五、踩坑清单（必读，能省你半天）

| # | 坑 | 现象 | 解法 |
|---|---|---|---|
| 1 | embedding 批量超限 | 知识库稍大就 `400` 报错 | `OpenAIEmbeddings(chunk_size=10)` —— 百炼 embedding 单次最多 10 条，默认 1000 必炸 |
| 2 | 兼容模式的 token 预切分 | 长文本 embedding 报错 | 加 `check_embedding_ctx_length=False` |
| 3 | `gte-rerank` 照抄老教程 | 404 / 下线报错 | 换 `qwen3-rerank`，并注意接口路径分家（4.4 表） |
| 4 | 维度对不上 | 检索结果全乱 | LangChain 下 `text-embedding-v3/v4` **无法指定维度**，固定 1024 维；换模型要重建库 |
| 5 | 地域端点不一致 | `401` / 连接失败 | 北京、新加坡、弗吉尼亚端点与 **API Key 都不通用**；北京是 `dashscope.aliyuncs.com`，新加坡是 `dashscope-intl`系 |
| 6 | 音频模型走错协议 | `Qwen-Audio` 调不通 | 它**不支持 OpenAI 兼容协议**，只能用 DashScope 原生协议 |
| 7 | 知识库建了个空库 | 检索永远没结果 | 建索引必须 `CreateIndex` + **`SubmitIndexJob`** 两步 |
| 8 | 应用调不通 | `app not found` | 应用发布后才能外部调用；`APP_ID` 和 `API_KEY` 不能混用别的地域 |
| 9 | 部署/微调模型调不通 | 兼容模式报模型不存在 | 部署模型只走 DashScope 原生协议 |
| 10 | 密钥泄露 | 账单异常 | `.env` + `.gitignore`；控制台配用量告警阈值 |

---

## 六、待核实 / 版本敏感项（别当圣经用）

- ⚑ **具体模型名**：`qwen3.7-plus`、`qwen3.8-max` 等代际迭代很快，动手前请打开控制台「选择模型」页确认当前可用名与上下文长度。
- ⚑ **`create_react_agent` 的 import 路径**：LangGraph 与 LangChain 大版本间迁移过，以本地 `pip show` 版本为准。
- ⚑ **Responses API 的 MCP 工具字段**：社区文章示例可能滞后于官方文档。
- ⚑ **Agent 2.0 的底层框架说明与多智能体能力边界**：来源为开发者社区文章，请以官方产品文档为准。
- ⚑ **价格**：本文刻意不写单价，百炼计费页与 Token 套餐变动频繁，成本测算请查官方价格页。

---

## 七、建议的改造顺序

```
第一步（半天）  第 1 章 hello world 跑通 → 确认 API Key / base_url / 模型名三件套正确
第二步（1 天）  第 4 章 LangChain → 只替换 LLM 初始化，验证 Chain / Tool 正常
第三步（1 天）  第 5 章 LangGraph ReAct → 把 4.3 模板跑通，理解循环推理
第四步（2 天）  第 9 章 RAG → 先自建链路（4.4）踩完坑，再对比托管路线（4.5）
第五步（按需）  第 10 / 11 / 12 章 → 平台侧能力为主，代码量反而小
```

**优先级建议**：先把 ① 兼容模式这条路走通（它覆盖第 4、5、6、7、9 章），再单独处理需要原生协议的部分（rerank、多模态、部署模型）。不要一上来就碰第 11 章 A2A，多智能体调试成本最高，等单 Agent 稳定后再上。

---

## 附：推荐目录结构

```
aiAgentCode/
├── .env                      # 密钥（勿提交）
├── .env.example              # 模板，可提交
├── .gitignore                # 含 .env / .venv / chroma_db
├── requirements.txt
├── arch/                     # 架构图（已生成）
├── chapter01/                # 01_hello_bailian.py 等
├── chapter04_langchain/
├── chapter05_langgraph/
├── chapter09_rag/
│   └── docs/                 # 待入库的原始文档
└── chapter10_mcp/
```

`requirements.txt`（不锁死小版本，按需 `pip install -U`）：

```
openai
python-dotenv
requests
langchain
langchain-openai
langchain-community
langchain-text-splitters
langchain-chroma
langgraph
chromadb
# 需要 rerank / 多模态 / 原生协议时再装：
# dashscope
# 需要代码方式管理百炼知识库时再装：
# alibabacloud_bailian20231229
```
