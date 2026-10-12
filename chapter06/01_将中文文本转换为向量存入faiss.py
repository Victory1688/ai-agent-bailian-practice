#第6章 RAG机制：检索增强智能体
# 【例6-1】 将中文文本转换为向量存入faiss
# Faiss 定位：高性能本地内存检索库
# 部署方式：本地库集成，无独立服务依赖
# 核心优势：检索速度极快，专为处理大规模向量数据优化
# 潜在局限：功能相对基础，需开发者自行管理元数据与索引
# 适用场景：追求极致性能的本地应用、AI研究原型验证


# 原写法：langchain 0.x 的 import 路径 + OpenAIEmbeddings，在当前环境无法运行，原因有二：
#   1) 0.x 路径断裂：langchain 1.x 把嵌入类拆到 langchain_community / langchain_openai，
#      FAISS 向量库拆到 langchain_community——报 ImportError（教材 import 全部失效）
#   2) OpenAIEmbeddings 默认直连 OpenAI 接口，国内环境无法访问
# 原写法代码（注释保留）：
# from langchain.embeddings import OpenAIEmbeddings
# from langchain.vectorstores import FAISS
# from langchain.docstore.document import Document

# 改写：嵌入模型换百炼 DashScopeEmbeddings（与 char05-03 同款方案——
#   向量化和对话同用一把 DASHSCOPE_API_KEY 钥匙），FAISS/Document 从 1.x 新路径导入。
# 教学点：本篇是大模型应用"检索增强"的起点——文档向量化后按语义相似度检索，
#   后续接上大模型生成，就是完整的 RAG。
import os
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')

# 构造文本列表（原样保留）
sample_texts = [
    "人工智能是研究人类智能的模拟技术",
    "大语言模型具备自然语言生成能力",
    "向量数据库实现高效相似性匹配",
    "嵌入模型用于将文本转化为向量",
    "LangChain用于构建语言模型应用"
]

# 构造文档对象（原样保留）
docs = [Document(page_content=text) for text in sample_texts]

# 初始化嵌入模型（原写法：OpenAIEmbeddings()；改写：百炼向量模型）
# text-embedding-v3 支持中文语义向量化，1024 维
embedding_model = DashScopeEmbeddings(
    model="text-embedding-v3",
    dashscope_api_key=api_key
)

# 构建FAISS向量数据库（原样保留——核心动作：5 篇文档全部向量化后建索引）
vector_store = FAISS.from_documents(docs, embedding_model)

# 查询文本（原样保留——查询文本也会被向量化，再按相似度取最近的 k=4 条）
query = "什么是向量数据库？"
results = vector_store.similarity_search(query)

# 输出结果（原样保留）
for i, r in enumerate(results):
    print(f"[匹配结果{i+1}]：{r.page_content}")


# 实测输出：
# [匹配结果1]：向量数据库实现高效相似性匹配
# [匹配结果2]：嵌入模型用于将文本转化为向量
# [匹配结果3]：LangChain用于构建语言模型应用
# [匹配结果4]：大语言模型具备自然语言生成能力
# 注意：similarity_search 默认 k=4，五条文本中"人工智能是研究人类智能的模拟技术"
#   语义距离最远未进前四；与查询"什么是向量数据库？"同属存储/检索话题的文本排在前列。
