# ========== 访问外部数据库进行检索 ==========
# 教学核心：retrieve 工位从字典/集合模拟升级为真正的数据库——
# 用 sqlite3 内存库建表、插数据、按关键词执行 SQL 查询。
# 四节点流水线：预处理(关键词提取) → 数据库检索 → 工具加工(字符串替换) → 结论汇总。

# 原写法：from typing import Dict, List + class State(Dict): pass
# 原写法的问题：与 01-06 篇相同——langgraph 1.x 靠 State 类的字段注解构建状态 schema，
#   Dict 子类没有字段注解，实测 graph.invoke() 返回 None（静默失败，系列第七次）。
# 原写法代码（注释保留）：
# from langgraph.graph import StateGraph, END
# from typing import Dict, List
# import sqlite3
#
# class State(Dict):
#     pass

# 改写：State 改用 TypedDict（五个字段注解，教材 import 的 List 正好派上用场）。
#   四个节点函数（sqlite3 逻辑一字未动）、图构建、invoke 与原版逐行一致。
from langgraph.graph import StateGraph, END
from typing import List, TypedDict
import sqlite3

# 定义状态结构，存储运行过程数据（改写：TypedDict + 五个字段注解）
class State(TypedDict):
    query: str
    keywords: List[str]
    retrieved: List[str]
    processed: List[str]
    conclusion: str

# 节点1：接收问题并提取关键词（原样保留，同 05/06 篇）
def preprocess_node(state: State) -> State:
    query = state.get("query", "").strip()
    keywords = [word.lower() for word in query.split() if len(word) > 3]
    return {"query": query, "keywords": keywords}

# 节点2：连接外部数据库，检索文献信息（原样保留——本篇教学核心）
# 三个教学点：
#   1) sqlite3.connect(":memory:") 内存数据库——每次连接都是一个全新的空库，
#      连接关闭数据即销毁。所以这里每次执行节点都要重新建表插数据（教材注释已声明是示例）。
#      生产场景换成 connect("外部库文件.db") 或连接池，建表插数据只做一次。
#   2) CREATE TABLE / executemany / SELECT 的 SQL 逻辑是标准的
#   3) 查询用 ? 占位符 + 元组传参——SQL 注入防护的标准写法（呼应 char02-06 篇）
def retrieve_node(state: State) -> State:
    conn = sqlite3.connect(":memory:")  # 使用内存数据库示例
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE papers (id INTEGER PRIMARY KEY, keyword TEXT, content TEXT)")
    cursor.executemany("INSERT INTO papers (keyword, content) VALUES (?, ?)", [
        ("graph", "LangGraph提升任务流管理能力"),
        ("agent", "多Agent系统依赖任务调度与协作"),
        ("database", "科研任务常涉及数据库查询与整合")
    ])
    results = []
    for kw in state.get("keywords", []):
        cursor.execute("SELECT content FROM papers WHERE keyword=?", (kw,))
        rows = cursor.fetchall()
        results.extend([row[0] for row in rows])
    conn.close()
    return {"retrieved": results if results else ["未找到相关数据"]}

# 节点3：调用外部工具（此处用字符串处理代替，原样保留）
# 教学点：把 replace 当作"外部工具"的占位——真实场景可以是翻译、改写、LLM 润色等
def tool_node(state: State) -> State:
    docs = state.get("retrieved", [])
    processed = [doc.replace("系统", "智能体系统") for doc in docs]
    return {"processed": processed if processed else ["工具未返回结果"]}

# 节点4：结果汇总与格式化（原样保留）
# 注意一个微妙之处（呼应 06 篇的降级链断裂 bug）：
#   conclude 用精确匹配判断失败信号，而上一工位 tool 的 replace 恰好不会加工
#   "未找到相关数据"（信号里没有"系统"二字）——本篇降级链活着是**运气**不是设计！
#   若失败信号改叫"检索系统异常"，replace 会把它变成"检索智能体系统异常"，
#   精确匹配立刻失效——与 06 篇同款断裂。生产请用结构化 status 字段传失败状态。
def conclude_node(state: State) -> State:
    processed = state.get("processed", [])
    if "未找到相关数据" in processed or "工具未返回结果" in processed:
        conclusion = "未能生成有效结论"
    else:
        conclusion = "综合分析结果: " + " | ".join(processed)
    return {"conclusion": conclusion}

# 构建任务图（原样保留）
builder = StateGraph(State)
builder.add_node("preprocess", preprocess_node)
builder.add_node("retrieve", retrieve_node)
builder.add_node("tool", tool_node)
builder.add_node("conclude", conclude_node)

# 定义执行路径（原样保留）
builder.set_entry_point("preprocess")
builder.add_edge("preprocess", "retrieve")
builder.add_edge("retrieve", "tool")
builder.add_edge("tool", "conclude")
builder.add_edge("conclude", END)

# 编译并执行任务（原样保留）
graph = builder.compile()
result = graph.invoke({"query": "Graph Agent Database Research"})
print(result)


# 补充验证：故障路径（教材未含，用于实证降级链在本篇的行为）
# "Quantum" 不命中任何数据 → ["未找到相关数据"] → replace 不加工它 → conclude 判断命中
# 实测结论：本篇降级链正常工作，输出 "未能生成有效结论"（但这是信号未被加工的巧合，见上）
print(graph.invoke({"query": "Quantum"}))

#1. 流程链路：`preprocess关键词提取` → `retrieve内存sqlite数据库查询` → `tool字符串替换工具` → `conclude汇总输出`
#2. 使用`sqlite3`内存数据库，程序运行结束数据库自动销毁，无需本地文件
#3. tool_node 模拟外部工具调用，示例把文本里的`系统`替换为`智能体系统`


# 输出结果（教材预期——本篇教材预期输出实测核对完全正确）：
# 正常路径：
# {'query': 'Graph Agent Database Research',
#  'keywords': ['graph', 'agent', 'database', 'research'],
#  'retrieved': ['LangGraph提升任务流管理能力', '多Agent系统依赖任务调度与协作',
#                '科研任务常涉及数据库查询与整合'],
#  'processed': ['LangGraph提升任务流管理能力', '多Agent智能体系统依赖任务调度与协作',
#                '科研任务常涉及数据库查询与整合'],
#  'conclusion': '综合分析结果: LangGraph提升任务流管理能力 | 多Agent智能体系统依赖任务调度与协作 | 科研任务常涉及数据库查询与整合'}
# 故障路径（补充验证）：
# {'query': 'Quantum', ..., 'retrieved': ['未找到相关数据'],
#  'processed': ['未找到相关数据'], 'conclusion': '未能生成有效结论'}
