# 【例6-5】 选择Qwen-Embedding模型做语义编码
# 文档预处理与向量化：Embedding 模型选择
# 核心任务：将非结构化文本映射为语义保持的稠密数值向量，支撑后续语义检索与匹配。
#
# 本篇的特殊性（三条路线混在一起）：
#   1) qwen_embedding_client、qwen_agent 是教材虚构的框架（真实包不存在，已在 char02 系列多次确认）
#   2) get_embeddings() 用原生 requests 调百炼嵌入 API——**这部分曾是真实的**，但 2025 年百炼嵌入 API
#      端点格式已变，原请求报 BadRequest.IllegalInput，响应结构也不是 data["output"]["embeddings"]
#      （实测验证：API 报 "The input parameter requires json format"）
#   3) faiss + numpy 原生操作——**真实且稳定**，char06 前几篇用的是 LangChain FAISS 包装，本篇露出底层
# 改写策略：保留 3) 的原生 FAISS 操作（这是本篇核心教学资产），嵌入模型用已在 01/03 篇验证可用的
#   DashScopeEmbeddings（LangChain 封装，内部调的就是百炼同一个 text-embedding-v3 模型，接口稳定），
#   虚构 import + Agent 部分按 char02-06 的 agent_chat 循环重写（dashscope function calling）。
# 本篇的"原生 vs 封装"对照：get_embeddings 改成 LangChain 封装后，build_faiss_index + search_finance
#   仍是原生 faiss——正好展示"嵌入模型可插拔、底层存储不变"的架构设计。

# 原写法（注释保留）：虚构框架 + 过时的 requests API
# import faiss, numpy as np
# from qwen_embedding_client import QwenEmbeddingClient  # 虚构
# from qwen_agent.agent import Agent, from qwen_agent.tools import Tool, from qwen_agent.context import Message  # 虚构
#
# QWEN_EMBEDDING_API = "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding"
# def get_embeddings(texts):  # 原生 requests 调 API（2025 年端点已变，实测失败）

import os
import faiss
import numpy as np
from typing import List
import json
import dashscope
from langchain_community.embeddings import DashScopeEmbeddings

# 从环境变量中获取 DASHSCOPE_API_KEY（百炼一把钥匙通吃对话+向量化）
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# ========== 抓取金融新闻（原样保留——真实网络调用，失败兜底） ==========
def fetch_finance_news() -> List[str]:
    """抓取国开证券官网新闻标题；网络失败时返回模拟数据保证演示可重复"""
    url = "https://www.kfzx.com.cn/api/newslist?page=1&pageSize=20"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        import requests
        resp = requests.get(url, headers=headers, timeout=5)
        news_items = resp.json().get("data", {}).get("rows", [])
        docs = [item["Title"] for item in news_items if "Title" in item]
        if docs:
            return docs
    except Exception as e:
        print(f"  [网络兜底] 抓取失败: {e}，使用模拟金融新闻数据")
    # 兜底：6 条模拟金融新闻（保证本机演示可跑）
    return [
        "央行宣布下调金融机构存款准备金率0.5个百分点",
        "财政部发布2025年国债发行计划 总额超3万亿元",
        "人民银行开展3000亿元MLF操作 中标利率维持不变",
        "证监会进一步规范上市公司股份回购行为 维护市场稳定",
        "银保监会加强商业银行流动性管理 防范系统性风险",
        "外汇管理局公布2025年国际收支平衡表 经常账户顺差收窄",
    ]

# ========== 嵌入编码（改写：DashScopeEmbeddings，等价于原 get_embeddings，但接口稳定） ==========
# 原写法注释保留：
# QWEN_EMBEDDING_API = "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding"
# def get_embeddings(texts: List[str]) -> List[np.ndarray]:
#     headers = {"Authorization": f"Bearer {api_key}"}
#     response = requests.post(QWEN_EMBEDDING_API, ...)
#     return [np.array(item["embedding"], dtype=np.float32) for item in data["output"]["embeddings"]]
# 实测 2025 年该端点报 BadRequest.IllegalInput（API 格式已变），改用 LangChain 封装的 DashScopeEmbeddings
# ——它内部调的就是百炼同一个 text-embedding-v3 模型，接口稳定（01/03 篇已验证）。
# 返回值改为 numpy 向量列表，保持与原 get_embeddings 的签名一致——build_faiss_index 零改动。
_emb_model = DashScopeEmbeddings(model="text-embedding-v3", dashscope_api_key=api_key)

def get_embeddings(texts: List[str]) -> List[np.ndarray]:
    """调百炼 text-embedding-v3 向量化，返回 numpy 向量列表（签名与教材原版一致）"""
    raw = _emb_model.embed_documents(texts)
    return [np.array(v, dtype=np.float32) for v in raw]

# ========== 构建 FAISS 索引：原生 faiss + numpy（原样保留——本篇核心教学资产） ==========
# 与 char06-01 FAISS.from_documents 的区别：本篇手动调 emb_fn + 手动 build index——
#   LangChain 封装只是把这两步藏进了 from_documents；本篇露出底层，展示"封装底下到底在干什么"
def build_faiss_index(embeddings: List[np.ndarray]) -> faiss.IndexFlatL2:
    dim = embeddings[0].shape[0]
    index = faiss.IndexFlatL2(dim)
    matrix = np.vstack(embeddings)
    index.add(matrix)
    return index

# ========== 语义检索函数（原 FinanceSearchTool.call 的核心逻辑，剥离类外壳） ==========
def search_finance(query: str, index: faiss.IndexFlatL2, docs: List[str]) -> str:
    """把查询向量化 → FAISS 搜 top-3 → 返回命中的新闻标题"""
    try:
        emb = get_embeddings([query])[0].reshape(1, -1)
        D, I = index.search(emb, k=3)
        hits = [docs[i] for i in I[0]]
        return "\n".join(hits)
    except Exception as e:
        return f"检索失败：{str(e)}"

# ========== Agent 工具注册（原 FinanceSearchTool 改写为三件套） ==========
tool_registry = {"search_finance": None}  # 占位，在 main 里注入 index/docs

tools = [
    {"type": "function", "function": {
        "name": "search_finance",
        "description": "从金融新闻库中检索与查询相关的新闻标题，返回最相关的3条",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "要检索的关键词或问题，如'货币政策'"}
        }, "required": ["query"]}
    }}
]

SYSTEM_MESSAGE = "你是一位金融资讯助手，能检索金融新闻库并回答用户关于市场动态、货币政策等方面的问题。"

# ========== Agent 循环（原 qwen_agent.Agent 的 chat() 方法——框架虚构，改写为手写循环） ==========
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

# ========== 主流程（原 __main__ 改写） ==========
if __name__ == "__main__":
    print("正在抓取金融新闻数据……")
    docs = fetch_finance_news()
    print(f"已获取新闻 {len(docs)} 条，正在进行文本嵌入……")
    embeddings = get_embeddings(docs)
    print("构建向量数据库中……")
    index = build_faiss_index(embeddings)

    # 注入检索函数（闭包捕获 index 和 docs）
    tool_registry["search_finance"] = lambda query: search_finance(query, index, docs)

    # Agent 配置
    config = {
        "model": "qwen-plus",
        "temperature": 0.3,
        "max_tokens": 512,
        "system_message": SYSTEM_MESSAGE
    }

    user_msg = "最近有哪些关于货币政策的消息？"
    print("Agent正在生成回答……")
    reply, _ = agent_chat(config, user_msg)

    print("\n--- Agent回答 ---")
    print(reply)
