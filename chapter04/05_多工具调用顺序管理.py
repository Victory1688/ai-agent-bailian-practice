# 【例4-5】 多工具调用顺序管理：实现复杂任务流
# 核心概念：许多复杂任务需要多个工具按特定顺序协同工作。显式地管理调用顺序，可以消除执行歧义，显著提高系统的稳定性和结果的可控性

# 原写法：langchain 0.x 的 import 路径 + OpenAI 模型类，在当前环境无法运行，原因有二：
#   1) LangChain 1.x 路径拆分：@tool 装饰器在 langchain_core.tools（与 02-04 篇的 Tool 类同门），
#      initialize_agent 收纳进 langchain_classic.agents，ConversationBufferMemory 收纳进
#      langchain_classic.memory，langchain.llms.OpenAI 类已移除
#   2) OpenAI 类需要 OPENAI_API_KEY 且国内无法直连 OpenAI 官方服务
# from langchain.agents import Tool, initialize_agent
# from langchain.memory import ConversationBufferMemory
# from langchain.llms import OpenAI
# from langchain.tools import tool
# from typing import List        # 原代码导入了但从未使用，改写后一并省略

# 改写（参照 01-04 篇的方式）：
#   - @tool 装饰器从 langchain_core.tools 导入（新式工具定义，与 Tool(name=..., func=...) 旧式包装并存）
#   - 模型类 OpenAI 改为 ChatTongyi（阿里百炼平台），temperature=0 语义不变（顺序规划要确定性）
#   - 三个工具函数、docstring（即工具说明书）、工具列表、Agent 组装、测试任务一字不动
#     （"模型自主规划 搜索->摘要->翻译 的调用顺序"是本篇教学核心）
import os

from langchain_classic.agents import initialize_agent
from langchain_classic.memory import ConversationBufferMemory
from langchain_core.tools import tool
from langchain_community.chat_models import ChatTongyi

# 初始化模型与Agent（工具函数定义在模型之后不影响：函数体只在 agent.run 时被调用）
# 原写法：llm = OpenAI(temperature=0)
# 改写：换用百炼平台的 qwen-plus，从环境变量读取 DASHSCOPE_API_KEY
llm = ChatTongyi(
    model="qwen-plus",
    temperature=0,
    dashscope_api_key=os.environ.get("DASHSCOPE_API_KEY"),
)

# 工具1：网络搜索接口（模拟）
@tool
def search_web(query: str) -> str:
    """根据用户输入执行Web搜索，并返回摘要结果"""
    if "AI Agent" in query:
        return "AI Agent是一种基于大语言模型的自主任务执行单元，具备工具调用与上下文感知能力。"
    return f"未找到关于：{query} 的相关信息"

# 工具2：摘要生成器
@tool
def summarize_text(text: str) -> str:
    """对给定文本执行摘要处理"""
    return "智能体是一种基于大模型的自主系统。"

# 工具3：翻译模块
@tool
def translate_to_zh(text: str) -> str:
    """将英文摘要翻译成中文"""
    return "智能体是一种基于大模型的自主系统。"

# 工具集成（@tool 装饰后函数已变为 StructuredTool 对象，可直接进列表）
tools = [search_web, summarize_text, translate_to_zh]

# 初始化Agent（原结构完全保留，含 memory）
memory = ConversationBufferMemory()
agent = initialize_agent(
    tools=tools,
    llm=llm,
    memory=memory,
    agent="zero-shot-react-description",
    verbose=True
)

# 任务请求：用中文总结AI Agent的基本定义
print("用户输入：用中文总结AI Agent的基本定义")
output = agent.run("用中文总结AI Agent的基本定义")
print("模型输出：", output)
