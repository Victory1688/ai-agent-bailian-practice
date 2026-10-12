# 【例6-7】实现一个RetrievalQA问答系统

#核心定义：Retrieval-Augmented Question Answering (检索增强问答) —— 结合外部知识库检索与大模型生成，解决大模型幻觉问题的关键技术。
#技术价值：解决幻觉与提升精度通过引入外部实时的、私有的、专业的知识库，大幅提高AI Agent在企业内部知识库、法律条款解读、医疗问诊等特定垂直领域的回答准确性与专业度，确保回答有据可依。
#


# 教学目标：把 char06 前六篇的零件串成完整 RAG 闭环——法律文档 → 切片 → 向量化 → FAISS 索引 → 手动检索 → 拼 prompt → 调 LLM 生成回答。
#
# 本篇的独特设计（与 05/06 篇的关键差异）：
#   05/06 篇用 Agent function calling（模型自主决定调工具），
#   但本篇第六步是**手动调用工具 + 手动拼 prompt + 手动调 Agent**——
#   这是 RAG 最原始、最显式的形态：开发者写死"先检索、再把检索结果塞进 prompt、再调 LLM"。
#   这个设计值得保留作为教学点，让新人看到 function calling 底下到底藏了什么。
#
# 改写前的三条问题（同 05/06 篇结构）：
#   1) qwen_agent.Agent/Tool/Message——虚构框架（char02 已多次实战确认不存在）
#   2) get_qwen_embedding() 用原生 requests 调百炼端点——2025 年格式已变，实测 BadRequest
#   3) fetch_law_sections() 用真实 API——网络失败无兜底
# 改写策略：
#   - 嵌入模型改 DashScopeEmbeddings（同 05/06 篇，接口稳定）
#   - FAISS 原生操作保留（LawRetrievalTool 的核心检索逻辑）
#   - 第六步"手动检索 + 手动拼 prompt + 手动调 Agent"的显式流程保留为教学点
#   - Agent 调 qwen-plus（dashscope.Generation.call），prompt 格式原样保留
#   - 法律数据加网络兜底返回模拟条文

# 原写法（注释保留）：虚构框架 + 原生 requests API
# from qwen_agent.agent import Agent
# from qwen_agent.tools import Tool
# from qwen_agent.context import Message
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

# 嵌入模型：DashScopeEmbeddings（同 05/06 篇，接口稳定）
from langchain_community.embeddings import DashScopeEmbeddings
_emb_model = DashScopeEmbeddings(model="text-embedding-v3", dashscope_api_key=api_key)

def get_qwen_embedding(texts: List[str]) -> List[np.ndarray]:
    """调百炼 text-embedding-v3 向量化，返回 numpy 向量列表（签名与教材原版一致）"""
    raw = _emb_model.embed_documents(texts)
    return [np.array(v, dtype=np.float32) for v in raw]

# ========= 第一步：加载法律文档（加网络兜底） =========
def fetch_law_sections() -> List[str]:
    """加载法律条文；网络失败时返回模拟条文保证演示可重复"""
    url = "https://www.lawxp.com/data/fake/law/ep_law.json"
    try:
        response = requests.get(url, timeout=5)
        data = response.json()
        docs = [item["content"] for item in data if "content" in item]
        if docs:
            return docs
    except Exception as e:
        print(f"  [网络兜底] 法律数据 API 抓取失败: {e}")
    # 兜底：6 条模拟法律条文（保证本机演示可跑，覆盖环境保护/刑法/劳动法等）
    return [
        "《中华人民共和国环境保护法》第四十五条规定：排放污染物的企业事业单位和其他生产经营者，应当采取有效措施，防治在生产建设或者其他活动中产生的废气、废水、废渣、粉尘、恶臭气体、放射性物质以及噪声、振动、光辐射、电磁辐射等对环境的污染和危害。",
        "《中华人民共和国环境保护法》第六十三条规定：企业事业单位和其他生产经营者有下列行为之一，尚不构成犯罪的，除依照有关法律法规规定予以处罚外，由县级以上人民政府环境保护主管部门或者其他有关部门将案件移送公安机关，对其直接负责的主管人员和其他直接责任人员，处十日以上十五日以下拘留；情节较轻的，处五日以上十日以下拘留。",
        "《中华人民共和国刑法》第三百三十八条规定：违反国家规定，排放、倾倒或者处置有放射性的废物、含传染病病原体的废物、有毒物质或者其他有害物质，严重污染环境的，处三年以下有期徒刑或者拘役，并处或者单处罚金；后果特别严重的，处三年以上七年以下有期徒刑，并处罚金。",
        "《中华人民共和国劳动法》第三十六条规定：国家实行劳动者每日工作时间不超过八小时、平均每周工作时间不超过四十四小时的工时制度。",
        "《中华人民共和国劳动合同法》第十条规定：建立劳动关系，应当订立书面劳动合同。已建立劳动关系，未同时订立书面劳动合同的，应当自用工之日起一个月内订立书面劳动合同。",
        "《中华人民共和国消费者权益保护法》第八条规定：消费者享有知悉其购买、使用的商品或者接受的服务的真实情况的权利。",
    ]

# ========= 第二步：段落切分（原样保留——按句号贪婪拼接，与 04 篇 generate_chunks 同构） =========
def split_text_into_chunks(texts: List[str], max_length=150) -> List[str]:
    chunks = []
    for text in texts:
        parts = text.split("。")
        chunk = ""
        for p in parts:
            if len(chunk) + len(p) < max_length:
                chunk += p + "。"
            else:
                chunks.append(chunk)
                chunk = p + "。"
        if chunk:
            chunks.append(chunk)
    return chunks

# ========= 第三步：Qwen 嵌入接口（改写：DashScopeEmbeddings，签名不变） =========
# 原写法注释保留：
# EMBEDDING_API = "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding"
# API_KEY = os.getenv("DASHSCOPE_API_KEY")
# def get_qwen_embedding(texts: List[str]) -> List[np.ndarray]:
#     payload = {"model": "text-embedding-v1", "input": texts}
#     headers = {"Authorization": f"Bearer {API_KEY}"}
#     resp = requests.post(EMBEDDING_API, headers=headers, json=payload)
#     results = resp.json()["output"]["embeddings"]
#     return [np.array(r["embedding"], dtype=np.float32) for r in results]
# 实测 2025 年该端点报 BadRequest.IllegalInput（API 格式已变），已改用 DashScopeEmbeddings（同 05/06 篇）

# ========= 第四步：构建向量索引（原 LawRetrievalTool 改写——去掉虚构 Tool 继承） =========
# 原写法：class LawRetrievalTool(Tool): ... super().__init__(name=..., description=...) ...
# 改写：class LawRetrievalTool: ... 去掉继承，核心检索逻辑原样保留
class LawRetrievalTool:
    """法律文本语义检索工具（改写：去掉虚构 Tool 继承，纯类）"""
    def __init__(self, chunks: List[str], embeddings: List[np.ndarray]):
        self.chunks = chunks
        dim = embeddings[0].shape[0]
        self.index = faiss.IndexFlatL2(dim)
        self.index.add(np.vstack(embeddings))

    def call(self, query: str) -> str:
        """核心检索逻辑原样保留：向量化 → FAISS 搜 top-5 → 返回命中的条文片段"""
        q_vec = get_qwen_embedding([query])[0].reshape(1, -1)
        D, I = self.index.search(q_vec, k=5)
        retrieved = [self.chunks[i] for i in I[0]]
        return "\n".join(retrieved)

# ========= 第五步：组装 RetrievalQA 上下文（原样保留——这是 RAG 的"G"的核心） =========
def build_prompt_with_context(query: str, context: str) -> str:
    """把检索到的条文塞进 prompt，引导 LLM 基于上下文回答而非凭空编"""
    prompt = f"""你是一名法律智能助手。请根据以下法律条文内容回答用户问题。
【法律条文】：
{context}
【用户提问】：
{query}
请结合条文内容给出明确、简洁、准确的回答。"""
    return prompt

# ========= 第六步：主流程（原样保留——手动检索 + 手动拼 prompt + 手动调 Agent） =========
# 这是本篇最值得保留的设计——比 05/06 篇的 function calling 更显式地展示 RAG 的两步流程：
#   Step 1: retrieval_tool.call(question) → 先检索
#   Step 2: build_prompt_with_context(question, context) → 把检索结果塞进 prompt
#   Step 3: dashscope.Generation.call(...) → 调 LLM 生成回答
# function calling 只是把这三步交给模型自主决策（05/06 篇），但底层逻辑是一样的。
# 改写：原 qwen_agent.Agent().chat(Message(...)) → dashscope.Generation.call

if __name__ == "__main__":
    print("正在加载法律数据……")
    raw_sections = fetch_law_sections()
    print(f"  原始条文数量：{len(raw_sections)}")

    print("正在切分文本为片段……")
    chunks = split_text_into_chunks(raw_sections, max_length=150)
    print(f"  切分后片段数：{len(chunks)}")

    print("正在进行文本嵌入……")
    embeddings = get_qwen_embedding(chunks)

    # 初始化检索工具（核心组件）
    retrieval_tool = LawRetrievalTool(chunks, embeddings)

    # 模拟用户提问
    question = "环境保护法中对企业排污行为有什么规定？"
    print(f"\n用户提问：{question}")

    # ====== RAG 两步核心流程（显式展示，教学重点） ======
    # 第一步：先调用工具进行语义检索（RAG 的 "R"）
    print("  [Step 1] 语义检索中……")
    context = retrieval_tool.call(question)

    # 第二步：拼接上下文并发送给 LLM 生成回答（RAG 的 "G"）
    print("  [Step 2] 组装 prompt 并生成回答……")
    final_prompt = build_prompt_with_context(question, context)

    # 调 dashscope（原 qwen_agent.Agent().chat() 改写）
    response = dashscope.Generation.call(
        model="qwen-plus",
        messages=[{"role": "user", "content": final_prompt}],
        temperature=0.3,
        max_tokens=1024,
        result_format='message'
    )
    answer = response.output.choices[0].message.content

    # 输出结果
    print("\n--- Agent回答 ---")
    print(answer)
