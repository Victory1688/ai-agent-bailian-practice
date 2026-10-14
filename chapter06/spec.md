# 第 6 章 规范说明书（spec.md）——RAG 机制：检索增强智能体

> **SDD 定位**：本文回答 *「如何让大模型基于外部知识库回答，而不是凭空编」*。
> **上篇（意图与学习路径）**回答 *为什么学、学什么、怎么学*；
> **下篇（契约与验收）**回答 *每个文件到底承诺了什么、怎么验证、还缺什么*。
> **主线**：RAG = **R**etrieval（检索）+ **A**ugmented（增强）+ **G**eneration（生成）。
> 本章 9 个例子把这条链路**拆件演示**：向量化 → 切片 → 清洗 → 嵌入选型 → 多库存储 → 检索 → 拼 prompt → 生成 → 混合检索。
> 前 6 篇是零件，第 7/8 篇把零件串成完整闭环，第 9 篇扩展到「文本 + 结构化数据」双通道。
>
> 适用范围：`D:/AiWorkOut/aiAgentCode/chapter06/`（9 个 .py / 1189 行）。
> 契约字段一律**从代码事实反推**，不臆造；教材简化点与改写依据一并留痕。

---

# 上篇：意图与学习路径

## 1. 章意图（Why）

### 1.1 教材原版想解决什么

教材用一章讲 RAG，把这条链路的每一环都拆开示范：

| 教材概念 | 想说明什么 |
|---|---|
| 存入 FAISS | 文本 → 向量 → 相似度检索的最小闭环 |
| 文档切片 | chunk_size / chunk_overlap 如何影响检索质量 |
| 语义找回 Agent | 向量化 → 建索引 → 相似度检索 三步 |
| 文本清洗与句元切分 | 数据质量是检索准确率的第一道防线 |
| Embedding 模型选择 | 把非结构化文本映射为语义保持的稠密向量 |
| 三种向量数据库 | FAISS 内存 / Chroma 嵌入式 / Weaviate 服务端的部署差异 |
| RetrievalQA | 检索 + 生成 的完整闭环 |
| 多段检索与 Top-K 融合 | 放宽召回条数，用多段上下文提信息密度 |
| 文本与结构化数据混合检索 | 双通道（语义 + 数值）解决异构数据召回 |

### 1.2 教材原版的三大断点

本章 **9 个例子全部无法直接运行**，卡在三处：

| 断点 | 涉及例子 | 具体表现 |
|---|---|---|
| 🔴 **`langchain` 0.x import 路径全部失效** | 01/02/03 | `from langchain.embeddings import ...` / `from langchain.vectorstores import ...` / `from langchain.text_splitter import ...` —— 1.x 已把这些拆到 `langchain_community` / `langchain_text_splitters` / `langchain_core`，旧路径 `ImportError` |
| 🔴 **虚构框架 `qwen_agent` + 过时嵌入端点** | 05/06/07/08/09 | `from qwen_agent.agent import Agent`（虚构）；`get_qwen_embedding()` 用原生 `requests` 调百炼嵌入端点，**2025 年端点格式已变**（实测 `BadRequest.IllegalInput`，"The input parameter requires json format"） |
| 🟠 **依赖缺失/环境要求** | 03/06/04 | 03 需 `sentence-transformers` + HuggingFace 下载；06 的 Weaviate 需本地 Docker；04 需 `ace_tools`（Colab 专属） |

另外两个**模型选型问题**：
- 03 篇用的 `all-MiniLM-L6-v2` 是**英文**向量模型（384 维）——检索中文知识库排序会明显失真。
- 01 篇的 `OpenAIEmbeddings` 默认直连 OpenAI，国内无法访问。

### 1.3 本章改写要解决什么

| 教材原实现 | 改写后 | 教学点 |
|---|---|---|
| `langchain.embeddings.OpenAIEmbeddings` | `langchain_community.embeddings.DashScopeEmbeddings(model="text-embedding-v3")` | 中文强、零下载、与对话共用一把 key |
| `langchain.vectorstores.FAISS` | `langchain_community.vectorstores.FAISS`（**仅换路径**） | 行为完全一致 |
| `langchain.schema.Document` | `langchain_core.documents.Document`（**仅换路径**） | 行为完全一致 |
| `langchain.text_splitter.RecursiveCharacterTextSplitter` | `langchain_text_splitters.RecursiveCharacterTextSplitter` | 类名/参数/行为完全一致 |
| `HuggingFaceEmbeddings(all-MiniLM-L6-v2)` | `DashScopeEmbeddings(text-embedding-v3)` | 语言匹配 + 免下载 |
| `requests.post(EMBEDDING_API)` 原生调用 | `DashScopeEmbeddings.embed_documents()` | 接口稳定（旧端点已变） |
| `qwen_agent.Agent/Tool/Message` | 手写 `agent_chat` 循环（dashscope function calling） | 拆开显示，不再黑盒 |
| `ace_tools.display_dataframe_to_user` | 原生 `print` | 去掉 Colab 专属依赖 |
| Weaviate（需 Docker） | **注释保留** + FAISS/Chroma 实跑 | 诚实说明「未跑通的原因」 |

### 1.4 本章最该带走的三句话

1. **RAG 的本质是「先检索、再拼 prompt、再生成」三步**——function calling 只是把这三步交给模型自主决策，底层没有任何魔法（第 7 篇把这个「显式版」原样保留，正是为了对照）。
2. **切片策略决定检索上限**——切太碎丢上下文，切太大稀释语义。`chunk_size` / `chunk_overlap` / 分隔符列表三个旋钮，中文场景尤其要注意**默认分隔符里没有中文标点**。
3. **嵌入模型必须与语言匹配**——英文模型（`all-MiniLM-L6-v2`）检索中文会失真；中文场景用 `text-embedding-v3`（1024 维）。

---

## 2. 学习路径（9 文件 / 1189 行）

按「最小闭环 → 预处理 → 选型 → 存储 → 完整闭环 → 融合 → 混合」的顺序阅读：

| # | 文件 | 行数 | 核心机制 | 读完后你应能说出 |
|---|---|---|---|---|
| 01 | `01_将中文文本转换为向量存入faiss.py` | 68 | `FAISS.from_documents` + `similarity_search` | RAG 最小闭环（向量化 → 建索引 → 检索） |
| 02 | `02_基于LangChain的文档切片实现.py` | 53 | `RecursiveCharacterTextSplitter(chunk_size=100, overlap=20)` | 切片三旋钮与默认分隔符的中文陷阱 |
| 03 | `03_使用LangChain开发带语义找回功能Agent.py` | 68 | 同 01 + **`k=2` 控制召回** | 「语义找回」的真身是语义检索（无 Agent） |
| 04 | `04_文本清洗与句元切分.py` | 97 | 正则白名单清洗 + 按标点断句 + 贪婪拼接 | 数据质量如何影响下游嵌入/召回 |
| 05 | `05_选择Qwen-Embedding模型做语义编码.py` | 166 | **原生 `faiss` + `numpy`** 手动建索引 + 抓真实新闻 + Agent 循环 | 封装底下到底在做什么 |
| 06 | `06_用三种向量数据库做语义检索.py` | 212 | FAISS（内存）/ Chroma（嵌入式）/ Weaviate（服务端）三库对照 | 三种部署形态的差异与接口差异 |
| 07 | `07_实现一个RetrievalQA问答系统.py` | 183 | **显式 RAG 三步**：检索 → 拼 prompt → 生成 | RAG 最原始、最显式的形态 |
| 08 | `08_多段检索与Top-K融合的Agent.py` | 149 | 同 07 + `top_k=5` 多段拼接成融合上下文 | Top-K 融合为什么比 Top-1 好 |
| 09 | `09_文本与结构化数据混合检索Qwen和DeepSeek.py` | 193 | **双通道**：文本语义检索 + pandas 结构化查询 → 融合 | 异构数据怎么统一召回 |

### 阅读路线建议

- **第一遍（最小闭环 3 篇）**：01 → 02 → 03。把「向量化 → 切片 → 检索」跑通。
- **第二遍（预处理与选型 2 篇）**：04 → 05。04 讲「怎么把脏文本洗干净」，05 讲「嵌入模型怎么选、底层怎么建索引」。
- **第三遍（存储 1 篇）**：06。三种向量库的横向对比。
- **第四遍（完整闭环 2 篇）**：07 → 08。**这是本章的核心**——显式 RAG 的完整形态。
- **第五遍（扩展 1 篇）**：09。从「单一文本检索」扩展到「混合检索」。
- **关键呼应**：07 与 08 几乎同构（差异只在 `top_k` 与是否显式命名「融合」）；01 与 03 几乎同构（差异只在 `k` 参数）。**这说明：RAG 的骨架极简，复杂度都在「预处理」与「召回策略」上。**

---

## 3. 五条工程主线（本章反复出现的设计决策）

### 主线一：RAG 三步骨架（全章统一）

```
① 向量化  texts ──embedding_model──→ [vec1, vec2, ...]
② 建索引  vectors ──FAISS / Chroma / faiss.IndexFlatL2──→ index
③ 检索    query ──向量化──→ 相似度搜索 ──→ top-k 文档
④ 增强    检索结果 ──拼进 prompt──→ 带上下文的 prompt     ← 第 7/8/9 篇才有
⑤ 生成    prompt ──LLM──→ 基于上下文的回答                ← 第 7/8/9 篇才有
```

前 6 篇只到 ③，第 7 篇补上 ④⑤ 形成闭环。

### 主线二：两种 FAISS 用法（封装 vs 原生）

本章同时展示同一件事的两种写法，这是**刻意的教学对照**：

| | LangChain 封装（01/03/06-FAISS） | 原生 faiss（05/06/07/08/09） |
|---|---|---|
| 建索引 | `FAISS.from_documents(docs, emb)` | `index = faiss.IndexFlatL2(dim); index.add(np.vstack(embs))` |
| 检索 | `db.similarity_search(query, k)` | `D, I = index.search(qvec, k); [docs[i] for i in I[0]]` |
| 元数据 | 自动关联 `Document` | **需自行管理** `docs` 列表与索引位置的对应 |
| 依赖 | `langchain_community` | `faiss` + `numpy` |
| 教学价值 | 「原来封装这么方便」 | 「原来封装底下就这两行」 |

**05 篇的注释点明**：`build_faiss_index` + `search_finance` 就是 `from_documents` + `similarity_search` 的手动复刻——「嵌入模型可插拔、底层存储不变」。

### 主线三：三种切片策略（对应三篇）

| 篇 | 策略 | 实现 | 特点 |
|---|---|---|---|
| 02 | **递归降级**（现成组件） | `RecursiveCharacterTextSplitter` | 按 `["\n\n","\n"," ",""]` 优先级降级，尽量在自然边界切 |
| 04 | **正则断句 + 贪婪拼接** | `split_sentences` + `generate_chunks` | 按 `。！？` 断句，再拼到接近 `max_len` |
| 08 | **硬切** | `text[i:i+max_len]` | 按字符数均匀分段，**会截断句子**，但长度一致 |

**02 篇的关键陷阱**：`RecursiveCharacterTextSplitter` 默认分隔符列表**没有中文标点**（`。！？，`），中文长段落只能在换行处切。**改进姿势**：`separators=["\n\n","\n","。","！","？","，"," ",""]`。

**04 篇的关键陷阱**：`re.split(r"(?<=[。！？])", text)` 在文本末尾是标点时会产生**末尾空串**（实测 5 个句号 → 6 段），生产需 `[s for s in sentences if s]` 过滤。

### 主线四：显式 RAG vs 隐式 RAG（function calling）

| | 显式 RAG（07/08/09） | 隐式 RAG（05/06，function calling） |
|---|---|---|
| 检索时机 | **开发者写死**：先检索再生成 | **模型自主决定**：要不要检索 |
| 代码形态 | `context = tool.call(q)` → `prompt = build(q, ctx)` → `LLM(prompt)` | `tools=[...]` → 模型返回 `tool_calls` → 本地执行 → 回填 |
| 可预测性 | 高（必定检索） | 低（模型可能不检索直接答） |
| 灵活度 | 低（固定流程） | 高（多轮、按需） |
| 教学价值 | **看得见 RAG 的骨架** | 看得见 Agent 的自主性 |

**07 篇的注释明确**：「这是 RAG 最原始、最显式的形态：开发者写死'先检索、再把检索结果塞进 prompt、再调 LLM'。这个设计值得保留作为教学点，让新人看到 function calling 底下到底藏了什么。」

### 主线五：数据获取的网络兜底（05/06/07/08/09 统一）

```python
def fetch_xxx():
    try:
        resp = requests.get(url, timeout=5)
        docs = [...]
        if docs:
            return docs
    except Exception as e:
        print(f"  [网络兜底] ...抓取失败: {e}")
    return [ ...模拟数据... ]   # ← 保证演示可重复
```

**为什么**：这些例子抓的是真实站点（国开证券、国家能源局、统计局、财政部、lawxp），网络/反爬/接口变动都会失败。**兜底数据保证「本机演示可跑」**——这是学习型代码的很重要的设计纪律。

---

## 4. 学习检查清单（读完自测）

- [ ] 能默写 RAG 最小闭环（向量化 → 建索引 → 检索）的代码骨架。
- [ ] 能说出 `chunk_size` 与 `chunk_overlap` 各自的作用。
- [ ] 能说出 `RecursiveCharacterTextSplitter` 默认分隔符的中文陷阱及改进方法。
- [ ] 能解释 `re.split` 断言分割为什么会产生末尾空串。
- [ ] 能说出「英文嵌入模型检索中文」会有什么问题。
- [ ] 能说出 LangChain 封装的 `FAISS.from_documents` 在原生 faiss 里对应哪几行。
- [ ] 能说出 FAISS / Chroma / Weaviate 三者的部署形态差异。
- [ ] 能画出显式 RAG 的三步流程。
- [ ] 能解释 Top-K 融合为什么优于 Top-1。
- [ ] 能说出 09 篇「文本通道 + 数据通道」各自解决什么问题。

---

# 下篇：契约与验收

## 5. 全局技术约束（C-xx）

### C-01 嵌入模型统一 `DashScopeEmbeddings(model="text-embedding-v3")`

**约束**：**不得**使用 `OpenAIEmbeddings`（国内不可达）、**不得**使用 `HuggingFaceEmbeddings`（需下载 + 中文效果弱）。
**统一写法**：
```python
from langchain_community.embeddings import DashScopeEmbeddings
embedding_model = DashScopeEmbeddings(model="text-embedding-v3", dashscope_api_key=api_key)
```
**维度**：1024 维（`text-embedding-v3`）。
**验收**：全章 grep `OpenAIEmbeddings` / `HuggingFaceEmbeddings` 只命中注释。

### C-02 LangChain 1.x 导入路径

| 对象 | 正确路径（1.x） | 教材旧路径（失效） |
|---|---|---|
| `DashScopeEmbeddings` | `langchain_community.embeddings` | —（教材用 `langchain.embeddings`） |
| `FAISS` | `langchain_community.vectorstores` | `langchain.vectorstores` |
| `Document` | `langchain_core.documents` | `langchain.docstore.document` / `langchain.schema` |
| `RecursiveCharacterTextSplitter` | `langchain_text_splitters` | `langchain.text_splitter` |

**约束**：必须使用 1.x 路径。
**验收**：grep `from langchain\.` 应只出现在注释块。

### C-03 API Key 来自环境变量

```python
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key    # 对话用
# 向量化用：dashscope_api_key=api_key（传给 DashScopeEmbeddings）
```
**要点**：**对话与向量化共用同一把 key** —— 这是本章注释反复强调的优点。
**已知风险**：无空值校验（见缺口 G-02）。

### C-04 对话统一 `qwen-plus` + `result_format='message'`

**约束**：05~09 的 `Generation.call` 必须带 `result_format='message'`，模型 `qwen-plus`，`temperature=0.3`。
**`max_tokens`**：Agent 类（05/06）512；生成类（07/08/09）1024。

### C-05 原生 faiss 索引构建固定模式

```python
dim = embeddings[0].shape[0]
index = faiss.IndexFlatL2(dim)
index.add(np.vstack(embeddings))
# 检索
qvec = get_qwen_embedding([query])[0].reshape(1, -1)
D, I = index.search(qvec, k)
hits = [docs[i] for i in I[0]]
```
**约束**：`IndexFlatL2`（暴力精确检索）；`reshape(1,-1)` 保证查询是二维矩阵；`I[0]` 取第一行索引。
**反例**：不做 `reshape` → faiss 报维度错误。

### C-06 `get_qwen_embedding` 签名全章统一

```python
def get_qwen_embedding(texts: List[str]) -> List[np.ndarray]:
    raw = _emb_model.embed_documents(texts)
    return [np.array(v, dtype=np.float32) for v in raw]
```
**约束**：**签名与教材原版一致**（`List[str] → List[np.ndarray]`），使 `build_faiss_index` / 各种 Tool 类**零改动**。
**理由**：「换实现不换签名」是本章的核心重构纪律——教材的 `qwen_agent.Agent` 被替换后，所有下游调用点的签名保持不变。

### C-07 工具类去掉虚构继承，保留核心方法

| 教材原类 | 改写后 | 保留 |
|---|---|---|
| `class XxxTool(Tool)` | `class XxxTool:` | `__init__` + `call()` 核心逻辑 |
| `super().__init__(name=..., description=...)` | 删除 | — |

**约束**：类名与 `call(query) -> str` 方法名**保持不变**。
**理由**：这是**最小改动原则**——让读者对照时能一眼看出「只删了继承」。

### C-08 数据获取必须有网络兜底

**约束**：`fetch_*()` 函数必须 `try/except` + `timeout=5|10` + **返回模拟数据**兜底。
**打印约定**：兜底时打印 `  [网络兜底] ...抓取失败: {e}`。
**验收**：断网时脚本仍能跑完并输出结果。

### C-09 每篇文件头保留教材原 import 与问题说明

**约束**：注释块必须包含：
1. 教材原 `import` 行；
2. 为什么不可运行（路径断裂 / 虚构框架 / 端点变更 / 依赖缺失）；
3. 改写方案。
**验收**：9 篇均有「原写法（注释保留）」区块。

### C-10 实测输出与关键陷阱写入注释尾部

**约束**：能实际运行的例子（01/02/03/04）在文件末尾以注释记录**实测输出**与**值得讨论的细节**。
**实例**：
- 01：5 条文本中「人工智能是研究人类智能的模拟技术」语义距离最远未进前四；
- 02：6 个自然段并入 3 块 + 中文标点分隔符陷阱；
- 03：Top2 排序优势细微（向量细微差异决定）；
- 04：5 个句号 → 6 段（末尾空串）+ 白名单有全角括号无半角。

### C-11 未跑通的路径必须诚实标注

**约束**：依赖外部环境无法跑通的部分（Weaviate 需 Docker），**代码原样注释保留** + 明确说明未跑通原因 + 给出启动命令参考。
**实例**：06 篇的 `WeaviateSearchTool`（`docker run -p 8080:8080 semitechnologies/weaviate:latest`）。

### C-12 教材假标题/假实现如实标注，不粉饰

**约束**：教材中「标题与实现不符」的地方，必须在注释中**明确指认**。
**实例**：
- 03 篇标题「带语义找回功能 Agent」→ 注释：「本篇标题叫'带语义找回功能Agent'，但代码里没有 Agent——没有大模型调用、没有决策循环、没有工具，本质是'语义检索'（RAG 的 R）」。
- 09 篇标题「Qwen 和 DeepSeek」→ 注释：「原代码 `FiscalDataQueryTool.call()` 实际是硬编码 if/elif，根本没调 DeepSeek——这是个教材假标题，改写时保持现状」。

---

## 6. 逐文件契约（F-01 ~ F-09）

---

### F-01 `01_将中文文本转换为向量存入faiss.py`（68 行）——最小闭环篇

**意图**：RAG 起点——5 篇文档向量化 → 建 FAISS 索引 → 语义检索。

**导入契约**（1.x 路径）：
```python
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
```

**数据契约**：
```python
sample_texts = ["人工智能是研究人类智能的模拟技术", "大语言模型具备自然语言生成能力",
                "向量数据库实现高效相似性匹配", "嵌入模型用于将文本转化为向量",
                "LangChain用于构建语言模型应用"]
docs = [Document(page_content=text) for text in sample_texts]
```

**嵌入契约**：`DashScopeEmbeddings(model="text-embedding-v3", dashscope_api_key=api_key)`。

**核心动作契约**：
1. `vector_store = FAISS.from_documents(docs, embedding_model)`；
2. `results = vector_store.similarity_search("什么是向量数据库？")`（**默认 k=4**）；
3. `print(f"[匹配结果{i+1}]：{r.page_content}")`。

**验收标准**：
- V-01-A：输出 4 条匹配结果。
- V-01-B：**第 1 条为「向量数据库实现高效相似性匹配」**（与查询同话题）。
- V-01-C：「人工智能是研究人类智能的模拟技术」**不在前四**（语义距离最远）。

**已知风险**：模块级直接执行（无 `if __name__`），`import` 即触发 API 调用（见缺口 G-08）。

**教材问题（文件头注释实录）**：
> 原写法：langchain 0.x 的 import 路径 + `OpenAIEmbeddings`，在当前环境无法运行，原因有二：① 0.x 路径断裂：langchain 1.x 把嵌入类拆到 `langchain_community` / `langchain_openai`，FAISS 向量库拆到 `langchain_community`——报 `ImportError`；② `OpenAIEmbeddings` 默认直连 OpenAI 接口，国内环境无法访问。
> 教学点：本篇是大模型应用"检索增强"的起点——文档向量化后按语义相似度检索，后续接上大模型生成，就是完整的 RAG。

---

### F-02 `02_基于LangChain的文档切片实现.py`（53 行）——切片篇

**意图**：讲清切片三旋钮 + 中文分隔符陷阱。

**导入契约**：`from langchain_text_splitters import RecursiveCharacterTextSplitter`（1.x 独立包；类名/构造参数/行为与教材一致）。

**切片契约**：
```python
splitter = RecursiveCharacterTextSplitter(chunk_size=100, chunk_overlap=20)
chunks = splitter.split_text(document_text)
```
- **默认分隔符**：`["\n\n", "\n", " ", ""]` —— **无中文标点**；
- 6 个自然段的输入 → 贪婪合并成 3 块。

**输入契约**：6 段中文文档（AI 学科介绍 → 大语言模型 → RAG → 切片策略）。

**验收标准**：
- V-02-A：输出 **3 个 chunk**（Chunk 1/2/3）。
- V-02-B：Chunk 1 含前两段（AI 定义 + 学科交叉），Chunk 2 含第 3、4 段，Chunk 3 含第 5、6 段。
- V-02-C：每块长度接近但不超过 ~100 字符。

**已知风险**：
- ⚠️ **中文标点不在默认分隔符列表**——长段落中文（无换行）只能在 `\n` 处切，可能产生超长块或不自然边界（见缺口 G-05）。
- ⚠️ `chunk_overlap=20` 在段落级切分时**看不到字面重叠**（因为段落本身是完整句）——教材注释已说明此点，但读者容易误解「overlap 没用」。

**教材问题（文件头注释实录）**：
> 原写法：`from langchain.text_splitter import RecursiveCharacterTextSplitter`。原文的问题：langchain 0.x 的旧路径。1.x 把文本切分器拆到了独立的 `langchain_text_splitters` 包，旧路径下报 `ImportError`（与 01 篇的 embeddings 断裂同款问题）。
> 教学点：`RecursiveCharacterTextSplitter` 默认分隔符是 `["\n\n", "\n", " ", ""]`——按优先级递归降级，尽量在"自然边界"（段落→行→空格）切开；注意默认列表里**没有中文标点**（`。！？，`），中文文本只能在换行处切——对长段落中文文档，改进姿势是传入 `separators=["\n\n","\n","。","！","？","，"," ",""]`。

---

### F-03 `03_使用LangChain开发带语义找回功能Agent.py`（68 行）——检索参数篇

**意图**：与 01 同款流程，新增 **`k` 参数控制召回条数**。

**三步契约（教材导语原样保留）**：
1. 向量化（Embedding）；
2. 构建索引；
3. 相似度检索（余弦相似度 Top-K）。

**核心差异**：`db.similarity_search("什么是RAG机制？", k=2)` —— **显式指定 k=2**。

**知识库契约（5 条）**：LangChain 框架 / 向量数据库 / RAG 机制 / OpenAI 函数调用 / 嵌入模型。

**验收标准**：
- V-03-A：输出 `[Top 1]` 与 `[Top 2]` 两条。
- V-03-B：Top1 为「RAG机制结合检索系统与生成模型进行问答」（名至实归）。

**已知风险 / 诚实标注**：
- ⚠️ **标题含「Agent」但代码里没有 Agent**——文件头注释明确指出：「没有大模型调用、没有决策循环、没有工具，本质是'语义检索'（RAG 的 R）」。
- ⚠️ Top2 排序**优势细微**——「OpenAI模型支持…」「LangChain是…」「向量数据库支持…」同属「AI 技术能力描述」句式，语义距离接近，排序由向量细微差异决定（注释已说明，说明**检索结果的稳定性有限**）。

**教材问题（文件头注释实录）**：
> 原写法：langchain 0.x 的 import 路径 + `HuggingFaceEmbeddings` 本地模型，在当前环境无法运行，原因有三：① 0.x 路径断裂；② `HuggingFaceEmbeddings` 需要 `sentence-transformers` 包 + 首次运行从 HuggingFace 下载模型；③ **`all-MiniLM-L6-v2` 是英文向量模型（384 维）——对中文文本的语义匹配能力很弱**，用它检索中文知识库，排序会明显失真（模型选型必须匹配语言）。
> 【标题辨析（诚实说明）】本篇标题叫"带语义找回功能Agent"，但代码里没有 Agent——"Agent"成分要等检索结果接入大模型生成答案（后续篇）才真正出现。

---

### F-04 `04_文本清洗与句元切分.py`（97 行）——数据质量篇

**意图**：数据质量的第一道防线——正则清洗 + 按标点断句 + 贪婪拼接成 chunk。

**三个函数契约**：

| 函数 | 签名 | 实现 |
|---|---|---|
| `clean_text(text)` | → str | ① `re.sub(r"[^\u4e00-\u9fa5。！？；，、（）——""《》：A-Za-z0-9]", "", text)`（白名单保留）；② `re.sub(r"\s+", "", text)`（清空所有空白） |
| `split_sentences(text)` | → List[str] | `re.split(r"(?<=[。！？])", text)`（在句号/叹号/问号**后**断） |
| `generate_chunks(sentences, max_len=60)` | → List[str] | 贪婪拼接：能塞进 `max_len` 就继续，否则封块 |

**主流程契约**：`cleaned_text = clean_text(raw)` → `sentences = split_sentences(...)` → `chunks = generate_chunks(sentences, max_len=80)`。

**输出契约（改写：pandas DataFrame + `ace_tools` → 原生 `print`）**：
```
清洗后文本：{cleaned_text}
切分得到 {len(sentences)} 个句子
拼接得到 {len(chunks)} 个 chunk（max_len=80）：
  [1] ...
```

**验收标准**：
- V-04-A：清洗后文本为**一整行**（所有空白被删）。
- V-04-B：**`len(sentences) == 6`**（5 个句号 → 6 段，末段为空串）。
- V-04-C：**`len(chunks) == 5`**（空串被合并进最后一块）。
- V-04-D：5 个 chunk 与 02 篇 `RecursiveCharacterTextSplitter` 的产出**几乎等价**（对照）。

**已知风险 / 关键细节（注释已明确）**：
- ⚠️ **白名单有全角括号 `（）` 但没有半角 `()`** —— 半角括号会被当噪声删掉（见缺口 G-06）。
- ⚠️ **`re.split` 末尾空串陷阱** —— 正则分割的常见问题，生产需 `[s for s in sentences if s]` 过滤。
- ⚠️ `clean_text` 的 `\s+` 清除把**段落结构也抹平了** —— 这是刻意的（让文本变一行），但会丢失原文档的段落信息（见缺口 G-06）。
- 函数签名 `generate_chunks(sentences, max_len=60)` 但调用时传 `max_len=80`（**默认值未被使用**）。

**教材问题（文件头注释实录）**：
> 原写法（注释保留）：末尾有一行 Colab 专用调用：`import ace_tools as tools; tools.display_dataframe_to_user(...)`。`ace_tools` 是 Google Colab（AI Code Editor）的专属展示库，本地 Python 环境没有——运行会报 `ImportError`。改写：改成标准 `print` 输出 `chunks` 列表。另外 `import pandas as pd` 仅用于构造 DataFrame 展示——改写后也改用原生 `print`。

---

### F-05 `05_选择Qwen-Embedding模型做语义编码.py`（166 行）——嵌入选型 + 原生 FAISS 篇

**意图**：讲「嵌入模型怎么选」+ 露出「LangChain 封装底下的原生 faiss 操作」。

**三条路线的混装（文件头注释明确）**：
1. `qwen_embedding_client` / `qwen_agent` —— **虚构**；
2. `get_embeddings()` 用原生 requests 调百炼嵌入 API —— **曾是真实的，但 2025 年端点格式已变**（实测 `BadRequest.IllegalInput`）；
3. `faiss` + `numpy` 原生操作 —— **真实且稳定**（本篇核心教学资产）。

**数据获取契约（`fetch_finance_news`）**：
- URL：`https://www.kfzx.com.cn/api/newslist?page=1&pageSize=20`；
- 解析：`resp.json()["data"]["rows"]` → `item["Title"]`；
- 兜底：**6 条模拟金融新闻**（降准 / 国债 / MLF / 股份回购 / 流动性 / 国际收支）。

**嵌入契约（`get_embeddings`）**：
```python
_emb_model = DashScopeEmbeddings(model="text-embedding-v3", dashscope_api_key=api_key)
def get_embeddings(texts: List[str]) -> List[np.ndarray]:
    raw = _emb_model.embed_documents(texts)
    return [np.array(v, dtype=np.float32) for v in raw]
```
**签名契约**：**与原教材版一致**（`List[str] → List[np.ndarray]`），因此 `build_faiss_index` 零改动。

**原生 FAISS 契约**：
```python
def build_faiss_index(embeddings) -> faiss.IndexFlatL2:
    dim = embeddings[0].shape[0]
    index = faiss.IndexFlatL2(dim)
    index.add(np.vstack(embeddings))
    return index

def search_finance(query, index, docs) -> str:
    emb = get_embeddings([query])[0].reshape(1, -1)
    D, I = index.search(emb, k=3)
    return "\n".join([docs[i] for i in I[0]])
```

**Agent 契约**：
- `tool_registry = {"search_finance": None}` 占位，`main` 里注入 `lambda query: search_finance(query, index, docs)`（**闭包捕获 index/docs**）；
- `tools` 说明书 + `SYSTEM_MESSAGE`（金融资讯助手）；
- `agent_chat(config, user_input, memory=None)` —— 标准循环（同 chapter02 骨架）。

**输出契约**：抓取 → 嵌入 → 建索引 → Agent 回答「最近有哪些关于货币政策的消息？」。

**验收标准**：
- V-05-A：打印「已获取新闻 N 条」（N=6 兜底或真实条数）。
- V-05-B：Agent 回答引用检索到的新闻标题（含「货币政策」相关内容）。
- V-05-C：`tool_registry["search_finance"]` 被成功注入（不为 None）。

**已知风险**：
- ⚠️ **`get_embeddings` 的旧端点已废弃** —— 注释明确记录「改写前实测失败」，这是**有价值的一手踩坑记录**。
- ⚠️ `tool_registry` 用 `None` 占位再注入 —— 若 Agent 在注入前被调用会 `TypeError`（当前流程不会）。
- ⚠️ 真实站点（`kfzx.com.cn`）接口可能随时变动/失效（兜底已覆盖）。

**教材问题（文件头注释实录）**：
> 本篇的特殊性（三条路线混在一起）：1) `qwen_embedding_client`、`qwen_agent` 是教材虚构的框架；2) `get_embeddings()` 用原生 requests 调百炼嵌入 API——**这部分曾是真实的**，但 2025 年百炼嵌入 API 端点格式已变，原请求报 `BadRequest.IllegalInput`（实测验证：API 报 "The input parameter requires json format"）；3) `faiss` + `numpy` 原生操作——**真实且稳定**。
> 本篇的"原生 vs 封装"对照：`get_embeddings` 改成 LangChain 封装后，`build_faiss_index` + `search_finance` 仍是原生 faiss——正好展示"嵌入模型可插拔、底层存储不变"的架构设计。

---

### F-06 `06_用三种向量数据库做语义检索.py`（212 行）——多库对照篇

**意图**：同一份数据 + 同一种嵌入模型，换三种向量库，展示**部署形态差异**。

**三库契约**：

| 库 | 类 | 部署 | 检索接口 | 本篇状态 |
|---|---|---|---|---|
| **FAISS** | `FaissSearchTool` | 内存（本地库） | `faiss.IndexFlatL2` + `index.search` | ✅ 跑通 |
| **Chroma** | `ChromaSearchTool` | 嵌入式（本地库） | `chromadb.EphemeralClient()` + `collection.query(query_embeddings, n_results)` | ✅ 跑通（chromadb 1.5.9） |
| **Weaviate** | `WeaviateSearchTool`（注释） | **服务端**（需 Docker） | `weaviate.Client("http://localhost:8080")` | ❌ 注释保留 |

**Chroma 契约细节（1.x API 适配）**：
```python
import chromadb
self.client = chromadb.EphemeralClient()          # 纯内存，进程结束消失（与 FAISS 行为一致）
self.collection = self.client.create_collection(name="energy_policy")
self.collection.add(documents=[doc], ids=[f"doc{i}"], embeddings=[vec.tolist()])
# 检索
result = self.collection.query(query_embeddings=[emb], n_results=3)
return "\n".join(result["documents"][0])
```
**注意**：`EphemeralClient()` 取代教材的 `chromadb.Client()`（后者在 1.x 有弃用警告 + 改默认持久化路径）。

**Weaviate 契约（注释保留 + 启动命令）**：
```
docker run -p 8080:8080 semitechnologies/weaviate:latest
```

**数据获取契约（`fetch_energy_policy_titles`）**：
- URL：`https://www.nea.gov.cn/api/front/index/policynews?pageIndex=1&pageSize=20`；
- 兜底：**6 条模拟新能源政策**（补贴 / 光伏 / 锂电池回收 / 特高压 / 氢能 / 储能）。

**Agent 契约**：两个检索工具（`search_faiss` / `search_chroma`），共享同一知识库；`SYSTEM_MESSAGE` 要求模型「根据用户需求选择合适的工具」。

**验收标准**：
- V-06-A：打印「获取到 6 条政策」+ 构建 FAISS + 构建 Chroma + 「（Weaviate 需 Docker 服务，已跳过）」。
- V-06-B：Agent 回答中出现政策标题内容（证明检索生效）。
- V-06-C：`tool_registry` 含 `search_faiss` + `search_chroma` 两个键。
- V-06-D：注释中 Weaviate 启动命令存在。

**已知风险**：
- ⚠️ **`_faiss_tool` / `_chroma_tool` 是模块级全局变量**，`main` 里赋值 —— 若 `import` 该模块则两个都是 None（`search_faiss` 返回「未初始化」）。
- ⚠️ Chroma 用 `EphemeralClient`（内存）—— 与 FAISS 行为一致，但**不能立刻体现「向量数据库持久化」的优势**（见缺口 G-07）。
- ⚠️ 只演示「两种库跑通」，**未真正对比检索结果差异**（Agent 只选一个工具）。
- ⚠️ 三库的**接口差异未做统一抽象** —— 三个类各有自己的 `search`，若换库需改调用点。

**教材问题（文件头注释实录）**：
> 改写前的三条问题（同 05 篇结构）：1) `qwen_agent.Agent/Tool/Message`——虚构框架；2) `get_qwen_embedding()` 用原生 requests 调百炼端点——2025 年格式已变，实测 `BadRequest`；3) **Weaviate——需要本地 Docker 启动服务（localhost:8080），本机没有 Docker，注释保留**。
> 改写策略：Agent 改 dashscope function calling；嵌入模型改 `DashScopeEmbeddings`；FAISS + Chroma 真实跑通（chromadb 已安装 1.5.9），Weaviate 代码原样注释保留 + 说明。

---

### F-07 `07_实现一个RetrievalQA问答系统.py`（183 行）——完整闭环篇 ⭐

**意图（本章核心）**：把前 6 篇的零件串成**显式 RAG 完整闭环**。

**六步契约**：

| 步 | 函数/动作 | 输出 |
|---|---|---|
| 1 | `fetch_law_sections()` | 法律条文列表（兜底 6 条：环保法×2 / 刑法 / 劳动法 / 劳动合同法 / 消费者权益保护法） |
| 2 | `split_text_into_chunks(texts, max_length=150)` | 按 `。` 贪婪拼接的片段 |
| 3 | `get_qwen_embedding(chunks)` | 向量列表 |
| 4 | `LawRetrievalTool(chunks, embeddings)` | 原生 faiss 索引 + `call(query) -> str`（k=5） |
| 5 | `build_prompt_with_context(query, context)` | 带上下文的 prompt |
| 6 | `dashscope.Generation.call(...)` | 最终回答 |

**`build_prompt_with_context` 契约（RAG 的「A」核心）**：
```
你是一名法律智能助手。请根据以下法律条文内容回答用户问题。
【法律条文】：
{context}
【用户提问】：
{query}
请结合条文内容给出明确、简洁、准确的回答。
```

**显式三步契约（本篇最大教学点）**：
```python
context = retrieval_tool.call(question)                      # RAG 的 "R"
final_prompt = build_prompt_with_context(question, context)  # RAG 的 "A"
response = dashscope.Generation.call(..., messages=[{"role":"user","content":final_prompt}], ...)  # RAG 的 "G"
```

**验收标准**：
- V-07-A：打印「原始条文数量：6」「切分后片段数：N」。
- V-07-B：`[Step 1] 语义检索中` + `[Step 2] 组装 prompt 并生成回答` 两行出现。
- V-07-C：最终回答**引用环保法条文内容**（证明基于检索结果而非凭空生成）。
- V-07-D：断网时使用兜底条文，流程仍完整跑完。

**已知风险**：
- ⚠️ **`split_text_into_chunks` 的贪婪拼接有边界 bug** —— 当 `len(chunk)+len(p) >= max_length` 时直接 `chunks.append(chunk)`，**首次循环 `chunk` 为空串**时会 append 空串（若首句超长）（见缺口 G-03）。
- ⚠️ `max_tokens=1024` 较大 —— 可能产生较长回答。
- ⚠️ 无「检索质量评估」 —— 检索到的是否真的回答了问题无从验证（见缺口 G-04）。
- 检索用 **L2 距离**（`IndexFlatL2`），而教材导语说「余弦相似度」——**实现与描述不符**（`text-embedding-v3` 归一化后可近似，但严格说不等）。

**教材问题（文件头注释实录）**：
> 本篇的独特设计（与 05/06 篇的关键差异）：05/06 篇用 Agent function calling（模型自主决定调工具），但本篇第六步是**手动调用工具 + 手动拼 prompt + 手动调 Agent**——这是 RAG 最原始、最显式的形态：开发者写死"先检索、再把检索结果塞进 prompt、再调 LLM"。**这个设计值得保留作为教学点，让新人看到 function calling 底下到底藏了什么。**
> 改写前的三条问题：1) `qwen_agent.Agent/Tool/Message`——虚构框架；2) `get_qwen_embedding()` 用原生 requests 调百炼端点——2025 年格式已变；3) `fetch_law_sections()` 用真实 API——网络失败无兜底。

---

### F-08 `08_多段检索与Top-K融合的Agent.py`（149 行）——Top-K 融合篇

**意图**：同 07 结构，显式命名 **Top-K 融合**（`top_k=5` 多段拼接成融合上下文）。

**与 07 的差异契约**：

| 维度 | 07 篇 | 08 篇 |
|---|---|---|
| 检索条数 | `k=5`（硬编码） | `top_k=5`（构造参数） |
| 融合动作 | 直接 `"\n".join` | `fused_context = "\n".join(top_passages)`（**显式命名**） |
| 切片方式 | 按 `。` 贪婪拼接 | **硬切** `text[i:i+max_len]` |
| prompt | 法律条文模板 | 政策片段模板 |
| 数据 | 法律条文 | 统计政策（兜底 8 条） |

**切片契约（`split_chunks(texts, max_len=100)`）**：
```python
if len(text) <= max_len: chunks.append(text)
else: chunks.extend([text[i:i+max_len] for i in range(0, len(text), max_len)])
```
**特点**：**硬切会截断句子**，但每段长度一致，适合无标点短文本。

**融合契约（`MultiPassageRetrievalTool.call`）**：
```python
qvec = get_qwen_embedding([query])[0].reshape(1, -1)
D, I = self.index.search(qvec, self.top_k)
top_passages = [self.docs[i] for i in I[0]]
fused_context = "\n".join(top_passages)     # ← Top-K 融合：多段拼成更丰富上下文
return fused_context
```

**数据契约（`fetch_policy_data`）**：兜底 **8 条模拟统计政策**（GDP / 核算方法 / 人口普查 / 数字经济 / 固投 / 研发支出 / 碳排放 / 文化产业）。

**验收标准**：
- V-08-A：打印「原始政策标题数：8」「分段后共 N 段」。
- V-08-B：`[Step 1] 多段语义检索 + Top-K 融合中` + `[Step 2] 组装 prompt 并生成回答`。
- V-08-C：最终回答提及 GDP 核算方法相关文件（证明 Top-K 召回生效）。
- V-08-D：`top_k` 改为 1 后回答信息量应下降（对照）。

**已知风险**：
- ⚠️ **`top_k` 越大，prompt 越长** —— 无 token 预算控制，可能超模型上下文（见缺口 G-09）。
- ⚠️ **融合只是 `"\n".join`** —— 无去重、无重排序（rerank）、无相关性过滤；若召回里有噪声，会一并塞进 prompt。
- ⚠️ 硬切可能把一句政策标题切成两半，产生**语义碎片**。

**教材问题（文件头注释实录）**：
> 本篇与 07 篇的结构几乎同构——同样的"检索→拼 prompt→调 LLM"显式 RAG 流程，唯一差异：07 篇 k=5 但没显式叫"Top-K 融合"，本篇显式命名并默认 `top_k=5`。改写策略与 07 篇完全平行（三个问题同构处置）。
> 教材用的是 `text[i:i+max_len]` 硬切（按字符数均匀分段），与 04/07 的"按句号贪婪拼接"不同——硬切会截断句子，但优点是每段长度一致，适合无标点的短文本。

---

### F-09 `09_文本与结构化数据混合检索Qwen和DeepSeek.py`（193 行）——混合检索篇

**意图**：解决**异构数据召回**——文本（非结构化）+ 数值（结构化）双通道。

**双通道架构契约**：

```
用户查询 ─┬─→ [文本通道] FiscalTextSearchTool：向量化 → FAISS top-3 → 政策文本
          └─→ [数据通道] FiscalDataQueryTool：关键词匹配 → pandas 过滤 → 精确数值
                                │
                          结果融合 build_prompt(query, text_ctx, data_ctx)
                                │
                              LLM 生成
```

**文本通道契约（`FiscalTextSearchTool`）**：原生 faiss `k=3`，返回 `"\n".join([docs[i] for i in I[0]])`。

**数据通道契约（`FiscalDataQueryTool.call`，**硬编码关键词匹配**）**：

| 条件 | 行为 |
|---|---|
| `"2020" in query and "支出" in query` | 2020 支出占 GDP 比重 |
| `"收入" in query` | **2021** 收入占 GDP 比重（年份硬编码） |
| `"支出" in query` | **2024** 支出占 GDP 比重（年份硬编码） |
| 其他 | `"未能识别查询字段，请重新表述问题。"` |

**数据获取契约**：
- `fetch_fiscal_texts()`：财政部 API（兜底 6 条财政政策文本）；
- `fetch_structured_data()`：OWID CSV（`requests` 下载 + `pd.read_csv(StringIO(...))`，筛 `Entity=="China"`，取 Year / spending / revenue，**兜底 6 行 2019~2024 数据**）。

**融合 prompt 契约**：
```
你是一个财税智能助手，拥有文本政策知识和财政结构化数据。
【政策解读】：
{text_context}
【财政数据】：
{data_context}
请结合以上信息回答用户问题：
{query}
回答应准确、简洁、有数据支撑。
```

**验收标准**：
- V-09-A：打印「加载完成，共 6 条文本，6 行数据」。
- V-09-B：`[Step 1] 文本通道` + `[Step 2] 数据通道` + `[Step 3] 融合双通道结果` 三行出现。
- V-09-C：最终回答**同时包含政策描述与具体数值**（如「2020年中国政府支出占GDP比重为25.5%」）。
- V-09-D：查询「2020年中国的财政支出是多少？相关政策有没有调整说明？」→ 数据通道命中第一分支。

**已知风险 / 诚实标注**：
- 🔴 **标题含「DeepSeek」但代码从未调用 DeepSeek** —— 文件头注释明确指认：「原代码 `FiscalDataQueryTool.call()` 实际是硬编码 if/elif，根本没调 DeepSeek——这是个教材假标题」。
- ⚠️ **数据通道是伪 NL→SQL** —— 手写 `if/elif` 关键词匹配，**只能回答 3 种预设问题**（见缺口 G-01）。
- ⚠️ `"收入" in query` 分支的年份硬编码 `2021` —— 与用户问题中的年份无关（若问「2020年收入」会返回 2021 数据）。
- ⚠️ OWID CSV 从 GitHub 下载，国内可能慢/失败（兜底已覆盖）。
- ⚠️ 融合无权重、无冲突处理 —— 若文本通道与数据通道矛盾，LLM 如何取舍未定义。

**教材问题（文件头注释实录）**：
> 额外发现：标题里提到"Qwen 和 DeepSeek"，但原代码 `FiscalDataQueryTool.call()` 实际是硬编码 if/elif，根本没调 DeepSeek——这是个教材假标题，改写时保持现状（因为真正的 NL→SQL 需要 LLM 调工具链，会让本篇偏离"混合检索"的教学重心）。
> 改写策略：同 07/08 篇——嵌入模型改 `DashScopeEmbeddings`，FAISS 原生操作保留，Agent 调 `qwen-plus`，两个 Tool 去虚构继承，数据加载加网络兜底。

---

## 7. 全章验收清单（V-01 ~ V-12）

### 7.1 运行层验收

| 编号 | 验收项 | 期望 |
|---|---|---|
| V-01 | `python 01_...py` | 4 条匹配结果，第 1 条为「向量数据库实现高效相似性匹配」 |
| V-02 | `python 02_...py` | 3 个 chunk |
| V-03 | `python 03_...py` | 2 条 Top 结果，Top1 为 RAG 机制 |
| V-04 | `python 04_...py` | 清洗后一行 + 6 句 + 5 chunk |
| V-05 | `python 05_...py` | 6 条新闻 + Agent 回答含政策内容 |
| V-06 | `python 06_...py` | FAISS + Chroma 构建成功，Weaviate 跳过 |
| V-07 | `python 07_...py` | 显式三步 + 回答引用环保法条文 |
| V-08 | `python 08_...py` | Top-K 融合 + 回答提及 GDP 核算 |
| V-09 | `python 09_...py` | 双通道 + 回答含政策 + 数值 |

### 7.2 契约层验收

| 编号 | 契约 | 对应 | 验证方式 |
|---|---|---|---|
| V-10 | 无 `OpenAIEmbeddings` / `HuggingFaceEmbeddings`（C-01） | 全章 | grep 只命中注释 |
| V-11 | 无 `from langchain.` 旧路径（C-02） | 全章 | grep 只命中注释 |
| V-12 | `get_qwen_embedding` 签名统一（C-06） | 05~09 | grep 函数定义 |
| V-13 | `fetch_*` 均有网络兜底（C-08） | 05~09 | grep `[网络兜底]` |

### 7.3 学习层验收

- [ ] 能默写 RAG 最小闭环骨架。
- [ ] 能说出 `FAISS.from_documents` 在原生 faiss 里对应哪几行。
- [ ] 能画出显式 RAG 的三步。
- [ ] 能说出 09 篇「假 DeepSeek」的具体位置。

---

## 8. 已知缺口与后续改进（Gap Analysis）

| 编号 | 等级 | 缺口 | 影响 | 建议改进 | 对照章节 |
|---|---|---|---|---|---|
| G-01 | 🔴 | 09 篇数据通道是**伪 NL→SQL**（3 个 if/elif 分支） | 只能回答预设问题，标题「DeepSeek」名不副实 | 用 function calling 让 LLM 生成 SQL | chapter01-03 / 13 |
| G-02 | 🟠 | 全章 `os.environ.get('DASHSCOPE_API_KEY')` **无空值校验** | key 未设时报错晦涩 | 启动时校验并提示 | chapter12 |
| G-03 | 🟠 | 07 篇 `split_text_into_chunks` **首句超长时会 append 空串** | 产生空 chunk 污染索引 | 加 `if chunk:` 守卫 | — |
| G-04 | 🟠 | 全章**无检索质量评估** | 无法知道检索是否真的回答了问题 | 引入命中率/LLM-as-a-Judge 评估 | chapter13 |
| G-05 | 🟠 | 02 篇默认分隔符**无中文标点** | 长段落中文切分不自然 | 显式传 `separators` 含 `。！？，` | — |
| G-06 | 🟠 | 04 篇白名单**无半角括号** + `\s+` 抹平段落 + 末尾空串 | 清洗过度/产生空串 | 白名单补全 + 过滤空串 + 保留段落 | — |
| G-07 | 🟠 | 06 篇 Chroma 用 `EphemeralClient`（内存） | 未体现向量库持久化优势 | 用 `PersistentClient(path=...)` 展示持久化 | — |
| G-08 | 🟠 | 01/02/03/04 **模块级直接执行**（无 `if __name__`） | `import` 即触发 API 调用/打印 | 加主入口守卫 | — |
| G-09 | 🟠 | 08/09 篇 **prompt 无 token 预算控制** | `top_k` 大时可能超上下文 | 加 token 计数 + 动态截断 | — |
| G-10 | 🟠 | 全章**无 rerank** | 召回噪声直接进 prompt | 引入重排序模型 / LLM 筛选 | — |
| G-11 | 🟡 | 全章检索用 **L2 距离**（07 导语却说「余弦相似度」） | 描述与实现不符（归一化后近似） | 统一为 `IndexFlatIP` + 归一化，或改描述 | — |
| G-12 | 🟡 | 05/06 篇 `_xxx_tool` **模块级全局变量** | `import` 时未初始化 | 改为类封装或显式初始化检查 | — |
| G-13 | 🟡 | 09 篇数据通道**年份硬编码**（2021/2024） | 「2020年收入」会返回 2021 数据 | 从 query 解析年份 | — |
| G-14 | 🟡 | 全章**无去重**（相同文本可能重复召回） | prompt 冗余 | 召回后按内容去重 | — |
| G-15 | 🟡 | 全章**无缓存**（同一查询重复嵌入/重复调用） | 浪费额度与时间 | 加嵌入/回答缓存 | chapter12（cache） |

### 缺口优先级建议

- **P0（正确性）**：G-01（伪 NL→SQL）、G-03（空 chunk）
- **P1（质量）**：G-05/G-06（切分与清洗）、G-09（token 预算）、G-10（rerank）
- **P2（健壮性）**：G-02、G-07、G-12、G-13
- **P3（整洁）**：G-08、G-11、G-14、G-15

---

## 附录 A：RAG 最小闭环代码骨架（全章共用）

```python
# ① 向量化
from langchain_community.embeddings import DashScopeEmbeddings
emb = DashScopeEmbeddings(model="text-embedding-v3", dashscope_api_key=api_key)

# ② 建索引（封装版）
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
docs = [Document(page_content=t) for t in texts]
store = FAISS.from_documents(docs, emb)

# ③ 检索
results = store.similarity_search(query, k=4)
for r in results: print(r.page_content)
```

**原生版等价物（05/06/07/08/09）**：
```python
import faiss, numpy as np
vecs = [np.array(v, dtype=np.float32) for v in emb.embed_documents(texts)]
index = faiss.IndexFlatL2(vecs[0].shape[0])
index.add(np.vstack(vecs))
qvec = np.array(emb.embed_documents([query])[0], dtype=np.float32).reshape(1, -1)
D, I = index.search(qvec, k=4)
hits = [texts[i] for i in I[0]]
```

## 附录 B：三种向量库对照

| 维度 | FAISS | Chroma | Weaviate |
|---|---|---|---|
| 部署 | 本地库（内存） | 本地库（嵌入式） | **服务端（需 Docker）** |
| 依赖 | `faiss`（+ numpy） | `chromadb` | `weaviate-client` + 容器 |
| 元数据 | 自行管理 | 内建 `metadata` | 内建 schema |
| 持久化 | 需 `save_local` | `PersistentClient` | 服务端自带 |
| 适用 | 极致性能本地原型 | 轻量嵌入式应用 | 生产级服务化 |
| 本篇状态 | ✅ 跑通 | ✅ 跑通（EphemeralClient） | ❌ 注释保留 |

## 附录 C：切片策略对照（02 / 04 / 08）

| 篇 | 策略 | 边界 | 长度 | 会截断句子 |
|---|---|---|---|---|
| 02 | 递归降级（默认分隔符） | 跟随 `\n\n`→`\n`→` ` | 不固定（≤ chunk_size） | 否（若分隔符合适） |
| 04 | 断句 + 贪婪拼接 | 跟随 `。！？` | 不固定（≤ max_len） | 否 |
| 08 | 硬切 | 无（按字符数） | **固定** | **是** |

## 附录 D：显式 RAG vs 隐式 RAG（function calling）

| 维度 | 显式（07/08/09） | 隐式（05/06） |
|---|---|---|
| 谁决定检索 | 开发者 | 模型 |
| 代码 | `ctx=tool.call(q); prompt=build(q,ctx); LLM(prompt)` | `tools=[...]; 循环执行 tool_calls` |
| 可预测 | ✅ | ❌ |
| 灵活 | ❌ | ✅ |
| 教学 | **看得见骨架** | 看得见自主性 |
