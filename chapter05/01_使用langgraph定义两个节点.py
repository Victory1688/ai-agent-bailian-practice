# 第5章 LangGraph智能体编排与任务流管理
# 第5章1节：使用LangGraph定义两个节点
# LangGraph核心概念：节点（Node）与边（Edge）

# 原写法：class State(dict): pass（无字段注解的 dict 子类）
# 原写法的问题：本篇实测 langgraph 1.2.11 下代码"跑得通但结果错误"——
#   graph.invoke() 返回 None 而不是预期的状态字典。原因：
#   LangGraph 1.x 靠 State 类的类型注解（__annotations__）来构建状态 schema，
#   裸 dict 子类没有任何字段注解，图无法收集状态，invoke 只能返回 None。
#   这是比 06/07 篇更隐蔽的"静默失败"：不报错、不崩溃，只是结果不对。
# 原写法代码（注释保留）：
# from langgraph.graph import StateGraph, END
# from langgraph.graph.state import CompiledStateGraph
#
# class State(dict):
#     pass
#
# def search_node(state: State):
#     query = state.get("query", "")
#     return {"retrieved": f"检索到与 {query} 相关的信息"}
#
# def generate_node(state: State):
#     info = state.get("retrieved", "")
#     return {"answer": f"基于{info}生成最终答案"}
#
# builder = StateGraph(State)
# builder.add_node("search", search_node)
# builder.add_node("generate", generate_node)
# builder.add_edge("search", "generate")
# builder.set_entry_point("search")
# builder.set_finish_point("generate")
#
# graph: CompiledStateGraph = builder.compile()
# result = graph.invoke({"query": "LangGraph"})
# print(result)

# 改写：State 改用 TypedDict（带字段类型注解）——这是 LangGraph 1.x 的标准 State 定义方式。
#   其余代码（两个节点函数、图的构建、entry/finish 设置、invoke 调用）与原版逐行一致，
#   实测在 langgraph 1.2.11 下可正常运行。
# 本篇没有大模型调用——节点是普通 Python 函数（"检索"/"生成"都是字符串拼接），
#   教学目标是先把"图"这个骨架建起来：节点=函数，边=顺序，状态=流转的字典。
from typing import TypedDict

from langgraph.graph import StateGraph, END
from langgraph.graph.state import CompiledStateGraph

# 定义一个简单的状态结构（改写：TypedDict + 字段注解）
# 三个字段对应三段数据：用户查询 -> 检索结果 -> 最终答案
class State(TypedDict):
    query: str
    retrieved: str
    answer: str

# 定义节点逻辑（原样保留：节点就是"接收整个状态、返回部分更新"的函数）
def search_node(state: State):
    query = state.get("query", "")
    return {"retrieved": f"检索到与 {query} 相关的信息"}

def generate_node(state: State):
    info = state.get("retrieved", "")
    return {"answer": f"基于{info}生成最终答案"}

# 构建图（原样保留）
builder = StateGraph(State)
builder.add_node("search", search_node)
builder.add_node("generate", generate_node)

# 定义流程：先执行search，再执行generate（原样保留）
# set_entry_point / set_finish_point 是旧式 API（新版推荐 add_edge(START, ...) / add_edge(..., END)），
# 但在 langgraph 1.x 中仍可用，这里保持与教材一致
builder.add_edge("search", "generate")
builder.set_entry_point("search")
builder.set_finish_point("generate")

graph: CompiledStateGraph = builder.compile()

# 执行（原样保留）
result = graph.invoke({"query": "LangGraph"})
print(result)
