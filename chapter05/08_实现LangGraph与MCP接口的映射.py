# ========== 示例四：实现LangGraph与MCP接口的映射 ==========
# 本示例展示了如何将LangGraph任务流与MCP接口集成，实现任务流的动态执行与上下文管理。

# - 自定义`MCPInterface`用来**跨节点持久保存上下文**，和 LangGraph 内置 State 并行，演示外部上下文存储方案；
# - 流程：`preprocess（保存query）` → `retrieve（模拟检索，保存检索结果）` → `conclude（读取MCP上下文，生成总结）`；
# - 最后打印`mcp.context_store`，查看全部阶段保存的上下文。
#
# 【重要辨析——教材"MCP"名的诚实说明】
#   真实世界的 MCP（Model Context Protocol）是 Anthropic 提出的开放协议：
#   客户端-服务器架构、JSON-RPC 通信、工具/资源/提示三大原语，
#   与 LangGraph 的真实集成走 langchain-mcp-adapters 库（把 MCP 服务器的工具转成 LangChain 工具）。
#   教材的 MCPInterface 只是**一个内存字典存取类**——它与 MCP 协议毫无关系，
#   真正演示的概念是"节点间通过共享的外部存储交换上下文"（生产对应 Redis/数据库/文件）。
#   本篇保留教材命名（方便对照原书），但请记住：见到"自定义 MCP 类"先怀疑是不是同名陷阱。

# 原写法：class State(Dict): pass
# 原写法的问题：与 01-07 篇相同——langgraph 1.x 靠 State 类的字段注解构建状态 schema，
#   Dict 子类没有字段注解，实测 graph.invoke() 返回 None（静默失败，系列第八次）。
# 原写法代码（注释保留）：
# from langgraph.graph import StateGraph, END
# from typing import Dict
# import json
#
# class State(Dict):
#     pass

# 改写：State 改用 TypedDict（三个字段注解）。MCPInterface、三个节点、图构建、
#   invoke 与原版逐行一致（全部是纯本地代码，无大模型调用）。
from langgraph.graph import StateGraph, END
from typing import Dict, TypedDict
import json

# 定义状态结构（改写：TypedDict + 字段注解）
class State(TypedDict):
    query: str
    retrieved: str
    summary: str

# MCP接口类，用于上下文存取（原样保留——一个模块级全局对象的内存字典存取器）
class MCPInterface:
    def __init__(self):
        self.context_store = {}

    # 写入上下文
    def save_context(self, key: str, value: Dict):
        self.context_store[key] = value

    # 读取上下文
    def load_context(self, key: str) -> Dict:
        return self.context_store.get(key, {})

# 初始化MCP接口（原样保留——模块级实例，所有节点共享同一个对象）
mcp = MCPInterface()

# 节点1：接收科研问题并保存上下文（原样保留）
# 双通道设计：数据同时写进 LangGraph State（图内单次执行）和 mcp（跨执行外部存储）
def preprocess_node(state: State) -> State:
    query = state.get("query", "")
    mcp.save_context("query_ctx", {"query": query})
    return {"query": query}

# 节点2：检索外部数据并写入上下文（原样保留）
def retrieve_node(state: State) -> State:
    query = state.get("query", "")
    fake_db = {"langgraph": "LangGraph支持任务图编排", "agent": "智能体依赖协议"}
    result = fake_db.get(query.lower(), "未找到相关数据")
    mcp.save_context("retrieval_ctx", {"retrieved": result})
    return {"retrieved": result}

# 节点3：加载上下文并生成总结（原样保留）
# 教学点：本节点从 mcp 读取前两节点的存档来拼摘要——演示"从外部存储取上下文"的姿势
def conclude_node(state: State) -> State:
    query_ctx = mcp.load_context("query_ctx")
    retrieval_ctx = mcp.load_context("retrieval_ctx")
    summary = f"问题:{query_ctx.get('query')} | 检索结果:{retrieval_ctx.get('retrieved')}"
    mcp.save_context("final_ctx", {"summary": summary})
    return {"summary": summary}


# 构建任务图（原样保留）
builder = StateGraph(State)
builder.add_node("preprocess", preprocess_node)
builder.add_node("retrieve", retrieve_node)
builder.add_node("conclude", conclude_node)

builder.set_entry_point("preprocess")
builder.add_edge("preprocess", "retrieve")
builder.add_edge("retrieve", "conclude")
builder.add_edge("conclude", END)

graph = builder.compile()

# 执行任务流（原样保留）
result = graph.invoke({"query": "LangGraph"})
print(result)

# 补充验证：第二次 invoke（教材未含，用于实证"外部存储跨 invoke 持久"）
# LangGraph State 每次 invoke 都从零开始；mcp.context_store 是模块级对象——
# 第二次 invoke 后，同名 key（query_ctx/retrieval_ctx/final_ctx）被新数据覆盖，
# 键的数量不变，但内容已换成新会话的数据——这就是"外部存储与图状态"的本质差异。
result2 = graph.invoke({"query": "Agent"})
print(result2)

# 输出最终上下文存储状态（原样保留）
print(json.dumps(mcp.context_store, ensure_ascii=False, indent=2))


# 输出结果（教材预期——本篇教材预期输出实测核对完全正确）：
# 第一次 invoke：
# {'query': 'LangGraph', 'retrieved': 'LangGraph支持任务图编排', 'summary': '问题:LangGraph | 检索结果:LangGraph支持任务图编排'}
# 第二次 invoke（补充验证）：
# {'query': 'Agent', 'retrieved': '智能体依赖协议', 'summary': '问题:Agent | 检索结果:智能体依赖协议'}
# 最终 context_store（两次 invoke 后——三个键全部是第二次的数据，覆盖实证）：
# {
#   "query_ctx": { "query": "Agent" },
#   "retrieval_ctx": { "retrieved": "智能体依赖协议" },
#   "final_ctx": { "summary": "问题:Agent | 检索结果:智能体依赖协议" }
# }


#- 自定义`MCPInterface`用来**跨节点持久保存上下文**，和 LangGraph 内置 State 并行，演示外部上下文存储方案；
#- 流程：`preprocess（保存query）` → `retrieve（模拟检索，保存检索结果）` → `conclude（读取MCP上下文，生成总结）`；
#- 最后打印`mcp.context_store`，查看全部阶段保存的上下文。

#- 输出结果：
#{'query': 'LangGraph', 'retrieved': 'LangGraph支持任务图编排', 'summary': '问题:LangGraph | 检索结果:LangGraph支持任务图编排'}
#{
#  "query_ctx": {
#    "query": "LangGraph"
#  },
#  "retrieval_ctx": {
#    "retrieved": "LangGraph支持任务图编排"
#  },
#  "final_ctx": {
#    "summary": "问题:LangGraph | 检索结果:LangGraph支持任务图编排"
#  }
#}