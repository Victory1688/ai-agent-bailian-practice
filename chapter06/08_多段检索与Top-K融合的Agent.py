# 【例6-8】多段检索与Top-K融合的Agent
# 核心思想：在检索阶段放宽限制，保留多个（Top-K）与查询最相关的段落，而非仅取Top-1。
# Top-K融合：将召回的多个高相关段落整合为一个信息密度更高、维度更丰富的上下文，作为大模型的输入。
#
# 本篇与 07 篇的结构几乎同构——同样的"检索→拼 prompt→调 LLM"显式 RAG 流程，
# 唯一差异：07 篇 k=5 但没显式叫"Top-K 融合"，本篇显式命名并默认 top_k=5。
# 改写策略与 07 篇完全平行（三个问题同构处置）。

# 原写法（注释保留）：虚构框架 + 原生 requests API
# import os, json, numpy as np, faiss, requests
# from qwen_agent.agent import Agent
# from qwen_agent.context import Message
# from qwen_agent.tools import Tool
#
# EMBEDDING_API = "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding"
# def get_qwen_embedding(texts): ...  # 2025 年端点格式已变（05 篇实测）

import os
import json
import numpy as np
import faiss
import requests
from typing import List
import dashscope

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# 嵌入模型：DashScopeEmbeddings（同 05/06/07 篇，接口稳定）
from langchain_community.embeddings import DashScopeEmbeddings
_emb_model = DashScopeEmbeddings(model="text-embedding-v3", dashscope_api_key=api_key)

def get_qwen_embedding(texts: List[str]) -> List[np.ndarray]:
    """调百炼 text-embedding-v3 向量化，返回 numpy 向量列表（签名与教材原版一致）"""
    raw = _emb_model.embed_documents(texts)
    return [np.array(v, dtype=np.float32) for v in raw]

# ========= 第一步：加载政策数据（加网络兜底） =========
def fetch_policy_data() -> List[str]:
    """加载政策标题；网络失败时返回模拟数据保证演示可重复"""
    url = "https://www.stats.gov.cn/sj/tjbz/tjzszc/index.json"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers, timeout=5)
        items = response.json().get("data", [])
        docs = [item["title"] for item in items if "title" in item]
        if docs:
            return docs
    except Exception as e:
        print(f"  [网络兜底] 国家统计局 API 抓取失败: {e}")
    # 兜底：8 条模拟统计政策（覆盖 GDP/核算/普查/统计制度等）
    return [
        "国家统计局发布2025年一季度GDP数据 同比增长5.2%",
        "国家统计局关于改进地区GDP核算方法的通知 试行统一核算制度",
        "第七次全国人口普查主要数据公报 全国人口共14.1亿人",
        "国家统计局建立健全数字经济统计监测体系 定期发布统计数据",
        "关于完善固定资产投资统计制度的意见 扩大统计范围",
        "国家统计局改革研发支出核算方法 更好反映创新活动价值",
        "关于加快建立碳排放统计核算体系的实施方案 2025年全面实施",
        "国家统计局发布文化产业统计分类标准 新增数字文化相关类别",
    ]

# ========= 第二步：段落切分（原样保留——硬切 max_len，与 04/07 的贪婪拼接不同） =========
# 教材用的是 text[i:i+max_len] 硬切（按字符数均匀分段），与 04/07 的"按句号贪婪拼接"不同——
# 硬切会截断句子，但优点是每段长度一致，适合无标点的短文本
def split_chunks(texts: List[str], max_len=100) -> List[str]:
    chunks = []
    for text in texts:
        if len(text) <= max_len:
            chunks.append(text)
        else:
            chunks.extend([text[i:i + max_len] for i in range(0, len(text), max_len)])
    return chunks

# ========= 第三步：嵌入接口（改写：DashScopeEmbeddings，签名不变） =========
# 同 07 篇，原 requests API 端点 2025 年已不可用

# ========= 第四步：MultiPassageRetrievalTool（改写：去掉虚构 Tool 继承） =========
# 原写法：class MultiPassageRetrievalTool(Tool): ... super().__init__(name=..., description=...) ...
# 改写：class MultiPassageRetrievalTool: ... 去掉继承，核心检索+融合逻辑原样保留
class MultiPassageRetrievalTool:
    """多段语义检索与 Top-K 融合工具（改写：去掉虚构 Tool 继承，纯类）"""
    def __init__(self, docs: List[str], embeddings: List[np.ndarray], top_k: int = 5):
        self.docs = docs
        self.top_k = top_k
        dim = embeddings[0].shape[0]
        self.index = faiss.IndexFlatL2(dim)
        self.index.add(np.vstack(embeddings))

    def call(self, query: str) -> str:
        """核心逻辑原样保留：向量化 → FAISS 搜 top_k → 拼接多段形成融合上下文"""
        qvec = get_qwen_embedding([query])[0].reshape(1, -1)
        D, I = self.index.search(qvec, self.top_k)
        top_passages = [self.docs[i] for i in I[0]]
        # Top-K 融合策略：拼接多个片段形成更丰富上下文（本篇灵魂）
        fused_context = "\n".join(top_passages)
        return fused_context

# ========= 第五步：构建 prompt（原样保留——与 07 篇格式同构） =========
def build_prompt(query: str, context: str) -> str:
    return f"""你是一名智能问答助手，以下是从政策数据库中检索到的多段内容：
【语料片段】
{context}

请基于上述内容准确回答以下问题：
【提问】{query}
请用中文简洁清晰地作答。"""

# ========= 第六步：主流程（改写：qwen_agent.Agent → dashscope.Generation.call） =========
# 同 07 篇：检索 → 拼 prompt → 调 LLM，显式 RAG 两步

if __name__ == "__main__":
    print("正在加载政策语料数据……")
    raw_docs = fetch_policy_data()
    print(f"  原始政策标题数：{len(raw_docs)}")

    print("正在进行分段处理……")
    chunks = split_chunks(raw_docs, max_len=100)
    print(f"  分段后共 {len(chunks)} 段")

    print("开始生成嵌入向量……")
    embeddings = get_qwen_embedding(chunks)

    print("构建向量数据库……")
    tool = MultiPassageRetrievalTool(chunks, embeddings, top_k=5)

    # 用户问题
    query = "国家统计局有哪些针对GDP核算方法的文件或解释？"
    print(f"\n用户提问：{query}")

    # ====== 显式 RAG 两步流程（同 07 篇） ======
    print("  [Step 1] 多段语义检索 + Top-K 融合中……")
    retrieved = tool.call(query)

    print("  [Step 2] 组装 prompt 并生成回答……")
    prompt = build_prompt(query, retrieved)

    response = dashscope.Generation.call(
        model="qwen-plus",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=1024,
        result_format='message'
    )
    answer = response.output.choices[0].message.content

    print("\n--- Agent回答 ---")
    print(answer)
