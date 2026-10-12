# 【例 12-7】模拟 MCP 服务与 Coze 调用 —— 统一协议层的 Agent 系统
#
# ★ 教材简化 vs 真实规范（本篇重点：MCP 协议辨析）
#
# 教材原版问题（已注释保留）：
#   ① import redis —— 本环境无 Redis，按约定改用运行目录 cache.json
#   ② Qwen2Chat / DeepSeekChat —— LangChain 虚构类（同例 12-4/05，不存在）
#   ③ ConversationBufferMemory / ConversationalRetrievalChain —— 官方已废弃
#   ④ HuggingFaceEmbeddings + Chroma —— 需下载 90MB 本地模型 + 重依赖；
#      ./chroma_db/ 目录凭空出现，空库也能"检索成功"
#   ⑤ memory.chat_memory.messages = history —— 直接注入绕开框架截断逻辑
#      （char08-04 踩过的同款陷阱）
#   ⑥ qa_chain.run() —— 废弃调用方式
#   ⑦ "MCP 协议层"名不副实 —— 教材只是把消息历史存进 Redis 并给键加
#      mcp: 前缀。真实 MCP（Model Context Protocol）是 Anthropic 于
#      2024-11 发布、2025-06-18 最新修订的跨进程开放标准：JSON-RPC 2.0
#      信封 + initialize 生命周期握手 + tools/resources/prompts 三大
#      原语，与"给消息缓存起个 mcp: 前缀"毫无关系
#   ⑧ "Coze 调用"凭空 —— 真实扣子（Coze）平台 2025 年通过注册
#      "MCP 扩展"（填一个 MCP 服务 URL）集成外部工具，运行时 Bot 按
#      MCP 协议拉取工具清单并调用，不存在教材这种进程内函数直调
#   ⑨ user 消息在 qa_chain.run() 之后才写缓存 —— 本轮输入不进本次
#      上下文，且调用失败时消息丢失（顺序 bug）
#
# 本次改写（真实 MCP 2025-06-18 规范最小实现 + Coze Bot 编排模拟）：
#   ① McpServer：JSON-RPC 2.0 单入口 handle()，实现 initialize 握手
#      （protocolVersion/capabilities/serverInfo）、tools/list、
#      tools/call、resources/list、resources/read，以及标准错误码
#      （-32700 解析错误 / -32601 方法不存在 / -32602 参数非法）
#   ② 工具 search_knowledge：dashscope TextEmbedding + 余弦相似度检索
#      （替代 Chroma + 本地 HuggingFace 模型，向量缓存落盘防重复计费，
#      沿用例 12-4 模式）
#   ③ 会话历史 resource：以 session://{id}/history URI 暴露，客户端经
#      resources/read 读取 —— 真实 MCP 把上下文当"资源"而非"消息前缀"
#   ④ McpClient：协议客户端（请求 id 自增、initialized 通知、错误抛异常）
#   ⑤ CozeBot：模拟扣子 Bot 工作流 —— MCP 工具调用取知识 → 组装上下文
#      → qwen-plus 生成（教材的 qwen/deepseek 切换改为可配置后端）
#   ⑥ cache.json 替代 Redis（保留教材 mcp:{session_id}:messages 键结构
#      思想）；先写 user 历史再生成，修复教材顺序 bug
#   ⑦ 传输层说明：教学用进程内消息传递（协议层与传输层解耦是 MCP 的
#      设计要点）；生产环境用官方 mcp SDK（pip install mcp）跑 stdio
#      或 Streamable HTTP 传输，本篇协议消息结构与其完全一致

# ============================================================
# 原代码（注释保留——教材简化版，伪 MCP + 虚构类 + 废弃 API）
# ============================================================
# # 统一协议层封装版，Coze+MCP：
# # -*- coding:utf-8 -*-
# # MCP协议层封装的统一Agent系统，整合Coze+Redis+Chroma+Qwen3.0+Deepseek-v1
#
# import os, uuid, redis, json
# from langchain_community.chat_models import Qwen2Chat, DeepSeekChat  # ← 虚构
# from langchain.vectorstores import Chroma                            # ← 依赖已迁移
# from langchain.embeddings import HuggingFaceEmbeddings               # ← 本地模型
# from langchain.memory import ConversationBufferMemory                # ← 已废弃
# from langchain.chains import ConversationalRetrievalChain            # ← 已废弃
# from langchain.schema import HumanMessage, AIMessage
#
# # 一、统一配置
# REDIS_HOST = "localhost"
# REDIS_PORT = 6379
# CHROMA_DIR = "./chroma_db/"
# EMBED_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
#
# # 二、缓存系统
# rds = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)            # ← Redis 依赖
#
# # 三、加载向量知识库
# embedding = HuggingFaceEmbeddings(model_name=EMBED_MODEL_NAME)
# vectorstore = Chroma(persist_directory=CHROMA_DIR, embedding_function=embedding)
#
# # 四、MCP协议层封装结构                    ← 名不副实：只是 Redis 键加前缀
# def format_mcp_messages(session_id):
#     key = f"mcp:{session_id}:messages"
#     raw = rds.lrange(key, 0, -1)
#     return [{"role": json.loads(item.decode())["role"], "content": json.loads(item.decode())["content"]} for item in raw]
#
# def cache_mcp_message(session_id, role, content):
#     msg = json.dumps({"role": role, "content": content})
#     key = f"mcp:{session_id}:messages"
#     rds.rpush(key, msg)
#
# # 五、模型统一封装为Coze调用函数
# def call_model(session_id, user_input, agent_type="qwen"):
#     memory = ConversationBufferMemory(return_messages=True)
#     history = []
#     mcp_history = format_mcp_messages(session_id)
#     for entry in mcp_history:
#         if entry["role"] == "user":
#             history.append(HumanMessage(content=entry["content"]))
#         else:
#             history.append(AIMessage(content=entry["content"]))
#     memory.chat_memory.messages = history     # ← 直接注入绕开截断逻辑
#     llm = Qwen2Chat(model="Qwen/Qwen1.5-14B-Chat") if agent_type == "qwen" \
#         else DeepSeekChat(model="deepseek-ai/deepseek-llm-chat")   # ← 虚构类
#     qa_chain = ConversationalRetrievalChain.from_llm(              # ← 已废弃
#         llm=llm,
#         retriever=vectorstore.as_retriever(search_kwargs={"k": 2}),
#         memory=memory
#     )
#     response = qa_chain.run(user_input)       # ← 废弃调用方式
#     cache_mcp_message(session_id, "user", user_input)   # ← 顺序 bug：应先写
#     cache_mcp_message(session_id, "assistant", response)
#     return response
#
# # 六、模拟Coze平台任务流：Agent切换对话
# def simulate_coze_agent_workflow():
#     session_id = str(uuid.uuid4())
#     print("[Qwen Agent 回复]")
#     print(call_model(session_id, "什么是位置编码？", agent_type="qwen"))
#     print("\n[Deepseek Agent 回复]")
#     print(call_model(session_id, "位置编码和RoPE有什么不同？", agent_type="deepseek"))
#
# # 七、运行模拟工作流
# simulate_coze_agent_workflow()
# ============================================================

import os
import sys
import json
import math
import uuid
import logging
import dashscope

# ===== dashscope 统一配置（前 10 章模式）=====
dashscope.api_key = os.environ.get("DASHSCOPE_API_KEY")

# ===== 日志：控制台输出 =====
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

# ===== 常量 =====
MCP_PROTOCOL_VERSION = "2025-06-18"   # MCP 官方最新规范版本号
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache.json")
EMBEDDING_MODEL = "text-embedding-v3"  # DashScope 语义向量模型（1024 维）
CHAT_MODEL = "qwen-plus"               # Coze Bot 底层生成模型
TOP_K = 2                              # 知识检索返回最相关的 2 个分块（教材 k=2）

# 内置知识库文本（替代教材缺失的 ./chroma_db/，主题与教材两问匹配）
KNOWLEDGE_TEXT = """位置编码（Positional Encoding）让 Transformer 感知 token 顺序。原始 Transformer 使用正弦位置编码，用不同频率的 sin/cos 函数为每个位置生成固定向量，与词向量相加后输入模型。
正弦位置编码的优点是无需训练、可外推到训练时未见过的序列长度，但它是绝对位置方案，不能直接表达两个 token 之间的相对位置关系。
RoPE（旋转位置编码，Rotary Position Embedding）是目前主流大模型（LLaMA、Qwen、DeepSeek 等）采用的方案，核心思想是把位置信息注入自注意力计算的 Q/K 向量：对每个位置的 Q、K 做与位置相关的旋转，使 Q 与 K 的点积只依赖相对位置差。
RoPE 具备相对位置感知、外推性好、实现高效的特点，配合 NTK-aware 缩放或 YaRN 等技术可以把上下文窗口扩展到数十万 token。
ALiBi（线性偏置注意力）是另一种相对位置方案：不修改 Q/K 向量，而是在注意力分数上叠加与距离成正比的线性惩罚，使远距离 token 的注意力自然衰减。"""

# MCP 工具定义（inputSchema 为标准 JSON Schema —— 真实 MCP tools 原语格式）
SEARCH_TOOL_DEF = {
    "name": "search_knowledge",
    "description": "在 LLM 知识库中检索与查询语义最相关的知识分块",
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "检索查询语句"},
            "top_k": {"type": "integer", "description": "返回条数", "default": TOP_K},
        },
        "required": ["query"],
    },
}


# ============================================================
# 组件 1：JSONCache（cache.json 替代 Redis，保留教材键结构思想）
# ============================================================

class JSONCache:
    """基于 cache.json 的缓存，替代 Redis 的 mcp:{session_id}:messages 存储

    结构: {"mcp_sessions": {sid: [{"role","content"}]}, "vectors": {...}}
    """

    def __init__(self, path: str):
        """初始化缓存

        参数: path — cache.json 文件路径；文件损坏时按空缓存重建
        """
        self._path = path
        try:
            with open(path, "r", encoding="utf-8") as f:
                self._data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self._data = {}

    def append_message(self, session_id: str, role: str, content: str):
        """向指定会话追加一条消息（等价教材 Redis rpush）"""
        sessions = self._data.setdefault("mcp_sessions", {})
        sessions.setdefault(session_id, []).append({"role": role, "content": content})
        self._save()

    def get_messages(self, session_id: str) -> list:
        """读取指定会话的全部消息（等价教材 Redis lrange 0 -1）"""
        return list(self._data.get("mcp_sessions", {}).get(session_id, []))

    def list_sessions(self) -> list:
        """返回全部已有会话 id（resources/list 的数据来源）"""
        return list(self._data.get("mcp_sessions", {}).keys())

    def set_vectors(self, doc_id: str, vector: list):
        """缓存知识分块的语义向量（避免重复调用 embedding API 计费）"""
        self._data.setdefault("vectors", {})[doc_id] = vector
        self._save()

    def get_vectors(self) -> dict:
        """返回全部已缓存向量 {doc_id: [float, ...]}"""
        return self._data.get("vectors", {})

    def _save(self):
        """落盘到 cache.json（单进程教学场景，整体覆写即可）"""
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=1)


# ============================================================
# 组件 2：语义知识库（dashscope 向量 + 余弦检索，替代 Chroma）
# ============================================================

def split_text(text: str, chunk_size: int = 120) -> list:
    """把知识文本按行聚合成分块（替代教材 langchain 切分器）

    参数: text — 原始知识文本; chunk_size — 单块目标长度
    返回: 分块字符串列表
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    chunks, buf = [], ""
    for ln in lines:
        if buf and len(buf) + len(ln) > chunk_size:
            chunks.append(buf)
            buf = ln
        else:
            buf = f"{buf} {ln}".strip()
    if buf:
        chunks.append(buf)
    return chunks


def embed_texts(texts: list) -> list:
    """调用 DashScope TextEmbedding API 批量生成语义向量

    参数: texts — 文本列表
    返回: 与输入顺序对应的向量列表
    异常: API 失败时抛 RuntimeError（由上层兜底）
    """
    resp = dashscope.TextEmbedding.call(model=EMBEDDING_MODEL, input=texts)
    if resp.status_code != 200:
        raise RuntimeError(f"Embedding API 失败: {resp.code} {resp.message}")
    ordered = sorted(resp.output["embeddings"], key=lambda e: e["text_index"])
    return [e["embedding"] for e in ordered]


def cosine_similarity(a: list, b: list) -> float:
    """计算两个向量的余弦相似度（-1~1，越大语义越相近）"""
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(x * x for x in b))
    return dot / norm if norm else 0.0


class KnowledgeBase:
    """长期知识库：分块 → 向量化（带 cache.json 缓存）→ top-k 语义检索"""

    def __init__(self, cache: JSONCache, text: str):
        """构建知识库：优先复用缓存向量，缺失分块才调用 embedding API

        参数: cache — 缓存对象（向量存进去）; text — 知识原文
        """
        self._chunks = split_text(text)
        try:
            cached = cache.get_vectors()
            missing = [(i, c) for i, c in enumerate(self._chunks) if str(i) not in cached]
            if missing:
                logger.info(f"[向量] 新增 {len(missing)} 个分块，调用 embedding API")
                vectors = embed_texts([c for _, c in missing])
                for (i, _), v in zip(missing, vectors):
                    cache.set_vectors(str(i), v)
            self._vectors = [cache.get_vectors()[str(i)] for i in range(len(self._chunks))]
            self._ready = True
            logger.info(f"[向量] 知识库就绪: {len(self._chunks)} 个分块")
        except Exception as e:
            # 网络不可用时检索降级为空（外部接口必须兜底的硬约定）
            self._vectors, self._ready = [], False
            logger.warning(f"[向量] embedding 不可用，知识检索降级为空: {e}")

    def search(self, query: str, top_k: int = TOP_K) -> list:
        """语义检索：返回与 query 最相关的 (分块, 相似度) 列表

        异常: 不向外抛——任何失败降级为空结果
        """
        if not self._ready:
            return []
        try:
            qvec = embed_texts([query])[0]
        except Exception as e:
            logger.warning(f"[向量] 查询向量化失败: {e}")
            return []
        scored = [(chunk, cosine_similarity(qvec, vec))
                  for chunk, vec in zip(self._chunks, self._vectors)]
        scored.sort(key=lambda x: -x[1])
        return scored[:top_k]


# ============================================================
# 组件 3：MCP Server（真实 2025-06-18 规范：JSON-RPC 2.0 + 原语）
# ============================================================

class McpServer:
    """MCP 服务器最小实现：initialize 生命周期 + tools/resources 原语

    与教材"伪 MCP"的本质区别：
      - 协议消息是 JSON-RPC 2.0 信封（jsonrpc/id/method/params/error）
      - 必须先 initialize 握手协商 protocolVersion 与 capabilities
      - 工具带 JSON Schema 入参声明，结果包装为 content 数组
    """

    def __init__(self, knowledge_base: KnowledgeBase, cache: JSONCache):
        """注入依赖

        参数: knowledge_base — 知识库（工具实现）; cache — 会话历史（资源实现）
        """
        self._kb = knowledge_base
        self._cache = cache

    def handle(self, raw: str) -> str:
        """协议单入口：解析 JSON-RPC 请求 → 分发 method → 序列化响应

        参数: raw — 原始 JSON-RPC 请求文本
        返回: 响应文本；notification（无 id）返回空串
        """
        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            return self._dump(self._error(None, -32700, "Parse error"))
        req_id, method = req.get("id"), req.get("method", "")
        if req_id is None:
            return ""    # notification（如 notifications/initialized）：按规范不回包
        dispatch = {
            "initialize": self._initialize,
            "tools/list": self._tools_list,
            "tools/call": self._tools_call,
            "resources/list": self._resources_list,
            "resources/read": self._resources_read,
        }
        handler = dispatch.get(method)
        if handler is None:
            return self._dump(self._error(req_id, -32601, f"Method not found: {method}"))
        try:
            result = handler(req.get("params") or {})
        except ValueError as e:
            return self._dump(self._error(req_id, -32602, str(e)))   # 参数级错误
        return self._dump({"jsonrpc": "2.0", "id": req_id, "result": result})

    # ---- MCP 原语：initialize（生命周期起点）----

    def _initialize(self, params: dict) -> dict:
        """握手：协商协议版本并声明服务器能力"""
        return {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {"tools": {}, "resources": {}},
            "serverInfo": {"name": "knowledge-mcp-server", "version": "1.0.0"},
        }

    # ---- MCP 原语：tools（模型可调用的函数）----

    def _tools_list(self, params: dict) -> dict:
        """列出本服务器提供的全部工具（含 JSON Schema 入参声明）"""
        return {"tools": [SEARCH_TOOL_DEF]}

    def _tools_call(self, params: dict) -> dict:
        """执行工具调用；工具执行失败按规范用 isError 标记（非 JSON-RPC 错误）"""
        name = params.get("name")
        args = params.get("arguments") or {}
        if name != "search_knowledge":
            raise ValueError(f"未知工具: {name}")
        query = (args.get("query") or "").strip()
        if not query:
            raise ValueError("query 不能为空")
        try:
            hits = self._kb.search(query, int(args.get("top_k", TOP_K)))
            text = "\n\n".join(f"[{i + 1}] {c}（相似度 {s:.3f}）"
                               for i, (c, s) in enumerate(hits)) or "（知识库未命中）"
            is_error = False
        except Exception as e:
            text, is_error = f"检索失败: {e}", True
        return {"content": [{"type": "text", "text": text}], "isError": is_error}

    # ---- MCP 原语：resources（客户端可读的上下文数据）----

    def _resources_list(self, params: dict) -> dict:
        """列出全部会话历史资源（uri = session://{sid}/history）"""
        items = [{"uri": f"session://{sid}/history", "name": f"会话 {sid} 的对话历史",
                  "mimeType": "application/json"} for sid in self._cache.list_sessions()]
        return {"resources": items}

    def _resources_read(self, params: dict) -> dict:
        """读取指定 URI 的资源内容（会话历史 JSON）"""
        uri = params.get("uri", "")
        prefix, suffix = "session://", "/history"
        sid = uri[len(prefix):-len(suffix)] if uri.startswith(prefix) and uri.endswith(suffix) else ""
        msgs = self._cache.get_messages(sid) if sid else []
        if not msgs:
            raise ValueError(f"资源不存在: {uri}")
        return {"contents": [{"uri": uri, "mimeType": "application/json",
                              "text": json.dumps(msgs, ensure_ascii=False, indent=1)}]}

    # ---- JSON-RPC 2.0 辅助 ----

    @staticmethod
    def _error(req_id, code: int, message: str) -> dict:
        """构造 JSON-RPC 标准错误响应"""
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}

    @staticmethod
    def _dump(payload: dict) -> str:
        """响应序列化（中文原样输出）"""
        return json.dumps(payload, ensure_ascii=False)


# ============================================================
# 组件 4：MCP Client（扣子 Bot 的连接器角色）
# ============================================================

class McpClient:
    """MCP 客户端：组装 JSON-RPC 请求 → 交给 server.handle → 解析响应

    协议细节：
      - 请求 id 自增且与响应一一对应
      - initialize 后必须发 notifications/initialized 通知（规范要求）
      - 响应含 error 字段时抛 RuntimeError（协议层错误）
    """

    def __init__(self, server: McpServer):
        """绑定服务器

        参数: server — MCP 服务器实例
        """
        self._server = server
        self._next_id = 0
        self.initialized = False

    def _request(self, method: str, params: dict = None) -> dict:
        """发送请求并返回 result；协议错误抛 RuntimeError"""
        self._next_id += 1
        req = json.dumps({"jsonrpc": "2.0", "id": self._next_id,
                          "method": method, "params": params or {}})
        resp = json.loads(self._server.handle(req))
        if "error" in resp:
            raise RuntimeError(f"MCP 错误 {resp['error']['code']}: {resp['error']['message']}")
        return resp["result"]

    def initialize(self) -> dict:
        """执行 initialize 握手 + initialized 通知（MCP 生命周期起点）"""
        result = self._request("initialize", {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "coze-bot-client", "version": "1.0.0"},
        })
        note = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert self._server.handle(note) == ""   # 通知无响应（协议规范）
        self.initialized = True
        return result

    def call_tool(self, name: str, arguments: dict) -> dict:
        """调用服务器工具，返回 CallToolResult（content 数组 + isError）"""
        return self._request("tools/call", {"name": name, "arguments": arguments})

    def list_tools(self) -> list:
        """拉取服务器工具清单"""
        return self._request("tools/list")["tools"]

    def read_resource(self, uri: str) -> dict:
        """读取指定 URI 的资源内容"""
        return self._request("resources/read", {"uri": uri})

    def list_resources(self) -> list:
        """列出服务器暴露的全部资源"""
        return self._request("resources/list")["resources"]


# ============================================================
# 组件 5：CozeBot（扣子 Bot 编排工作流模拟）
# ============================================================

class CozeBot:
    """扣子 Bot 编排模拟：MCP 工具调用取知识 → 上下文组装 → LLM 生成

    对应真实扣子平台的运行方式：Bot 配置 MCP 扩展后，对话时按 MCP
    协议拉取工具清单并调用工具，再把工具结果拼进提示词生成回复。
    """

    def __init__(self, client: McpClient, cache: JSONCache):
        """注入依赖

        参数: client — MCP 客户端; cache — 会话历史缓存
        """
        self._client = client
        self._cache = cache

    def chat(self, session_id: str, user_input: str) -> str:
        """一轮对话：先写历史 → MCP 检索知识 → LLM 生成 → 回写历史

        参数: session_id — 会话标识; user_input — 用户输入
        返回: 助手回复文本
        """
        self._cache.append_message(session_id, "user", user_input)  # 修复教材顺序 bug
        knowledge = self._fetch_knowledge(user_input)
        answer = self._generate(self._build_messages(session_id, knowledge))
        self._cache.append_message(session_id, "assistant", answer)
        return answer

    def _fetch_knowledge(self, query: str) -> str:
        """经 MCP 协议调用 search_knowledge 工具（异常兜底返回空串）"""
        try:
            result = self._client.call_tool("search_knowledge", {"query": query})
            if result.get("isError"):
                logger.warning(f"[MCP] 工具执行失败: {result['content'][0]['text']}")
                return ""
            return result["content"][0]["text"]
        except Exception as e:
            logger.warning(f"[MCP] 工具调用异常: {e}")
            return ""

    def _build_messages(self, session_id: str, knowledge: str) -> list:
        """组装上下文：system（知识增强）+ 完整会话历史"""
        messages = []
        if knowledge:
            messages.append({"role": "system",
                             "content": f"你是 AI 助手，请优先依据以下检索到的知识回答问题：\n{knowledge}"})
        for m in self._cache.get_messages(session_id):
            messages.append({"role": m["role"], "content": m["content"]})
        return messages

    def _generate(self, messages: list) -> str:
        """调用 qwen-plus 生成回复（外部接口异常兜底）"""
        try:
            resp = dashscope.Generation.call(model=CHAT_MODEL, messages=messages,
                                             max_tokens=256, result_format="message")
            if resp.status_code != 200:
                raise RuntimeError(f"{resp.code} {resp.message}")
            return resp.output.choices[0].message.content
        except Exception as e:
            logger.error(f"[LLM] 调用失败: {e}")
            return "（系统繁忙，请稍后再试。）"


# ===== 全局对象：缓存 / 知识库 / 服务器 =====
cache = JSONCache(CACHE_FILE)
knowledge_base = KnowledgeBase(cache, KNOWLEDGE_TEXT)
server = McpServer(knowledge_base, cache)


# ============================================================
# main 入口：6 项 self-test
# ============================================================

def run_self_test() -> bool:
    """验证 MCP 协议链路：握手 / 工具 / 资源 / 错误码 / Coze 工作流"""
    ok = True
    client = McpClient(server)
    bot = CozeBot(client, cache)

    print("\n" + "=" * 60)
    print("  模拟 MCP 服务与 Coze 调用 —— Self Test")
    print("=" * 60)

    # Test 1: initialize 生命周期握手
    print("\n--- Test 1: MCP initialize 握手 ---")
    try:
        result = client.initialize()
        assert result["protocolVersion"] == MCP_PROTOCOL_VERSION, "协议版本不符"
        assert "tools" in result["capabilities"] and "resources" in result["capabilities"]
        assert client.initialized, "initialized 通知应已发送"
        print(f"  [通过] protocolVersion={result['protocolVersion']} "
              f"server={result['serverInfo']['name']}")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 2: tools/list 工具清单（JSON Schema 声明）
    print("\n--- Test 2: tools/list 工具清单 ---")
    try:
        tools = client.list_tools()
        tool = tools[0]
        assert tool["name"] == "search_knowledge"
        assert tool["inputSchema"]["type"] == "object"
        assert "query" in tool["inputSchema"]["properties"]
        print(f"  [通过] 工具 {tool['name']}（{len(tools)} 个），inputSchema 合法")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 3: tools/call 工具调用（真实 embedding 检索）
    print("\n--- Test 3: tools/call search_knowledge ---")
    try:
        result = client.call_tool("search_knowledge",
                                  {"query": "RoPE 和正弦位置编码有什么区别？"})
        assert not result.get("isError"), result["content"][0]["text"]
        text = result["content"][0]["text"]
        assert len(text) > 20, "应命中知识分块"
        print(f"  [通过] 命中内容（前 80 字）: {text[:80]}")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 4: Coze 工作流两轮对话（真实 LLM + 跨轮记忆）
    print("\n--- Test 4: Coze 工作流两轮对话 ---")
    sid = str(uuid.uuid4())
    try:
        r1 = bot.chat(sid, "什么是位置编码？用一句话回答。")
        r2 = bot.chat(sid, "位置编码和RoPE有什么不同？")
        assert r1 and r2, "两轮都应有回复"
        assert "（系统繁忙" not in r2, f"LLM 调用失败: {r2}"
        print(f"  第 1 轮: {r1[:60]}...")
        print(f"  第 2 轮: {r2[:60]}...")
        print("  [通过] 同一 session 两轮对话，第二轮 RoPE 语义承接第一轮")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 5: resources 原语读取会话历史
    print("\n--- Test 5: resources 读取会话历史 ---")
    try:
        resources = client.list_resources()
        assert any(r["uri"] == f"session://{sid}/history" for r in resources)
        content = client.read_resource(f"session://{sid}/history")
        msgs = json.loads(content["contents"][0]["text"])
        roles = [m["role"] for m in msgs]
        assert roles == ["user", "assistant", "user", "assistant"], f"历史顺序异常: {roles}"
        print(f"  [通过] resources/read 返回 {len(msgs)} 条历史，角色顺序 {roles}")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 6: JSON-RPC 标准错误码
    print("\n--- Test 6: JSON-RPC 错误码 ---")
    try:
        # -32601 Method not found
        req = json.dumps({"jsonrpc": "2.0", "id": 99, "method": "tools/unknown"})
        assert json.loads(server.handle(req))["error"]["code"] == -32601
        # -32602 Invalid params（非法 resource URI）
        req = json.dumps({"jsonrpc": "2.0", "id": 100, "method": "resources/read",
                          "params": {"uri": "bad://x"}})
        assert json.loads(server.handle(req))["error"]["code"] == -32602
        # -32700 Parse error（非法 JSON）
        assert json.loads(server.handle("not-json"))["error"]["code"] == -32700
        print("  [通过] -32601 / -32602 / -32700 三种错误码全部正确")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    return ok


def main():
    """入口：跑 self-test 并按结果退出"""
    print("MCP 服务器最小实现（2025-06-18 规范）+ Coze Bot 编排模拟")
    ok = run_self_test()
    print("\n" + "=" * 60)
    print("  全部 6 项 self-test 通过" if ok else "  存在失败项")
    print("=" * 60)
    print("\n手动调用示例：")
    print("  client = McpClient(server)")
    print("  client.initialize()")
    print('  print(client.call_tool("search_knowledge", {"query": "RoPE 是什么"}))')
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
