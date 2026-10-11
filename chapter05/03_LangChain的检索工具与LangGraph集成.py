# ========== 示例一：LangChain的检索工具与LangGraph集成 ==========
# 教学核心：把 char04 式的"现成 LangChain 链"（RetrievalQA）作为一个节点塞进 LangGraph 图——
# 链负责"检索+生成"，图负责"编排调度"，两者组合成最小 RAG 流水线。

# 原写法：langchain 0.x 的 import 路径 + OpenAI 模型类，在当前环境无法运行，原因有四：
#   1) LangChain 1.x 路径拆分：RetrievalQA 收纳进 langchain_classic.chains，
#      FAISS 收纳进 langchain_community.vectorstores，
#      OpenAIEmbeddings 收纳进 langchain_community.embeddings
#   2) OpenAIEmbeddings 需要 OPENAI_API_KEY 且国内无法直连 OpenAI 官方服务
#   3) llm=None 是教材伪代码——RetrievalQA 的职责是"检索 + 让 LLM 基于检索结果生成答案"，
#      没有 LLM 这条链根本无法工作（run 时必然报错）
#   4) class State(dict): pass 无字段注解——langgraph 1.x 无法构建状态 schema，
#      实测 invoke 返回 None（01/02 篇同款静默失败）
# 原写法代码（注释保留）：
# from langchain.chains import RetrievalQA
# from langchain.vectorstores import FAISS
# from langchain.embeddings import OpenAIEmbeddings
# from langgraph.graph import StateGraph
#
# # 初始化LangChain的检索工具
# db = FAISS.from_texts(["LangGraph是一个任务编排框架", "LangChain是一个工具链框架"], OpenAIEmbeddings())
# retriever = db.as_retriever()
# qa_tool = RetrievalQA.from_chain_type(llm=None, retriever=retriever)
#
# # LangGraph状态
# class State(dict):
#     pass
#
# def query_node(state: State):
#     result = qa_tool.run(state["question"])
#     return {"answer": result}
#
# builder = StateGraph(State)
# builder.add_node("query", query_node)
# builder.set_entry_point("query")
#
# graph = builder.compile()
# print(graph.invoke({"question": "LangGraph是什么？"}))

# 改写（参照 01/02 篇与本系列前几章的方式）：
#   - RetrievalQA 从 langchain_classic.chains 导入，FAISS / DashScopeEmbeddings / ChatTongyi
#     从 langchain_community 导入（全部真实存在且可用）
#   - OpenAIEmbeddings 改为 DashScopeEmbeddings——百炼平台的向量化模型，
#     与聊天模型共用同一把 DASHSCOPE_API_KEY 钥匙
#   - llm=None 修复为 ChatTongyi(qwen-plus)——补上"基于检索结果生成答案"的模型环节
#   - State 改用 TypedDict（question/answer 两字段），其余代码与原版逐行一致
import os
from typing import TypedDict

from langchain_classic.chains import RetrievalQA
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_community.chat_models import ChatTongyi
from langgraph.graph import StateGraph

# 生成答案用的大模型（修复教材的 llm=None）
# 原写法：qa_tool = RetrievalQA.from_chain_type(llm=None, retriever=retriever)
llm = ChatTongyi(
    model="qwen-plus",
    dashscope_api_key=os.environ.get("DASHSCOPE_API_KEY"),
)

# 初始化LangChain的检索工具（两段知识文本原样保留；向量模型换百炼）
db = FAISS.from_texts(["LangGraph是一个任务编排框架", "LangChain是一个工具链框架"], DashScopeEmbeddings())
retriever = db.as_retriever()
qa_tool = RetrievalQA.from_chain_type(llm=llm, retriever=retriever, chain_type="stuff")

# LangGraph状态（改写：TypedDict + 字段注解，01/02 篇同款修复）
class State(TypedDict):
    question: str
    answer: str

# 图节点：调用检索链（原样保留——链对图来说就是一个普通函数）
def query_node(state: State):
    result = qa_tool.run(state["question"])
    return {"answer": result}

builder = StateGraph(State)
builder.add_node("query", query_node)
builder.set_entry_point("query")

graph = builder.compile()
print(graph.invoke({"question": "LangGraph是什么？"}))
