# 【例6-9】文本与结构化数据混合检索
# 核心挑战：多模态数据的异构性难题
#   在真实业务场景中，信息往往同时存在于非结构化文本（如行业报告、新闻资讯）
#   与结构化数据（如数据库表、业务单据）中，单一检索方式难以兼顾两类数据的召回效果。
#
# 解决方案：双通道查询与结果融合架构
#   1) 文本通道：对文档向量化 + FAISS 检索 → 解决"语义理解"需求
#   2) 数据通道：识别数值/事实性查询意图 → pandas 过滤 → 精准提取结构化数据
#   3) 结果融合：两通道结果统一拼进 prompt → LLM 生成逻辑一致的最终回答
#
# 改写前的三条问题（同 07/08 篇结构）：
#   1) qwen_agent.Agent/Tool/Message——虚构框架（char02 已多次确认不存在）
#   2) get_qwen_embedding() 用原生 requests 调百炼端点——2025 年格式已变，实测 BadRequest
#   3) fetch_fiscal_texts() / fetch_structured_data()——网络失败无兜底
# 额外发现：标题里提到"Qwen 和 DeepSeek"，但原代码 FiscalDataQueryTool.call()
#   实际是硬编码 if/elif，根本没调 DeepSeek——这是个教材假标题，改写时保持现状（因为
#   真正的 NL→SQL 需要 LLM 调工具链，会让本篇偏离"混合检索"的教学重心）。
# 改写策略：同 07/08 篇——嵌入模型改 DashScopeEmbeddings，FAISS 原生操作保留，
#   Agent 调 qwen-plus，两个 Tool 去虚构继承，数据加载加网络兜底。

# 原写法（注释保留）：虚构框架 + 原生 requests API
# from qwen_agent.agent import Agent
# from qwen_agent.context import Message
# from qwen_agent.tools import Tool
#
# EMBEDDING_API = "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding"
# def get_qwen_embedding(texts): ...  # 2025 年端点格式已变（05 篇实测）

import os
import json
import requests
import pandas as pd
import numpy as np
import faiss
from typing import List, Dict
import dashscope

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# 嵌入模型：DashScopeEmbeddings（同 05-08 篇，接口稳定）
from langchain_community.embeddings import DashScopeEmbeddings
_emb_model = DashScopeEmbeddings(model="text-embedding-v3", dashscope_api_key=api_key)

def get_qwen_embedding(texts: List[str]) -> List[np.ndarray]:
    """调百炼 text-embedding-v3 向量化，返回 numpy 向量列表（签名与教材原版一致）"""
    raw = _emb_model.embed_documents(texts)
    return [np.array(v, dtype=np.float32) for v in raw]

# ========= 第一步：加载数据（加网络兜底） =========
def fetch_fiscal_texts() -> List[str]:
    """加载财政政策文本；网络失败时返回模拟数据保证演示可重复"""
    url = "https://www.mof.gov.cn/zhengwuxinxi/caizhengxinwen/index.json"
    try:
        resp = requests.get(url, timeout=5)
        data = resp.json().get("news", [])
        docs = [item["title"] + "。" + item.get("summary", "") for item in data[:20]]
        if docs:
            return docs
    except Exception as e:
        print(f"  [网络兜底] 财政部 API 抓取失败: {e}")
    # 兜底：6 条模拟财政政策文本
    return [
        "财政部实施2020年积极的财政政策，减税降费规模超过2.5万亿元。",
        "国务院发布关于完善财政转移支付制度的意见，加大对困难地区支持力度。",
        "财政部推动地方政府专项债券发行，2024年专项债额度达3.9万亿元。",
        "完善个人所得税改革方案，提高基本减除费用标准至每月5000元。",
        "加强财政资金绩效管理，全面实施预算绩效管理办法。",
        "推进财政信息化建设，实现预算管理一体化系统全覆盖。",
    ]

def fetch_structured_data() -> pd.DataFrame:
    """加载财政结构化数据；网络失败时返回模拟数据保证演示可重复"""
    url = "https://raw.githubusercontent.com/owid/owid-datasets/master/datasets/Government%20revenue%20and%20spending/Government_revenue_and_spending.csv"
    try:
        # 先用 requests 下载（pd.read_csv 本身不支持 timeout）
        resp = requests.get(url, timeout=10)
        from io import StringIO
        df = pd.read_csv(StringIO(resp.text))
        df = df[df["Entity"] == "China"]
        df = df[["Year", "Government spending (as % of GDP)", "Government revenue (as % of GDP)"]].dropna()
        if len(df) > 0:
            return df
    except Exception as e:
        print(f"  [网络兜底] OWID CSV 抓取失败: {e}")
    # 兜底：6 行模拟中国财政年度数据
    return pd.DataFrame([
        {"Year": 2019, "Government spending (as % of GDP)": 24.4, "Government revenue (as % of GDP)": 19.1},
        {"Year": 2020, "Government spending (as % of GDP)": 25.5, "Government revenue (as % of GDP)": 18.0},
        {"Year": 2021, "Government spending (as % of GDP)": 24.0, "Government revenue (as % of GDP)": 17.7},
        {"Year": 2022, "Government spending (as % of GDP)": 23.2, "Government revenue (as % of GDP)": 16.8},
        {"Year": 2023, "Government spending (as % of GDP)": 23.1, "Government revenue (as % of GDP)": 16.7},
        {"Year": 2024, "Government spending (as % of GDP)": 23.5, "Government revenue (as % of GDP)": 16.5},
    ])

# ========= 第二步：嵌入接口（改写：DashScopeEmbeddings，签名不变） =========
# 同 07/08 篇，原 requests API 端点 2025 年已不可用

# ========= 第三步：文本通道检索工具（改写：去掉虚构 Tool 继承） =========
class FiscalTextSearchTool:
    """财政政策文本语义搜索（改写：去掉虚构 Tool 继承，纯类）"""
    def __init__(self, docs: List[str], embeddings: List[np.ndarray]):
        self.docs = docs
        dim = embeddings[0].shape[0]
        self.index = faiss.IndexFlatL2(dim)
        self.index.add(np.vstack(embeddings))

    def call(self, query: str) -> str:
        """向量化 → FAISS 搜 top-3 → 返回命中的政策文本"""
        vec = get_qwen_embedding([query])[0].reshape(1, -1)
        D, I = self.index.search(vec, k=3)
        return "\n".join([self.docs[i] for i in I[0]])

# ========= 第四步：数据通道查询工具（原样保留——硬编码关键词匹配） =========
# 原代码注释说"使用DeepSeek-V1进行自然语言转SQL（模拟）"——实际是硬编码 if/elif，
# 改写时保持原状（真正的 NL→SQL 会让本篇偏离"混合检索"的教学重心）。
# 生产用 NL→SQL 需要 LLM 调工具链，详见 char01-03 生成SQL任务建模。
class FiscalDataQueryTool:
    """财政数据结构化查询工具（改写：去掉虚构 Tool 继承，纯类；核心查询逻辑原样保留）"""
    def __init__(self, df: pd.DataFrame):
        self.df = df

    def call(self, query: str) -> str:
        """硬编码关键词匹配——简化版 NL→SQL（原样保留）"""
        if "2020" in query and "支出" in query:
            row = self.df[self.df["Year"] == 2020]
            val = row['Government spending (as % of GDP)'].values[0]
            return f"2020年中国政府支出占GDP比重为{val}%。"
        elif "收入" in query:
            year = 2021
            row = self.df[self.df["Year"] == year]
            val = row['Government revenue (as % of GDP)'].values[0]
            return f"{year}年中国政府收入占GDP比重为{val}%。"
        elif "支出" in query:
            row = self.df[self.df["Year"] == 2024]
            val = row['Government spending (as % of GDP)'].values[0]
            return f"2024年中国政府支出占GDP比重为{val}%。"
        else:
            return "未能识别查询字段，请重新表述问题。"

# ========= 第五步：组装 prompt（原样保留——双通道上下文融合） =========
def build_prompt(query: str, text_context: str, data_context: str) -> str:
    """融合文本通道 + 数据通道的检索结果，一起塞给 LLM"""
    return f"""你是一个财税智能助手，拥有文本政策知识和财政结构化数据。
【政策解读】：
{text_context}
【财政数据】：
{data_context}
请结合以上信息回答用户问题：
{query}
回答应准确、简洁、有数据支撑。"""

# ========= 第六步：主流程（改写：qwen_agent.Agent → dashscope.Generation.call） =========
if __name__ == "__main__":
    print("加载财政文本与结构化数据……")
    texts = fetch_fiscal_texts()
    df = fetch_structured_data()
    print(f"  加载完成，共 {len(texts)} 条文本，{len(df)} 行数据。")

    print("生成文本嵌入向量中……")
    text_embeddings = get_qwen_embedding(texts)

    # 初始化两个通道的工具
    text_tool = FiscalTextSearchTool(texts, text_embeddings)
    data_tool = FiscalDataQueryTool(df)

    # 用户问题（同时涉及文本政策和结构化数据）
    query = "2020年中国的财政支出是多少？相关政策有没有调整说明？"
    print(f"\n用户提问：{query}")

    # ====== 双通道混合检索 ======
    print("  [Step 1] 文本通道：语义检索相关政策……")
    text_context = text_tool.call(query)

    print("  [Step 2] 数据通道：结构化查询财政数据……")
    data_context = data_tool.call(query)

    # ====== 结果融合 + 调 LLM ======
    print("  [Step 3] 融合双通道结果，组装 prompt 并生成回答……")
    full_prompt = build_prompt(query, text_context, data_context)

    response = dashscope.Generation.call(
        model="qwen-plus",
        messages=[{"role": "user", "content": full_prompt}],
        temperature=0.3,
        max_tokens=1024,
        result_format='message'
    )
    answer = response.output.choices[0].message.content

    print("\n--- Agent回答 ---")
    print(answer)
