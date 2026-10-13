# 第13章 项目案例：从零实现一个复合智能体系统
# 【例13-5】RAG 检索问答子系统
#
# ★ 教材简化 vs 生产级改写
#
# 教材原版问题（已注释保留）：
#   ① 标题又写"Qwen3.0"，代码是 Qwen/Qwen1.5-7B-Chat —— 标题内容不符（同前几篇）
#   ② Qwen2Chat / DeepSeekChat 虚构类 + 一揽子过时 import：
#      - from langchain.document_loaders / langchain.embeddings —— 路径已迁移
#      - ConversationalRetrievalChain / ConversationBufferMemory —— LangChain
#        官方已废弃（0.3+），推荐 LangGraph / LCEL 重写
#      - vectorstore.persist() —— 新版 Chroma 已移除该方法（自动持久化）
#   ③ data/ai_knowledge.txt 凭空出现 —— 文件不存在直接崩（char12-04 同款）
#   ④ HuggingFaceEmbeddings 需下载约 90MB 本地模型 + sentence-transformers
#      重依赖，离线/弱网环境不可用
#   ⑤ 每次 ask() 都重建 ConversationalRetrievalChain —— 重复构造坑
#      （同 13-01/13-03：装配一次，全程复用）
#   ⑥ 错误处理：失败时把 "[ERROR] ..." 字符串当回答返回 —— 调用方无法
#      区分"回答"与"故障"，且 str(e) 可能携带内部细节
#   ⑦ 多轮记忆依赖已废弃的 ConversationBufferMemory
#   ⑧ 无 self-test
#
# 本次改写（轻量 RAG 三段流水线，char12-04 已验证模式）：
#   ① 知识库内置（覆盖教材三个问题的 AI 知识文本），不再依赖外部文件
#   ② EmbeddingClient：dashscope text-embedding-v3 替代本地 HuggingFace
#      模型；向量落盘 cache.json（md5 键），重复运行零二次计费——
#      并提供 api_calls 计数器，让"缓存生效"可被 self-test 证明
#   ③ KnowledgeBase：段落切分（超长滑窗兜底，保留教材切分语义）+
#      纯 Python 余弦相似度 top-k 检索（替代 Chroma，概念一致）
#   ④ RAGAgent：检索 → 增强 → 生成三段流水线；对话历史 self.history
#      注入 messages 实现多轮记忆（替代废弃的 ConversationBufferMemory）；
#      主备模型回退（延续 13-03/13-04 模式）；ask 返回结构化契约
#      {"success", "answer", "sources"}——错误不再混入回答文本
#   ⑤ self-test 5 项：检索命中 / 向量缓存复用（api_calls==0 实测）/
#      真实 RAG 问答 / 多轮指代 / 主备回退实测

# ============================================================
# 原代码（注释保留——教材简化版，废弃 Chain + 缺失文件 + 错误混流）
# ============================================================
# # 【例13-5】
# # -*- coding:utf-8 -*-
# # RAG检索子系统实现：向量检索+模型生成
# # 支持文档自动嵌入，向量数据库构建，用户问题向量检索与大模型生成问答，
# # 集成Qwen3.0与DeepSeek，并支持检索日志输出与模型动态切换。
#
# import os
# import uuid
# import traceback
# from langchain.chains import ConversationalRetrievalChain        # ← 已废弃
# from langchain.vectorstores import Chroma
# from langchain.document_loaders import TextLoader                # ← 路径已迁移
# from langchain.text_splitter import CharacterTextSplitter
# from langchain.embeddings import HuggingFaceEmbeddings           # ← 路径已迁移
# from langchain.memory import ConversationBufferMemory            # ← 已废弃
# from langchain_community.chat_models import Qwen2Chat, DeepSeekChat  # ← 虚构类
# from langchain.schema import HumanMessage                        # ← 路径过时
#
# # 一、准备向量存储（文档→嵌入→Chroma）
# def build_vectorstore_from_file(file_path: str, persist_dir="./chroma_rag"):
#     loader = TextLoader(file_path, encoding='utf-8')   # ← data/ai_knowledge.txt 不存在
#     docs = loader.load()
#     splitter = CharacterTextSplitter(chunk_size=500, chunk_overlap=50)
#     split_docs = splitter.split_documents(docs)
#     embedding_model = HuggingFaceEmbeddings(           # ← 下载 90MB 本地模型
#         model_name="sentence-transformers/all-MiniLM-L6-v2")
#     vectorstore = Chroma.from_documents(split_docs, embedding=embedding_model,
#                                         persist_directory=persist_dir)
#     vectorstore.persist()                              # ← 新版 Chroma 已移除
#     return vectorstore
#
# # 二、构建RAG问答系统
# class RAGAgent:
#     def __init__(self, vectorstore, model_type="qwen"):
#         self.vectorstore = vectorstore
#         self.model_type = model_type
#         self.model = self._load_model()
#         self.memory = ConversationBufferMemory(return_messages=True)  # ← 已废弃
#
#     def _load_model(self):
#         if self.model_type == "qwen":
#             return Qwen2Chat(model="Qwen/Qwen1.5-7B-Chat")             # ← 虚构
#         else:
#             return DeepSeekChat(model="deepseek-ai/deepseek-llm-chat")
#
#     def ask(self, query: str):
#         try:
#             chain = ConversationalRetrievalChain.from_llm(   # ← 每次 ask 重建
#                 llm=self.model,
#                 retriever=self.vectorstore.as_retriever(search_kwargs={"k": 2}),
#                 memory=self.memory)
#             result = chain.run(query)
#             return result
#         except Exception as e:
#             return f"[ERROR] 回答失败：{str(e)}"   # ← 错误混进回答，调用方无法区分
#
# # 三、测试运行：准备数据并调用RAG系统
# def run_demo():
#     print(">>> 正在构建向量知识库...")
#     vectorstore = build_vectorstore_from_file("data/ai_knowledge.txt")
#     print(">>> 初始化RAG智能体")
#     agent = RAGAgent(vectorstore, model_type="qwen")
#     queries = [
#         "请简要介绍什么是人工智能？",
#         "人工智能和机器学习有什么区别？",
#         "深度学习属于人工智能吗？",
#     ]
#     for i, q in enumerate(queries):
#         print(f"\n问题{i+1}：{q}")
#         reply = agent.ask(q)
#         print("回答：", reply)
#
# run_demo()
# ============================================================

import os
import sys
import json
import math
import uuid
import hashlib
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
EMBEDDING_MODEL = "text-embedding-v3"   # dashscope 语义向量模型（1024 维）
EMBED_BATCH = 10                        # 嵌入 API 单批上限（超批需分批调用）
MAX_TOKENS = 256
TOP_K = 2                               # 检索返回最相关的 2 个片段（教材 k=2）

# 模型注册表：主备槽位（延续 13-03/13-04 模式）
# 注：实测当前百炼账号未开通 DeepSeek 托管，备用槽位用 qwen-turbo 演示
MODEL_REGISTRY = {
    "primary": {"model": "qwen-plus"},
    "backup": {"model": "qwen-turbo"},
}

# 内置知识库文本（替代教材缺失的 data/ai_knowledge.txt，
# 覆盖教材三个问题的知识范围）
KNOWLEDGE_TEXT = """人工智能（Artificial Intelligence，AI）是让机器模拟人类智能行为的技术领域，涵盖感知、推理、学习与决策等能力，其目标是让机器完成通常需要人类智能才能完成的任务。
机器学习（Machine Learning）是实现人工智能的核心方法之一，它让计算机从数据中自动学习规律，而无需人为编写显式规则，常见的范式包括监督学习、无监督学习与强化学习。
深度学习（Deep Learning）是机器学习的一个重要分支，它通过多层神经网络自动提取特征，在图像识别、语音识别与自然语言处理等任务中表现突出。
Transformer 是现代大语言模型的基础架构，其核心是自注意力机制（Self-Attention），允许序列中每个位置直接关注所有其他位置，从而高效建模长距离依赖。
智能体（Agent）是能够感知环境、进行决策并采取行动以达成目标的智能系统，大模型智能体通常具备记忆、规划与工具调用等能力。
检索增强生成（RAG）将知识检索与大模型生成相结合：先从知识库中检索与问题相关的片段，再让模型基于片段生成回答，能显著降低幻觉并让回答可溯源。"""

RAG_PROMPT_TEMPLATE = (
    "请根据以下检索到的知识片段回答用户问题。"
    "如果片段中没有足够信息，请如实说明。\n\n"
    "知识片段：\n{context}\n\n用户问题：{query}"
)


# ============================================================
# 组件 1：JSONCache —— 向量落盘缓存（cache.json，重复运行零二次计费）
# ============================================================

class JSONCache:
    """基于 cache.json 的键值缓存，存放文本 md5 → 语义向量"""

    def __init__(self, path: str = CACHE_FILE):
        """加载（或初始化）缓存文件

        参数: path — 缓存文件路径（默认运行目录 cache.json）
        """
        self.path = path
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                self._data = json.load(f)
        else:
            self._data = {}

    def get(self, key: str):
        return self._data.get(key)

    def set(self, key: str, value):
        self._data[key] = value
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)


# ============================================================
# 组件 2：EmbeddingClient —— dashscope 嵌入（带缓存与调用计数）
# ============================================================

class EmbeddingClient:
    """文本嵌入客户端：先查缓存，未命中才调 API（api_calls 计数供测试验证）"""

    def __init__(self, cache: JSONCache):
        """初始化嵌入客户端

        参数: cache — JSONCache 实例（向量落盘复用）
        """
        self.cache = cache
        self.api_calls = 0   # 实际调用嵌入 API 的批次数（self-test 验证缓存用）

    @staticmethod
    def _key(text: str) -> str:
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    def embed(self, texts: list) -> list:
        """批量嵌入：缓存命中直接返回，未命中分批调 API 并落盘

        参数: texts — 文本列表
        返回: 与输入顺序对齐的向量列表（每个 1024 维）
        异常: RuntimeError — 嵌入接口非 200
        """
        result = [None] * len(texts)
        misses = []   # [(索引, 文本)] 缓存未命中的条目
        for i, t in enumerate(texts):
            cached = self.cache.get(self._key(t))
            if cached is not None:
                result[i] = cached
            else:
                misses.append((i, t))
        # 分批调用（每批不超过 EMBED_BATCH），按批回填并写缓存
        for start in range(0, len(misses), EMBED_BATCH):
            batch = misses[start:start + EMBED_BATCH]
            resp = dashscope.TextEmbedding.call(
                model=EMBEDDING_MODEL, input=[t for _, t in batch], dimension=1024)
            if resp.status_code != 200:
                raise RuntimeError(f"{resp.code} {resp.message}")
            self.api_calls += 1
            for (idx, t), item in zip(batch, resp.output["embeddings"]):
                vec = item["embedding"]
                result[idx] = vec
                self.cache.set(self._key(t), vec)
        return result

    @staticmethod
    def cosine(a: list, b: list) -> float:
        """余弦相似度（纯 Python 实现，替代向量库的相似度算子）"""
        dot = sum(x * y for x, y in zip(a, b))
        norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
        return dot / norm if norm else 0.0


# ============================================================
# 组件 3：KnowledgeBase —— 分块 + 向量化 + top-k 检索（替代 Chroma）
# ============================================================

def split_text(text: str, chunk_size: int = 200, overlap: int = 20) -> list:
    """文本分块：按段落切，超长段落滑窗兜底（保留教材切分语义）

    教材 CharacterTextSplitter(chunk_size=500, overlap=50) 针对外部长文件；
    内置知识库段落较短，按段落分即可，超长段落才滑窗——概念一致、粒度更细

    参数: text — 原始文本; chunk_size — 块上限字符数; overlap — 滑窗重叠字符数
    返回: 文本块列表
    """
    chunks = []
    for para in [p.strip() for p in text.split("\n") if p.strip()]:
        if len(para) <= chunk_size:
            chunks.append(para)
            continue
        step = chunk_size - overlap
        for i in range(0, len(para), step):
            part = para[i:i + chunk_size].strip()
            if part:
                chunks.append(part)
            if i + chunk_size >= len(para):
                break
    return chunks


class KnowledgeBase:
    """向量知识库：构建时向量化全部块，检索时余弦相似度 top-k"""

    def __init__(self, text: str, embedder: EmbeddingClient,
                 chunk_size: int = 200):
        """构建知识库（分块 → 嵌入 → 就绪）

        参数: text — 知识库原始文本; embedder — 嵌入客户端;
              chunk_size — 分块上限字符数
        """
        self.chunks = split_text(text, chunk_size=chunk_size)
        self.embedder = embedder
        self.vectors = embedder.embed(self.chunks)
        logger.info(f"[知识库] {len(self.chunks)} 个片段已向量化")

    def search(self, query: str, k: int = TOP_K) -> list:
        """检索最相关的 k 个片段（教材 as_retriever(k=2) 语义保留）

        参数: query — 用户问题; k — 返回片段数
        返回: 按相似度降序的片段文本列表
        """
        q_vec = self.embedder.embed([query])[0]
        scored = [(self.embedder.cosine(q_vec, v), chunk)
                  for chunk, v in zip(self.chunks, self.vectors)]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [chunk for _, chunk in scored[:k]]


# ============================================================
# 组件 4：RAGAgent —— 检索增强问答（多轮记忆 + 主备回退 + 结构化返回）
# ============================================================

class RAGAgent:
    """RAG 问答子系统：检索知识片段 → 拼装增强提示词 → 模型生成回答

    装配一次全程复用（修复教材每次 ask 重建 chain）；
    ask 返回结构化契约（修复教材错误字符串混流）
    """

    def __init__(self, knowledge_base: KnowledgeBase):
        """初始化 RAG 智能体

        参数: knowledge_base — 已构建的向量知识库
        """
        self.kb = knowledge_base
        self.session_id = str(uuid.uuid4())
        self.history: list = []          # 对话历史（替代 ConversationBufferMemory）
        self.attempted_slots: list = []  # 最近一次回答尝试的模型槽位

    def _invoke(self, model_name: str, messages: list) -> str:
        """单模型调用（dashscope 原生协议）

        参数: model_name — 模型名; messages — 原生格式消息列表
        返回: 模型回复文本
        异常: RuntimeError — 接口非 200（由上层触发回退）
        """
        resp = dashscope.Generation.call(
            model=model_name, messages=messages,
            max_tokens=MAX_TOKENS, result_format="message")
        if resp.status_code != 200:
            raise RuntimeError(f"{resp.code} {resp.message}")
        return resp.output.choices[0].message.content.strip()

    def ask(self, query: str) -> dict:
        """回答用户问题（检索 → 增强 → 生成，永不抛异常）

        参数: query — 用户问题
        返回: 成功 {"success": True, "answer", "sources"}；
              失败 {"success": False, "answer": "", "sources": [], "error"}
        """
        try:
            sources = self.kb.search(query)
            context = "\n".join(f"- {s}" for s in sources)
            prompt = (RAG_PROMPT_TEMPLATE
                      .replace("{context}", context)
                      .replace("{query}", query))
            # 对话历史注入（多轮记忆），当前问题追加在末尾
            messages = self.history + [{"role": "user", "content": prompt}]
            answer = None
            for slot in ("primary", "backup"):
                self.attempted_slots.append(slot)
                try:
                    logger.info(f"[模型] 使用 {slot}({MODEL_REGISTRY[slot]['model']}) 生成回答")
                    answer = self._invoke(MODEL_REGISTRY[slot]["model"], messages)
                    break
                except Exception as e:
                    logger.warning(f"[回退] {slot} 模型级失败: {e}")
            if answer is None:
                raise RuntimeError("所有模型均执行失败")
            self.history.append({"role": "user", "content": prompt})
            self.history.append({"role": "assistant", "content": answer})
            return {"success": True, "answer": answer, "sources": sources}
        except Exception as e:
            logger.error(f"[RAG] 回答失败: {e}")
            # 结构化错误：success 标志让调用方可程序化判断，错误不再混进回答
            return {"success": False, "answer": "", "sources": [], "error": str(e)}


# ============================================================
# self-test（5 项）
# ============================================================

def run_self_test() -> bool:
    """验证检索命中 / 向量缓存复用 / 真实 RAG 问答 / 多轮指代 / 主备回退"""
    ok = True

    print("\n" + "=" * 60)
    print("  char13-05 RAG 检索问答子系统 —— Self Test")
    print("=" * 60)

    cache = JSONCache()
    embedder = EmbeddingClient(cache)

    # Test 1: 分块 + 检索命中
    print("\n--- Test 1: 知识库构建与检索命中 ---")
    try:
        kb = KnowledgeBase(KNOWLEDGE_TEXT, embedder)
        assert len(kb.chunks) >= 5, f"分块数异常: {len(kb.chunks)}"
        hits = kb.search("什么是Transformer架构？")
        assert hits and "Transformer" in hits[0], hits
        print(f"  [通过] {len(kb.chunks)} 个片段，top-1 命中: {hits[0][:40]}...")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 2: 向量缓存复用（重建知识库，api_calls 应为 0）
    print("\n--- Test 2: 向量缓存复用（二次构建零计费）---")
    try:
        embedder2 = EmbeddingClient(cache)
        kb2 = KnowledgeBase(KNOWLEDGE_TEXT, embedder2)
        assert embedder2.api_calls == 0, f"缓存未生效，仍有 {embedder2.api_calls} 次 API 调用"
        hits2 = kb2.search("什么是Transformer架构？")
        assert hits2 and "Transformer" in hits2[0], hits2
        print("  [通过] 二次构建 api_calls == 0，检索结果与首次一致——cache.json 生效")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 3: 真实 RAG 问答（教材问题 1）
    print("\n--- Test 3: 真实 RAG 问答（qwen-plus）---")
    try:
        agent = RAGAgent(kb)
        result = agent.ask("请简要介绍什么是人工智能？")
        assert result["success"] is True, result
        assert result["answer"] and result["sources"], result
        assert len(result["sources"]) == TOP_K, result["sources"]
        print(f"  [通过] 回答: {result['answer'][:50]}...（引用 {len(result['sources'])} 个片段）")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 4: 多轮对话记忆（"它"指代验证，char12-04/13-01 同款方法）
    print("\n--- Test 4: 多轮对话记忆 ---")
    try:
        r1 = agent.ask("深度学习属于人工智能吗？")
        assert r1["success"], r1
        r2 = agent.ask("那它和机器学习是什么关系？")
        assert r2["success"] and r2["answer"], r2
        assert "机器学习" in r2["answer"], f"指代未接上: {r2['answer']}"
        print(f"  [通过] 第二轮回答（'它'指代深度学习）: {r2['answer'][:50]}...")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 5: 主备回退实测（注入坏模型名）
    print("\n--- Test 5: 模型级回退（primary 注入坏模型名）---")
    try:
        old = MODEL_REGISTRY["primary"]["model"]
        MODEL_REGISTRY["primary"]["model"] = "nonexistent-model-for-test"
        try:
            agent.attempted_slots = []
            result = agent.ask("什么是检索增强生成？")
        finally:
            MODEL_REGISTRY["primary"]["model"] = old   # 无论成败都还原注册表
        assert agent.attempted_slots == ["primary", "backup"], agent.attempted_slots
        assert result["success"] and "RAG" in result["answer"] or "检索" in result["answer"], result
        print(f"  [通过] 主模型失败 → 备用接管: {result['answer'][:40]}...")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    return ok


def run_demo():
    """手动体验入口：教材同款 3 个问题逐条问答"""
    print(">>> 正在构建向量知识库...")
    kb = KnowledgeBase(KNOWLEDGE_TEXT, EmbeddingClient(JSONCache()))
    print(">>> 初始化 RAG 智能体")
    agent = RAGAgent(kb)
    queries = [
        "请简要介绍什么是人工智能？",
        "人工智能和机器学习有什么区别？",
        "深度学习属于人工智能吗？",
    ]
    for i, q in enumerate(queries):
        print(f"\n问题{i + 1}：{q}")
        result = agent.ask(q)
        if result["success"]:
            print("回答：", result["answer"])
            print("引用片段：", [s[:30] + "..." for s in result["sources"]])
        else:
            print("[失败]", result["error"])


def main():
    """入口：跑 self-test；--demo 进入手动体验"""
    ok = run_self_test()
    print("\n" + "=" * 60)
    print("  全部 5 项 self-test 通过" if ok else "  存在失败项")
    print("=" * 60)
    if "--demo" in sys.argv:
        run_demo()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
