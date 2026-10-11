# 【例4-7】 工具链动态规划逻辑：实现任务的自动分解与执行
# 动态规划逻辑是智能体的核心能力之一。它让智能体不再被动执行单一指令，而是能够理解任务的上下文和目标，动态判断调用的工具类型与顺序，
# 从而将复杂的任务自动拆解为可执行的步骤序列，完成端到端的自主规划与执行。

# 原写法：langchain 0.x 的 import 路径 + OpenAI 模型类，在当前环境无法运行，原因有二：
#   1) LangChain 1.x 路径拆分：Tool/initialize_agent/AgentType 收纳进 langchain_classic.agents，
#      ConversationBufferMemory 收纳进 langchain_classic.memory，
#      langchain.chat_models.ChatOpenAI 类已移除
#   2) OpenAI 类需要 OPENAI_API_KEY 且国内无法直连 OpenAI 官方服务
# from langchain.chat_models import ChatOpenAI
# from langchain.agents import Tool, initialize_agent
# from langchain.memory import ConversationBufferMemory
# from langchain.agents.agent_types import AgentType

# 本篇还有一个隐蔽的逻辑 bug（即使 import 与模型修好也会"跑得通但教学目标落空"）：
#   原代码 memory_key="history"，而 CONVERSATIONAL_REACT_DESCRIPTION 默认模板里的
#   历史变量名是 {chat_history}（06 篇已查源码实证）——变量名不匹配会导致记忆静默丢失，
#   第二轮"请介绍第一本书的详细信息"时模型根本不知道"第一本书"是谁，
#   工具链的跨轮接力（搜书 -> 记住第一本 -> 查详情）就断了。改写修正为 "chat_history"。

# 改写（参照 01-06 篇的方式）：
#   - 经典 API 从 langchain_classic 导入，Tool 从 langchain_core.tools 导入
#   - 模型类 ChatOpenAI 改为 ChatTongyi（阿里百炼平台），temperature=0 语义不变
#   - 两个工具函数（openlibrary.org 真实 API）、Tool 包装、Agent 组装、两轮对话全部原样保留
import os
import requests

from langchain_classic.agents import initialize_agent, Tool
from langchain_classic.agents.agent_types import AgentType
from langchain_classic.memory import ConversationBufferMemory
from langchain_community.chat_models import ChatTongyi

# 初始化语言模型
# 原写法：llm = ChatOpenAI(temperature=0, model_name="gpt-3.5-turbo")
# 改写：换用百炼平台的 qwen-plus，从环境变量读取 DASHSCOPE_API_KEY
llm = ChatTongyi(
    model="qwen-plus",
    temperature=0,
    dashscope_api_key=os.environ.get("DASHSCOPE_API_KEY"),
)

# 工具1：基于关键词搜索图书
# 原写法：openlibrary.org 真实 API。实测在国内网络环境连接超时（openlibrary.org 不可达），
#   且原函数没有 try/except 兜底——ConnectTimeout 异常从 tool.run 一路抛到顶层，
#   直接把 AgentExecutor 打崩（对照 06 篇：维基百科超时有兜底，模型能优雅降级）。
#   真实 API 版本原样注释保留，网络可达的环境可直接切回（建议补上 timeout=5）：
# def search_books(keyword: str) -> str:
#     """调用公开API搜索图书标题"""
#     url = f"https://openlibrary.org/search.json?q={keyword}"
#     res = requests.get(url, timeout=5)
#     docs = res.json().get("docs", [])[:3]
#     return "\n".join([f"{i+1}. {doc.get('title')} by {doc.get('author_name', ['N/A'])[0]}" for i, doc in enumerate(docs)])

# 改写：本地模拟书库（保持与原版相同的返回格式："序号. 书名 by 作者"）
#   教学定位与 05 篇哑工具一致：工具实现是假的，"搜书 -> 记住第一本 -> 查详情"的
#   工具链动态规划才是本篇灵魂——数据本地化保证教学主链路在国内网络可复现
LOCAL_BOOKS = [
    {"title": "人工智能：一种现代方法", "author": "Stuart Russell", "year": 2020},
    {"title": "深度学习", "author": "Ian Goodfellow", "year": 2017},
    {"title": "生命3.0", "author": "Max Tegmark", "year": 2018},
]

def search_books(keyword: str) -> str:
    """调用公开API搜索图书标题（改写版：本地模拟，返回格式与原版一致）"""
    hits = [b for b in LOCAL_BOOKS if any(k in b["title"] for k in ["人工智能", "AI", "artificial", "智能"])]
    if keyword not in ("", None) and not hits:
        hits = LOCAL_BOOKS  # 未命中时退化为全量返回，保证演示链路不中断
    return "\n".join([f"{i+1}. {b['title']} by {b['author']}" for i, b in enumerate(hits[:3])])

# 工具2：根据书名获取图书详细信息
# 原写法：openlibrary.org 真实 API（同样因网络不可达改写，且原函数无异常兜底）：
# def get_book_details(title: str) -> str:
#     """根据书名获取图书出版详情"""
#     url = f"https://openlibrary.org/search.json?title={title}"
#     res = requests.get(url, timeout=5)
#     docs = res.json().get("docs", [])
#     if not docs:
#         return "未找到该书籍详情"
#     book = docs[0]
#     return f"书名: {book.get('title')}\n作者: {book.get('author_name', ['N/A'])[0]}\n出版时间: {book.get('first_publish_year', '未知')}"

def get_book_details(title: str) -> str:
    """根据书名获取图书出版详情（改写版：本地模拟，返回格式与原版一致）"""
    # 清洗模型传入的书名（实测模型会带书名号《》或拼上" by 作者"后缀——
    # 真实 API 用 HTTP 参数化查询天然健壮，模拟版需要自己做解析清洗）
    t = title.strip().strip("《》").strip()
    if " by " in t:
        t = t.split(" by ")[0].strip()
    for b in LOCAL_BOOKS:
        if b["title"] == t or t in b["title"] or b["title"] in t:
            return f"书名: {b['title']}\n作者: {b['author']}\n出版时间: {b['year']}"
    return "未找到该书籍详情"

# 定义工具集（原样保留）
tools = [
    Tool(
        name="SearchBooks",
        func=search_books,
        description="根据关键词搜索图书，适合用于确定书名"
    ),
    Tool(
        name="GetBookDetails",
        func=get_book_details,
        description="根据书名获取图书详细信息"
    )
]

# 配置对话记忆
# 原写法：memory_key="history" —— 与默认模板的 {chat_history} 变量名不匹配，记忆静默丢失
# 改写：memory_key="chat_history"，与 CONVERSATIONAL_REACT_DESCRIPTION 默认模板对齐
memory = ConversationBufferMemory(memory_key="chat_history")

# 初始化Agent（原结构完全保留：CONVERSATIONAL_REACT_DESCRIPTION + 默认英文模板）
agent = initialize_agent(
    tools=tools,
    llm=llm,
    agent=AgentType.CONVERSATIONAL_REACT_DESCRIPTION,
    memory=memory,
    verbose=True
)

# 多轮调用：先搜索，再根据第一本书名查询详情（原样保留）
# 第二轮"第一本书"没有出现在本轮输入里——全靠第一轮存进记忆的搜索结果
response_1 = agent.run("我想查几本关于人工智能的书")
response_2 = agent.run("请介绍第一本书的详细信息")

# 输出结果
print(response_1)
print(response_2)
