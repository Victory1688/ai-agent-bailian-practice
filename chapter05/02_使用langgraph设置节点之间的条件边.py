# 第5章2节：使用LangGraph设置节点之间的条件边
# 条件边（Conditional Edge）：根据当前状态的值动态选择下一个节点，
# 是 LangGraph 从"固定流水线"走向"动态任务流"的关键机制。

# 原写法：class State(dict): pass（无字段注解的 dict 子类）
# 原写法的问题：与 01 篇相同——langgraph 1.x 靠 State 类的类型注解构建状态 schema，
#   裸 dict 子类无注解，实测 graph.invoke() 返回 None（静默失败：不报错但结果错误）。
#   本篇问题更典型：条件边的路由函数 lambda state: state["route"] 依赖 route 键，
#   无 schema 时这个键根本不在图的状态定义里。
# 原写法代码（注释保留）：
# from langgraph.graph import StateGraph, END
#
# class State(dict):
#     pass
#
# def check_node(state: State):
#     if "urgent" in state.get("query", "").lower():
#         return {"route": "fast"}
#     return {"route": "normal"}
#
# def fast_node(state: State):
#     return {"response": "快速处理路径已启动"}
#
# def normal_node(state: State):
#     return {"response": "普通处理路径已启动"}
#
# builder = StateGraph(State)
# builder.add_node("check", check_node)
# builder.add_node("fast", fast_node)
# builder.add_node("normal", normal_node)
#
# # 条件边：根据 route 的值选择路径
# builder.add_conditional_edges(
#     "check",
#     lambda state: state["route"],
#     {"fast": "fast", "normal": "normal"}
# )
#
# builder.set_entry_point("check")
# builder.add_edge("fast", END)
# builder.add_edge("normal", END)
#
# graph = builder.compile()
#
# print(graph.invoke({"query": "urgent request"}))
# print(graph.invoke({"query": "regular request"}))

# 改写：State 改用 TypedDict（带字段注解）——LangGraph 1.x 的标准 State 定义方式。
#   三个节点函数、条件边 API、图的构建与两次 invoke 与原版逐行一致，
#   实测在 langgraph 1.2.11 下输出与教材预期完全一致。
# 本篇依然没有大模型调用——教学目标是把"条件分支"这个图机制建起来：
#   check 节点做路由判断（写 route 键），条件边按 route 的值把流量引向 fast 或 normal。
from typing import TypedDict

from langgraph.graph import StateGraph, END

# 定义状态结构（改写：TypedDict + 字段注解）
# 三个字段：query 用户输入 / route 路由判断结果（中间变量）/ response 最终响应
class State(TypedDict):
    query: str
    route: str
    response: str

# 路由判断节点：根据 query 里是否包含 urgent，写入 route 键（原样保留）
def check_node(state: State):
    if "urgent" in state.get("query", "").lower():
        return {"route": "fast"}
    return {"route": "normal"}

# 两个业务节点（原样保留）
def fast_node(state: State):
    return {"response": "快速处理路径已启动"}

def normal_node(state: State):
    return {"response": "普通处理路径已启动"}


builder = StateGraph(State)
builder.add_node("check", check_node)
builder.add_node("fast", fast_node)
builder.add_node("normal", normal_node)

# 条件边：根据 route 的值选择路径（本篇核心，原样保留）
# 三个参数：
#   "check"                —— 条件边挂在哪个节点之后
#   lambda state: state["route"]  —— 路由函数：读状态返回一个"选择值"
#   {"fast": "fast", "normal": "normal"} —— 映射表：选择值 -> 目标节点名
builder.add_conditional_edges(
    "check",
    lambda state: state["route"],
    {"fast": "fast", "normal": "normal"}
)

builder.set_entry_point("check")
builder.add_edge("fast", END)
builder.add_edge("normal", END)

graph = builder.compile()

# 执行（原样保留：两次 invoke 分别命中两条路径）
print(graph.invoke({"query": "urgent request"}))
print(graph.invoke({"query": "regular request"}))


# 输出结果：
#{'query': 'urgent request', 'route': 'fast', 'response': '快速处理路径已启动'}
#{'query': 'regular request', 'route': 'normal', 'response': '普通处理路径已启动'}
