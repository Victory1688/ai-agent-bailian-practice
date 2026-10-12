# 【例6-6】用三种向量数据库做语义检索
# 教学目标：同一份数据、同一种嵌入模型，换三种向量数据库（FAISS 内存 / Chroma 嵌入式 / Weaviate 服务端），
# 展示不同存储的部署形态与检索接口差异。
#
# 改写前的三条问题（同 05 篇结构）：
#   1) qwen_agent.Agent/Tool/Message——虚构框架（char02 已多次实战确认不存在）
#   2) get_qwen_embedding() 用原生 requests 调百炼端点——2025 年格式已变，实测 BadRequest
#   3) Weaviate——需要本地 Docker 启动服务（localhost:8080），本机没有 Docker，注释保留
# 改写策略：
#   - Agent 改 dashscope function calling（同 05 篇）
#   - 嵌入模型改 DashScopeEmbeddings（同 05 篇，函数签名保留 List[np.ndarray]）
#   - FAISS + Chroma 真实跑通（chromadb 已安装 1.5.9），Weaviate 代码原样注释保留 + 说明
#   - 三个 Tool 类改三件套（函数 + 注册表 + 说明书）

# 原写法（注释保留）：虚构框架 + 原生 requests API
# from qwen_agent.agent import Agent
# from qwen_agent.tools import Tool
# from qwen_agent.context import Message
#
# EMBEDDING_API = "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding"
# def get_qwen_embedding(texts): ...  # 2025 年端点格式已变（05 篇实测）

import os
import json
import requests
import numpy as np
from typing import List
import dashscope
import faiss

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# 嵌入模型：DashScopeEmbeddings（同 05 篇，接口稳定）
from langchain_community.embeddings import DashScopeEmbeddings
_emb_model = DashScopeEmbeddings(model="text-embedding-v3", dashscope_api_key=api_key)

def get_qwen_embedding(texts: List[str]) -> List[np.ndarray]:
    """调百炼 text-embedding-v3 向量化，返回 numpy 向量列表（签名与教材原版一致）"""
    raw = _emb_model.embed_documents(texts)
    return [np.array(v, dtype=np.float32) for v in raw]

# ========= 第一步：获取真实数据（原样保留——网络失败兜底） =========
def fetch_energy_policy_titles() -> List[str]:
    url = "https://www.nea.gov.cn/api/front/index/policynews?pageIndex=1&pageSize=20"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers, timeout=5)
        items = response.json().get("data", [])
        docs = [item["title"] for item in items if "title" in item]
        if docs:
            return docs
    except Exception as e:
        print(f"  [网络兜底] 国家能源局 API 抓取失败: {e}")
    # 兜底：6 条模拟新能源政策（保证本机演示可跑）
    return [
        "国家能源局发布2025年新能源汽车补贴政策 延续购置补贴至年底",
        "发改委印发十四五可再生能源发展规划 光伏装机量翻倍",
        "工信部推动锂电池回收利用 建立溯源管理体系",
        "电网公司加快特高压建设 提升新能源消纳能力",
        "地方政府出台氢能产业发展实施方案 2025年建成加氢站100座",
        "储能技术创新专项启动 支持钠离子电池等新型储能研发",
    ]

# ========= 第二步：FAISS 部署（原样保留——与 05 篇 build_faiss_index 完全同构） =========
class FaissSearchTool:
    """FAISS 内存检索工具（改写：去掉虚构 Tool 继承，纯类）"""
    def __init__(self, docs: List[str], embeddings: List[np.ndarray]):
        self.docs = docs
        dim = embeddings[0].shape[0]
        self.index = faiss.IndexFlatL2(dim)
        self.index.add(np.vstack(embeddings))

    def search(self, query: str) -> str:
        qvec = get_qwen_embedding([query])[0].reshape(1, -1)
        D, I = self.index.search(qvec, k=3)
        return "\n".join([self.docs[i] for i in I[0]])

# ========= 第三步：Chroma 部署（改写：适配 chromadb 1.x API） =========
# 原写法：chromadb.Client() + create_collection（旧 API）
# chromadb 1.x 改默认持久化路径；Client() 仍可用但会有弃用警告
class ChromaSearchTool:
    """Chroma 嵌入式检索工具（改写：去掉虚构 Tool 继承，纯类）"""
    def __init__(self, docs: List[str], embeddings: List[np.ndarray]):
        import chromadb
        # 用 EphemeralClient（纯内存，进程结束消失——与 FAISS 行为一致）
        self.client = chromadb.EphemeralClient()
        self.collection = self.client.create_collection(name="energy_policy")
        for i, (doc, vec) in enumerate(zip(docs, embeddings)):
            self.collection.add(
                documents=[doc],
                ids=[f"doc{i}"],
                embeddings=[vec.tolist()]
            )
        self.docs = docs

    def search(self, query: str) -> str:
        emb = get_qwen_embedding([query])[0].tolist()
        result = self.collection.query(query_embeddings=[emb], n_results=3)
        return "\n".join(result["documents"][0])

# ========= 第四步：Weaviate 部署（原样注释保留——需要 Docker 服务端） =========
# Weaviate 是服务端向量数据库，需要先启动 Docker 容器（本机没有 Docker，注释保留）
# 启动命令参考：docker run -p 8080:8080 semitechnologies/weaviate:latest
# import weaviate
# class WeaviateSearchTool:
#     def __init__(self, docs, embeddings):
#         self.client = weaviate.Client("http://localhost:8080")
#         if not self.client.schema.exists("Policy"):
#             self.client.schema.create_class({
#                 "class": "Policy",
#                 "vectorIndexType": "hnsw",
#                 "properties": [{"name": "content", "dataType": ["text"]}]
#             })
#         for i, (doc, vec) in enumerate(zip(docs, embeddings)):
#             self.client.data_object.create({"content": doc}, "Policy", vector=vec.tolist())
#     def search(self, query):
#         vec = get_qwen_embedding([query])[0].tolist()
#         result = self.client.query.get("Policy", ["content"]).with_near_vector({"vector": vec}).with_limit(3).do()
#         hits = result["data"]["Get"]["Policy"]
#         return "\n".join([hit["content"] for hit in hits])

# ========= Agent 工具注册 + 循环（改写：dashscope function calling） =========
# 三个向量库各一个检索函数，都叫 search_xxx
_faiss_tool = None
_chroma_tool = None

def search_faiss(query: str) -> str:
    return _faiss_tool.search(query) if _faiss_tool else "FAISS 未初始化"

def search_chroma(query: str) -> str:
    return _chroma_tool.search(query) if _chroma_tool else "Chroma 未初始化"

tool_registry = {"search_faiss": search_faiss, "search_chroma": search_chroma}

tools = [
    {"type": "function", "function": {
        "name": "search_faiss",
        "description": "基于 FAISS 内存向量库的能源政策语义搜索，返回最相关的3条政策标题",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "要搜索的政策关键词"}
        }, "required": ["query"]}
    }},
    {"type": "function", "function": {
        "name": "search_chroma",
        "description": "基于 Chroma 嵌入式向量库的能源政策语义搜索，返回最相关的3条政策标题",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "要搜索的政策关键词"}
        }, "required": ["query"]}
    }}
]

SYSTEM_MESSAGE = (
    "你是一位能源政策研究助手，具备两个语义搜索工具（FAISS 和 Chroma），"
    "两个工具共享同一个知识库。请根据用户的需求选择合适的工具进行搜索并回答。"
)

def agent_chat(config, user_input, memory=None):
    if memory is None:
        memory = [{"role": "system", "content": config["system_message"]}]
    memory = memory + [{"role": "user", "content": user_input}]
    while True:
        response = dashscope.Generation.call(
            model=config["model"], messages=memory, tools=tools,
            temperature=config["temperature"], max_tokens=config["max_tokens"],
            result_format='message'
        )
        message = response.output.choices[0].message
        tool_calls = getattr(message, 'tool_calls', None)
        if not tool_calls:
            memory = memory + [{"role": "assistant", "content": message.content}]
            return message.content, memory
        memory = memory + [message]
        for call in tool_calls:
            fn_name = call['function']['name']
            fn_args = json.loads(call['function'].get('arguments') or '{}')
            fn = tool_registry.get(fn_name)
            tool_result = fn(**fn_args) if fn else f"未注册的工具: {fn_name}"
            memory = memory + [{
                "role": "tool", "content": tool_result, "name": fn_name,
                "tool_call_id": call.get('id', fn_name)
            }]

# ========= 执行检索 =========
if __name__ == "__main__":
    print("获取能源政策标题中……")
    docs = fetch_energy_policy_titles()
    print(f"获取到 {len(docs)} 条政策，开始编码……")
    embeddings = get_qwen_embedding(docs)

    # 构建 FAISS + Chroma 两个向量库
    print("构建 FAISS 索引……")
    _faiss_tool = FaissSearchTool(docs, embeddings)
    print("构建 Chroma 集合……")
    _chroma_tool = ChromaSearchTool(docs, embeddings)
    print("（Weaviate 需 Docker 服务，已跳过）")

    # Agent 配置
    config = {
        "model": "qwen-plus",
        "temperature": 0.3,
        "max_tokens": 512,
        "system_message": SYSTEM_MESSAGE
    }

    query = "近期有哪些新能源相关政策？"
    print(f"\nAgent正在回答：{query}")
    reply, _ = agent_chat(config, query)

    print("\n--- Agent回答 ---")
    print(reply)
