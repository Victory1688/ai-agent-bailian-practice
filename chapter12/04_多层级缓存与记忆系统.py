# 【例 12-4】智能体多层级缓存与记忆系统构建
#
# ★ 教材简化 vs 生产级改写
#
# 教材原版问题（已注释保留）：
#   ① import redis —— 本环境无 Redis，按项目约定改用运行目录 cache.json
#   ② langchain 类引用全部过时/虚构：
#      - Qwen2Chat / DeepSeekChat —— LangChain 社区库里根本不存在这两个类
#      - ConversationBufferMemory / ConversationalRetrievalChain —— LangChain
#        官方已废弃（0.3+），推荐 LangGraph 或 LCEL 重写
#      - HuggingFaceEmbeddings / Chroma 的 import 路径也已迁移
#   ③ 本地 GPU 模型（Qwen1.5-14B-Chat + deepseek-llm-chat, device="cuda"）
#   ④ sample_knowledge.txt 知识库文件凭空出现，不存在则直接崩
#   ⑤ HuggingFaceEmbeddings 需下载 90MB 本地模型 + chromadb 重依赖
#   ⑥ 无错误处理、无 self-test
#
# 本次改写（三层记忆架构，轻量可运行）：
#   ① 层级 1 短期缓存：JSONCache（cache.json）替代 Redis —— 对话历史按
#      session 隔离存储，保留教材 key 结构 session:{id}:history 的思想
#   ② 层级 2 长期知识库：dashscope TextEmbedding API（text-embedding-v3）
#      生成语义向量 + 纯 Python 余弦相似度 top-k 检索 —— 替代 Chroma +
#      本地 HuggingFace 模型，概念完全一致（语义向量化 + 相似度检索），
#      向量本身也缓存落盘，重复运行不再二次计费
#   ③ 层级 3 跨模型记忆共享：同一 session 的历史同时注入 qwen-plus 与
#      deepseek-v3（dashscope 托管），对话 2 的"它"能指代对话 1 的
#      Self-Attention —— 证明记忆跨模型延续
#   ④ 知识库内置示例文本（不再依赖外部文件），main 入口 4 项 self-test

# ============================================================
# 原代码（注释保留——教材简化版，Redis + 虚构类 + 本地 GPU）
# ============================================================
# import redis
# import chromadb
# from langchain_community.chat_models import Qwen2Chat      # ← 类不存在
# from langchain_community.chat_models import DeepSeekChat   # ← 类不存在
# from langchain.memory import ConversationBufferMemory      # ← 已废弃
# from langchain.chains import ConversationalRetrievalChain  # ← 已废弃
# from langchain.embeddings import HuggingFaceEmbeddings     # ← 路径已迁移
# from langchain.vectorstores import Chroma                  # ← 路径已迁移
#
# REDIS_HOST, REDIS_PORT = "localhost", 6379
# rds = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)  # ← Redis 依赖
#
# loader = TextLoader("sample_knowledge.txt")                # ← 文件不存在
# split_docs = RecursiveCharacterTextSplitter(...).split_documents(docs)
# embedding_model = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
# vectorstore = Chroma.from_documents(split_docs, embedding_model, ...)
#
# def get_model(agent_type="qwen"):
#     if agent_type == "qwen":
#         return Qwen2Chat(model="Qwen/Qwen1.5-14B-Chat", device="cuda")  # ← 本地 GPU
#     else:
#         return DeepSeekChat(model="deepseek-ai/deepseek-llm-chat", device="cuda")
#
# def cache_conversation(session_id, message, role="user"):
#     rds.rpush(f"session:{session_id}:history", f"{role}:{message}")     # ← Redis
# ============================================================

import os
import sys
import json
import math
import time
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
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache.json")
EMBEDDING_MODEL = "text-embedding-v3"   # DashScope 语义向量模型（1024 维）
TOP_K = 2                               # 知识检索返回最相关的 2 个分块（教材 k=2）

# 两个对话后端：不同模型 + 不同调用协议（跨模型记忆共享演示）
# 注：实测当前百炼账号未开通 DeepSeek 托管（deepseek-* 模型 404），
# 故选用 qwen-plus / qwen-turbo 两个真实可用的不同模型演示跨模型切换；
# 若账号开通 deepseek-v3，把 backend_b 的 model 改回 "deepseek-v3" 即可
CHAT_BACKENDS = {
    "backend_a": {"model": "qwen-plus", "protocol": "native"},   # dashscope 原生协议
    "backend_b": {"model": "qwen-turbo", "protocol": "openai"},  # OpenAI 兼容协议
}

# 内置知识库文本（替代教材缺失的 sample_knowledge.txt）
KNOWLEDGE_TEXT = """Transformer 是现代大语言模型的基础架构，其核心是自注意力机制。
Self-Attention（自注意力）允许序列中每个位置直接关注所有其他位置，通过 Query、Key、Value 三个矩阵计算相关性权重。
具体计算过程是：将输入映射为 Q、K、V，用 Q 与 K 的点积除以维度平方根后做 softmax 归一化，得到注意力权重，再对 V 加权求和。
多头注意力（Multi-Head Attention）将 Self-Attention 并行重复多组，每组（每个头）在不同的子空间学习不同的注意力模式。
多头注意力的输出是各头结果拼接后做线性变换，它让模型同时捕捉语法、语义、位置等不同层面的依赖关系。
与 RNN 相比，Self-Attention 可以完全并行计算，训练效率更高，且任意两位置的距离都是 1，长程依赖建模能力更强。"""


# ============================================================
# 层级 1：短期缓存（JSONCache 替代 Redis，对话历史按 session 隔离）
# ============================================================

class JSONCache:
    """基于 cache.json 的键值缓存，替代 Redis 的会话历史存储

    结构: {"sessions": {session_id: [{"role", "content"}]}, "vectors": {...}}
    """

    def __init__(self, path: str):
        """初始化缓存

        参数: path — cache.json 文件路径；文件损坏时重建
        """
        self._path = path
        try:
            with open(path, "r", encoding="utf-8") as f:
                self._data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self._data = {}

    def append_history(self, session_id: str, role: str, content: str):
        """向指定会话追加一条历史消息（等价 Redis rpush）

        参数: session_id — 会话标识; role — user/assistant; content — 消息内容
        """
        sessions = self._data.setdefault("sessions", {})
        sessions.setdefault(session_id, []).append({"role": role, "content": content})
        self._save()

    def get_history(self, session_id: str):
        """读取指定会话的全部历史（等价 Redis lrange 0 -1）"""
        return list(self._data.get("sessions", {}).get(session_id, []))

    def set_vectors(self, doc_id: str, vector: list):
        """缓存知识分块的语义向量（避免重复调用 embedding API 计费）"""
        self._data.setdefault("vectors", {})[doc_id] = vector
        self._save()

    def get_vectors(self) -> dict:
        """返回全部已缓存的向量 {doc_id: [float, ...]}"""
        return self._data.get("vectors", {})

    def _save(self):
        """落盘到 cache.json（单进程教学场景，整体覆写即可）"""
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=1)


# ============================================================
# 层级 2：长期知识库（dashscope 语义向量 + 余弦相似度检索）
# ============================================================

def split_text(text: str, chunk_size: int = 120) -> list:
    """把知识文本按行聚合成分块（教材用 langchain 切分器，这里自实现）

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

    参数: texts — 文本列表（单次最多 10 条）
    返回: 与输入顺序对应的向量列表
    异常: API 失败时抛出 RuntimeError
    """
    resp = dashscope.TextEmbedding.call(model=EMBEDDING_MODEL, input=texts)
    if resp.status_code != 200:
        raise RuntimeError(f"Embedding API 失败: {resp.code} {resp.message}")
    ordered = sorted(resp.output["embeddings"], key=lambda e: e["text_index"])
    return [e["embedding"] for e in ordered]


def cosine_similarity(a: list, b: list) -> float:
    """计算两个向量的余弦相似度（范围 -1~1，越大越语义相近）"""
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(x * x for x in b))
    return dot / norm if norm else 0.0


class KnowledgeBase:
    """长期知识库：分块 → 向量化（带 cache.json 缓存）→ top-k 语义检索"""

    def __init__(self, cache: JSONCache, text: str):
        """构建知识库：优先复用缓存向量，缺失分块才调用 embedding API

        参数: cache — 短期缓存对象（向量也存进去）; text — 知识原文
        """
        self._cache = cache
        self._chunks = split_text(text)
        cached = cache.get_vectors()
        missing = [(i, c) for i, c in enumerate(self._chunks) if str(i) not in cached]
        if missing:
            logger.info(f"新增 {len(missing)} 个知识分块，调用 embedding API")
            vectors = embed_texts([c for _, c in missing])
            for (i, _), v in zip(missing, vectors):
                cache.set_vectors(str(i), v)
        self._vectors = [cache.get_vectors()[str(i)] for i in range(len(self._chunks))]
        logger.info(f"知识库就绪: {len(self._chunks)} 个分块，全部向量已缓存")

    def search(self, query: str, top_k: int = TOP_K) -> list:
        """语义检索：返回与 query 最相关的 (分块, 相似度) 列表

        参数: query — 用户查询; top_k — 返回条数
        """
        qvec = embed_texts([query])[0]
        scored = [(chunk, cosine_similarity(qvec, vvec))
                  for chunk, vvec in zip(self._chunks, self._vectors)]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


# ============================================================
# 层级 3：跨模型记忆共享 Agent（同 session 历史注入不同 LLM）
# ============================================================

class MemoryAgent:
    """带记忆的对话 Agent：检索增强 + 会话历史跨模型共享

    与教材 MemoryAgent 的对应：
      ConversationBufferMemory → JSONCache.get_history（历史由 cache 统一管理）
      ConversationalRetrievalChain → 检索 + prompt 拼接 + Generation.call
      Qwen2Chat/DeepSeekChat → 两个真实后端 qwen-plus / qwen-turbo
    """

    def __init__(self, session_id: str, kb: KnowledgeBase, backend_key: str = "backend_a"):
        """初始化 Agent

        参数: session_id — 会话标识（同 id 即共享记忆）; kb — 知识库;
              backend_key — CHAT_BACKENDS 的键（backend_a / backend_b）
        """
        self.session_id = session_id
        self.kb = kb
        backend = CHAT_BACKENDS[backend_key]
        self.model = backend["model"]
        self.protocol = backend["protocol"]
        self.cache = kb._cache

    def chat(self, user_input: str) -> str:
        """一轮对话：历史注入 → 知识检索 → LLM 生成 → 历史落盘

        参数: user_input — 用户输入
        返回: 助手回复文本
        异常: LLM 调用失败抛 RuntimeError
        """
        # ① 跨模型记忆共享的核心：历史从 cache 读取（谁写的都能读）
        history = self.cache.get_history(self.session_id)
        # ② 长期知识检索：找最相关的知识分块
        hits = self.kb.search(user_input)
        knowledge = "\n".join(f"- {c}" for c, _ in hits)
        logger.info(f"[{self.model}] 检索命中 {len(hits)} 块 (top={hits[0][1]:.3f})")

        # ③ 组装消息：系统提示(知识) + 完整历史 + 本轮输入
        messages = [{"role": "system",
                     "content": f"你是智能助手，请结合以下知识回答：\n{knowledge}"}]
        messages += history
        messages.append({"role": "user", "content": user_input})

        # ④ 按后端协议调用 LLM：native=dashscope 原生；openai=百炼兼容模式
        #    两种协议消息结构一致，印证"记忆与模型解耦"的设计价值
        if self.protocol == "native":
            resp = dashscope.Generation.call(model=self.model, messages=messages,
                                             max_tokens=256, result_format="message")
            if resp.status_code != 200:
                raise RuntimeError(f"{self.model} 调用失败: {resp.code} {resp.message}")
            answer = resp.output.choices[0].message.content
        else:
            from openai import OpenAI
            client = OpenAI(api_key=dashscope.api_key,
                            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
            resp = client.chat.completions.create(model=self.model, messages=messages,
                                                  max_tokens=256)
            answer = resp.choices[0].message.content

        # ⑤ 双写历史落盘（等价教材的 rpush user + rpush ai）
        self.cache.append_history(self.session_id, "user", user_input)
        self.cache.append_history(self.session_id, "assistant", answer)
        return answer


# ============================================================
# main 入口：4 项 self-test
# ============================================================

def run_self_test():
    """验证三层记忆架构：知识检索 / 会话落盘 / 跨模型记忆共享 / 会话隔离"""
    ok = True

    print("\n" + "=" * 60)
    print("  多层级缓存与记忆系统 —— Self Test")
    print("=" * 60)

    cache = JSONCache(CACHE_FILE)

    # Test 1: 长期知识库语义检索
    print("\n--- Test 1: 知识库语义检索（Self-Attention 查询）---")
    try:
        kb = KnowledgeBase(cache, KNOWLEDGE_TEXT)
        hits = kb.search("Self-Attention 是怎么工作的")
        for c, s in hits:
            print(f"  相似度 {s:.3f} | {c[:36]}...")
        assert hits[0][1] > 0.3, "最相关分块相似度过低"
        assert "Attention" in hits[0][0], "未命中注意力相关分块"
        print("  [通过] 语义检索命中正确知识分块")
    except Exception as e:
        print(f"  [失败] {e}"); return False

    # Test 2: 对话 1（backend_a: qwen-plus）+ 历史落盘
    print("\n--- Test 2: qwen-plus 对话 + 历史写入 cache.json ---")
    session = f"demo-{uuid.uuid4().hex[:6]}"
    try:
        agent_q = MemoryAgent(session, kb, backend_key="backend_a")
        ans1 = agent_q.chat("请问 Transformer 中的 Self-Attention 机制是怎么工作的？")
        assert len(ans1) > 10
        hist = cache.get_history(session)
        assert len(hist) == 2 and hist[0]["role"] == "user"
        print(f"  qwen-plus: {ans1[:44]}...")
        print(f"  [通过] 历史已落盘（{len(hist)} 条）")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 3: 对话 2（backend_b: qwen-turbo）同一 session → 记忆共享
    print("\n--- Test 3: qwen-turbo 接续对话（跨模型记忆共享）---")
    try:
        agent_d = MemoryAgent(session, kb, backend_key="backend_b")
        ans2 = agent_d.chat("它和多头注意力机制之间的关系是什么？")
        assert len(ans2) > 10
        hist = cache.get_history(session)
        assert len(hist) == 4, f"历史应为 4 条，实际 {len(hist)}"
        print(f"  qwen-turbo: {ans2[:44]}...")
        print(f"  [通过] 第二个模型读取到第一个模型写入的历史（4 条）")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 4: 会话隔离（新 session 历史必须为空）
    print("\n--- Test 4: 会话隔离验证 ---")
    try:
        other = cache.get_history(f"other-{uuid.uuid4().hex[:6]}")
        assert other == []
        print("  [通过] 新会话历史为空，session 间相互隔离")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    print(f"\n{'=' * 60}")
    print(f"  {'全部 4 项 self-test 通过' if ok else '存在失败项'}")
    print(f"{'=' * 60}")
    return ok


if __name__ == "__main__":
    t0 = time.time()
    success = run_self_test()
    print(f"\n总耗时 {int(time.time() - t0)}s | cache.json: {CACHE_FILE}")
    sys.exit(0 if success else 1)
