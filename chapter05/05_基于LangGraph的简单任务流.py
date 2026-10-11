# ========== 基于 LangGraph 的简单任务流 ==========
# 教学核心：01 篇的两节点图扩展为完整的四节点业务流水线——
# 预处理 → 检索 → 摘要 → 结论，每个节点"读上游的键、写自己的键"，
# 数据在共享状态里逐级传递，形成一条看得见的任务流水线。

# 原写法：from typing import Dict + class State(Dict): pass
# 原写法的问题：与 01-04 篇相同——langgraph 1.x 靠 State 类的字段注解构建状态 schema，
#   Dict 子类依然没有字段注解，实测 graph.invoke() 返回 None（静默失败，系列第五次）。
# 原写法代码（注释保留）：
# from langgraph.graph import StateGraph, END
# from typing import Dict
#
# class State(Dict):
#     pass

# 改写：State 改用 TypedDict（带字段注解）——langgraph 1.x 的标准 State 定义方式。
#   四个节点函数、图的构建、invoke 调用与原版逐行一致（本篇无大模型调用，纯本地模拟）。
from langgraph.graph import StateGraph, END
from typing import TypedDict

# 定义状态结构，存储任务执行过程中的上下文（改写：TypedDict + 五个字段注解）
# 五个字段对应流水线的五个产出：原始输入 → 标准化文本 → 检索结果 → 摘要 → 结论
class State(TypedDict):
    query: str
    standardized: str
    retrieved: str
    summary: str
    conclusion: str

# 定义第一个节点：接收用户输入并标准化问题（原样保留）
# 教学点：本节点同时改写了已有的 query 键（strip 后的值覆盖原值）并新增 standardized 键
def preprocess_node(state: State) -> State:
    query = state.get("query", "").strip()
    # 添加标准化逻辑
    standardized = query.lower().replace("?", "")
    return {"query": query, "standardized": standardized}

# 定义第二个节点：检索文献（这里用简单的字典数据库代替真实检索，原样保留）
def retrieve_node(state: State) -> State:
    database = {
        "langgraph": "LangGraph是一种任务图编排框架，擅长复杂流程管理",
        "agent": "智能体系统依赖任务调度与状态管理实现高效运行"
    }
    keyword = state.get("standardized", "")
    # 注意：字典 get 是精确匹配——标准化后的文本必须恰好等于某个 key 才能命中
    result = database.get(keyword, "未找到相关文献")
    return {"retrieved": result}

# 定义第三个节点：摘要生成（原样保留）
# 教学点：本地模拟版摘要 = 截断 20 字符 + 省略号（真实场景换成 LLM 生成）
def summarize_node(state: State) -> State:
    content = state.get("retrieved", "")
    if content == "未找到相关文献":
        summary = "暂无可用信息"
    else:
        summary = content[:20] + "..."
    return {"summary": summary}

# 定义第四个节点：结论生成（原样保留）
def conclude_node(state: State) -> State:
    summary = state.get("summary", "")
    if summary == "暂无可用信息":
        conclusion = "当前问题未能得到支持性资料"
    else:
        conclusion = f"基于文献摘要可得: {summary}"
    return {"conclusion": conclusion}

# 构建任务图（原样保留）
builder = StateGraph(State)
builder.add_node("preprocess", preprocess_node)
builder.add_node("retrieve", retrieve_node)
builder.add_node("summarize", summarize_node)
builder.add_node("conclude", conclude_node)

# 设置节点间的执行路径（原样保留：单线四节点流水线，无条件边）
builder.set_entry_point("preprocess")
builder.add_edge("preprocess", "retrieve")
builder.add_edge("retrieve", "summarize")
builder.add_edge("summarize", "conclude")
builder.add_edge("conclude", END)

# 编译任务流（原样保留）
graph = builder.compile()

# 执行示例任务（原样保留）
result = graph.invoke({"query": "LangGraph?"})
print(result)


# 输出结果（教材预期，注意 summary 的截断长度是教材手写估计）：
# {
#    'query': 'LangGraph?',
#    'standardized': 'langgraph',
#    'retrieved': 'LangGraph是一种任务图编排框架，擅长复杂流程管理',
#    'summary': 'LangGraph是一种任务图编排框...',
#    'conclusion': '基于文献摘要可得: LangGraph是一种任务图编排框...'
# }
#
# 实测输出（content[:20] 按字符截断：LangGraph=9字符 + "是一种任务图编排框架"=10字符，
# 第20个字符是"，"）：
# {'query': 'LangGraph?', 'standardized': 'langgraph',
#  'retrieved': 'LangGraph是一种任务图编排框架，擅长复杂流程管理',
#  'summary': 'LangGraph是一种任务图编排框架，...',
#  'conclusion': '基于文献摘要可得: LangGraph是一种任务图编排框架，...'}
