# ========== 示例二：LangChain函数调用工具与LangGraph集成 ==========
# 核心思想：**LangChain 负责各类工具、RAG、LLM 封装；LangGraph 负责编排节点、控制执行流程**。

# 原写法：import 路径断裂 + 两处教材自带 bug（实测确认），在当前环境无法运行：
#   1) from langchain.tools import tool —— LangChain 1.x 中 @tool 收纳进 langchain_core.tools
#   2) 教材的 multiply 函数没有 docstring —— @tool 装饰器实测直接抛
#      ValueError: "Function must have a docstring if description not provided"
#      （docstring 就是工具说明书 description，没有它模型不知道这工具干嘛的）
#   3) calc_node 里 multiply(a=state["x"], b=state["y"]) —— 实测抛
#      TypeError: "'StructuredTool' object is not callable"
#      （@tool 返回的是 StructuredTool 工具对象，不是函数本身，
#       调用它的标准方式是 .invoke(参数字典)）
#   4) class State(dict): pass 无字段注解 —— langgraph 1.x 静默失败（01-03 篇同款，系列第四次）
# 原写法代码（注释保留）：
# from langchain.tools import tool
# from langgraph.graph import StateGraph
#
# # 定义LangChain工具
# @tool
# def multiply(a: int, b: int) -> int:
#     return a * b
#
# # LangGraph状态
# class State(dict):
#     pass
#
# def calc_node(state: State):
#     result = multiply(a=state["x"], b=state["y"])
#     return {"product": result}
#
# builder = StateGraph(State)
# builder.add_node("calc", calc_node)
# builder.set_entry_point("calc")
#
# graph = builder.compile()
# print(graph.invoke({"x": 7, "y": 8}))

# 改写（参照 01-03 篇与本系列前几章的方式）：
#   - @tool 从 langchain_core.tools 导入
#   - multiply 补上 docstring（这就是工具说明书，呼应 char03-06 的 Function Calling 三件套：
#     类型注解=参数 schema，docstring=description，函数体=执行逻辑——一个装饰器全搞定）
#   - calc_node 改用工具对象的标准调用方式 .invoke(参数字典)
#   - State 改用 TypedDict（x/y/product 三字段），图构建与 invoke 与原版逐行一致
# 说明：本篇标题里的"函数调用"指把 LangChain 工具函数接入图节点，
#   本篇的 multiply 是被节点"手动调用"的（没有大模型参与决策）——
#   真正的"模型自主决定调不调工具"（Function Calling 循环）见 char02 系列与 char05 后续篇章。
from typing import TypedDict

from langchain_core.tools import tool
from langgraph.graph import StateGraph

# 定义LangChain工具（补上教材缺失的 docstring）
@tool
def multiply(a: int, b: int) -> int:
    """计算两个整数的乘积"""
    return a * b

# LangGraph状态（改写：TypedDict + 字段注解，01-03 篇同款修复）
class State(TypedDict):
    x: int
    y: int
    product: int

def calc_node(state: State):
    # 原写法：result = multiply(a=state["x"], b=state["y"])
    #         实测 TypeError: 'StructuredTool' object is not callable
    # 改写：工具对象的标准调用方式是 .invoke(参数字典)——参数名与函数签名一致
    result = multiply.invoke({"a": state["x"], "b": state["y"]})
    return {"product": result}

builder = StateGraph(State)
builder.add_node("calc", calc_node)
builder.set_entry_point("calc")

graph = builder.compile()
print(graph.invoke({"x": 7, "y": 8}))
