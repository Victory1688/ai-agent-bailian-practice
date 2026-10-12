# 【例6-3】 使用LangChain开发带语义找回功能Agent
# 实现步骤（教材导语，原样保留）
#
# 01. 向量化 (Embedding)：使用预训练模型（如BERT、OpenAI Embedding）将文本转化为数值化的向量表示。
# 02. 构建索引：将所有知识库文档向量存储于向量数据库(如 FAISS, Milvus)中，并构建高效索引以加速检索。
# 03. 相似度检索：计算查询向量与库中向量的余弦相似度，进行Top-K排序，返回最相关的文档。
#
# 【标题辨析（诚实说明）】本篇标题叫"带语义找回功能Agent"，但代码里没有 Agent——
#   没有大模型调用、没有决策循环、没有工具，本质是"语义检索"（RAG 的 R）。
#   "Agent"成分要等检索结果接入大模型生成答案（后续篇）才真正出现。

# 原写法：langchain 0.x 的 import 路径 + HuggingFaceEmbeddings 本地模型，在当前环境无法运行，原因有三：
#   1) 0.x 路径断裂（同 01 篇）：embeddings/vectorstores/schema 三个路径在 1.x 全部失效
#   2) HuggingFaceEmbeddings 需要 sentence-transformers 包 + 首次运行从 HuggingFace 下载
#      模型（国内网络需配 hf-mirror 镜像），本地资源受限时不便
#   3) all-MiniLM-L6-v2 是英文向量模型（384 维）——对中文文本的语义匹配能力很弱，
#      用它检索中文知识库，排序会明显失真（模型选型必须匹配语言）
# 原写法代码（注释保留）：
# from langchain.vectorstores import FAISS
# from langchain.embeddings import HuggingFaceEmbeddings
# from langchain.schema import Document
#
# embedding_model = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")

# 改写：嵌入模型换百炼 DashScopeEmbeddings（与 01 篇同款——中文效果好、零下载、
#   与对话模型共用 DASHSCOPE_API_KEY）。本地嵌入模型的完整路线见讲解文档第七节。
# 教学点：本篇是 01 篇的同款流程（入库→检索），新增两个知识点：k 参数控制召回条数、
#   检索质量取决于"知识库文本与查询的语义距离"。
import os
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')

# 加载嵌入模型（改写：百炼向量模型）
embedding_model = DashScopeEmbeddings(
    model="text-embedding-v3",
    dashscope_api_key=api_key
)

# 准备模拟知识库（原样保留）
documents = [
    Document(page_content="LangChain是用于构建语言模型应用的开发框架"),
    Document(page_content="向量数据库支持语义搜索与高效索引管理"),
    Document(page_content="RAG机制结合检索系统与生成模型进行问答"),
    Document(page_content="OpenAI模型支持函数调用与多轮对话"),
    Document(page_content="嵌入模型用于将文本转为向量表达形式"),
]

# 构建向量数据库（原样保留）
db = FAISS.from_documents(documents, embedding_model)
# 用户查询（原样保留）
query = "什么是RAG机制？"
# 执行语义相似度召回（原样保留——k=2：只取最相似的前 2 条）
matched_docs = db.similarity_search(query, k=2)
# 输出结果（原样保留）
for idx, doc in enumerate(matched_docs):
    print(f"[Top {idx+1}] {doc.page_content}")


# 实测输出：
# [Top 1] RAG机制结合检索系统与生成模型进行问答
# [Top 2] OpenAI模型支持函数调用与多轮对话
# 观察：Top1 与查询共享"RAG机制"四字且语义同题，名至实归；
#   Top2 在候选中优势细微——"OpenAI模型支持…"与"LangChain是…""向量数据库支持…"
#   同属"AI技术能力描述"句式，语义距离接近，排序由向量的细微差异决定。
