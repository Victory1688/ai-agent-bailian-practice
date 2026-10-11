# ========== 示例三：科研助手多步骤任务实现 ==========
# 整个科研助手链路一共**5 个节点串行执行**：
# `预处理(提取关键词)` → `文献检索` → `文献去重筛选` → `生成摘要` → `汇总结论`
# 所有节点共享同一个`State`状态，每个节点输出的字段都会保留在上下文中。

# 原写法：from typing import Dict, List + class State(Dict): pass
# 原写法的问题：与 01-05 篇相同——langgraph 1.x 靠 State 类的字段注解构建状态 schema，
#   Dict 子类没有字段注解，实测 graph.invoke() 返回 None（静默失败，系列第六次）。
#   教材 import 的 List 本该用在状态注解上（keywords/retrieved_docs 等都是列表字段）。
# 原写法代码（注释保留）：
# from langgraph.graph import StateGraph, END
# from typing import Dict, List
#
# class State(Dict):
#     pass

# 另一处教材自带 bug（conclude_node 的降级链断裂，实测确认）：
#   故障路径下 filter_node 产出失败信号 "有效文献不足"（6 个字符，不足 15 字不截断），
#   summarize_node 仍会给它拼上省略号 → summaries 里是 "有效文献不足..."；
#   而 conclude_node 用精确匹配 `if "有效文献不足" in summaries` 判断——
#   列表里是带省略号的版本，精确匹配永远失败 → 走 else 分支，
#   最终输出 "基于现有文献分析：有效文献不足..."——**失败被当成正常分析结果输出**。
# 原写法（注释保留）：
#   if "暂无摘要" in summaries or "有效文献不足" in summaries:
#       conclusion = "未能生成可靠的科研结论"
#   else:
#       conclusion = "基于现有文献分析：" + " | ".join(summaries)
# 修复：改用子串匹配（any + in 字符串包含判断），失败信号无论是否被加工过都能识别。

# 改写：State 改用 TypedDict（六个字段，教材 import 的 List 正好派上用场）。
#   五个节点（除 conclude 的 bug 修复外）、图构建、invoke 与原版逐行一致。
from langgraph.graph import StateGraph, END
from typing import List, TypedDict

# 定义状态，存储任务执行过程中的上下文（改写：TypedDict + 六个字段注解）
class State(TypedDict):
    query: str
    keywords: List[str]
    retrieved_docs: List[str]
    filtered_docs: List[str]
    summaries: List[str]
    conclusion: str

# 节点1：问题预处理，进行关键词抽取（原样保留）
# 教学点：按空格分词 + 只保留长度大于 3 的词 + 统一小写
def preprocess_node(state: State) -> State:
    query = state.get("query", "").strip()
    # 简单关键词提取逻辑
    keywords = [word.lower() for word in query.split() if len(word) > 3]
    return {"query": query, "keywords": keywords}

# 节点2：文献检索，数据库检索（原样保留——字典模拟版，每命中一个关键词带回一批文献）
def retrieve_node(state: State) -> State:
    database = {
        "graph": ["LangGraph用于任务编排", "图式化逻辑提升多Agent协作效率"],
        "agent": ["智能体体系依赖状态追踪", "多任务分解是关键挑战"]
    }
    results = []
    for kw in state.get("keywords", []):
        results.extend(database.get(kw, []))
    return {"retrieved_docs": results if results else ["未找到相关文献"]}

# 节点3：文献筛选，过滤掉无效或重复信息（原样保留）
# 教学点：集合推导式去重——注意 set 会打乱文档顺序（生产可用 dict.fromkeys 保序去重）
def filter_node(state: State) -> State:
    docs = state.get("retrieved_docs", [])
    filtered = list({doc for doc in docs if "未找到" not in doc})
    return {"filtered_docs": filtered if filtered else ["有效文献不足"]}

# 节点4：文献摘要，截取核心内容（原样保留）
def summarize_node(state: State) -> State:
    docs = state.get("filtered_docs", [])
    summaries = [doc[:15] + "..." for doc in docs]
    return {"summaries": summaries}

# 节点5：结论生成，汇总摘要并形成最终输出（bug 修复）
def conclude_node(state: State) -> State:
    summaries = state.get("summaries", [])
    # 原写法：if "暂无摘要" in summaries or "有效文献不足" in summaries:
    #         （精确匹配列表元素——但 summarize 会给失败信号加省略号，
    #          "有效文献不足..." != "有效文献不足"，降级链在此断裂）
    # 修复：改为子串匹配，失败信号无论是否被加工过都能识别
    if any(("有效文献不足" in s) or ("未找到" in s) or (s == "暂无摘要") for s in summaries):
        conclusion = "未能生成可靠的科研结论"
    else:
        conclusion = "基于现有文献分析：" + " | ".join(summaries)
    return {"conclusion": conclusion}


# 构建任务图（原样保留）
builder = StateGraph(State)
builder.add_node("preprocess", preprocess_node)
builder.add_node("retrieve", retrieve_node)
builder.add_node("filter", filter_node)
builder.add_node("summarize", summarize_node)
builder.add_node("conclude", conclude_node)

# 定义执行路径（原样保留：五节点单线流水线）
builder.set_entry_point("preprocess")
builder.add_edge("preprocess", "retrieve")
builder.add_edge("retrieve", "filter")
builder.add_edge("filter", "summarize")
builder.add_edge("summarize", "conclude")
builder.add_edge("conclude", END)

# 编译任务图（原样保留）
graph = builder.compile()

# 执行科研助手任务（原样保留：正常路径，graph 与 agent 两个关键词都命中）
result = graph.invoke({"query": "Graph Agent Research"})
print(result)


# 补充验证：故障路径（教材未含，用于实证 conclude 的降级链修复）
# "Quantum Research" 中只有 research 不在数据库 → 触发 "未找到相关文献" → 过滤后空 → "有效文献不足"
# 修复前实测：conclusion = "基于现有文献分析：有效文献不足..."（失败被当正常结果）
# 修复后实测：conclusion = "未能生成可靠的科研结论"（降级链恢复工作）
print(graph.invoke({"query": "Quantum Research"}))


# 实测输出：
# 正常路径：
# {'query': 'Graph Agent Research', 'keywords': ['graph', 'agent', 'research'],
#  'retrieved_docs': ['LangGraph用于任务编排', '图式化逻辑提升多Agent协作效率',
#                     '智能体体系依赖状态追踪', '多任务分解是关键挑战'],
#  'filtered_docs': [4 条文献（set 去重，顺序可能与上面不同）],
#  'summaries': [4 条截断摘要],
#  'conclusion': '基于现有文献分析：LangGraph用于任务编... | ...'}
# 故障路径：
# {'query': 'Quantum Research', ..., 'filtered_docs': ['有效文献不足'],
#  'summaries': ['有效文献不足...'], 'conclusion': '未能生成可靠的科研结论'}
