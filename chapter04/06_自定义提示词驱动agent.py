# 【例4-6】 自定义提示词驱动智能体：定制Agent的"灵魂"
# 核心概念：提示词即"指令集" 在 LangChain 框架中，Agent 的行为逻辑完全依赖大模型的推理能力，而提示词就是引导推理方向的"核心指令集"，是实现 Agent 能力定制化的最关键手段。

# 原写法：langchain 0.x 的 import 路径 + OpenAI 模型类，在当前环境无法运行，原因有二：
#   1) LangChain 1.x 路径拆分：initialize_agent/Tool/AgentType 收纳进 langchain_classic.agents，
#      ConversationBufferMemory 收纳进 langchain_classic.memory，PromptTemplate 在 langchain_core.prompts，
#      langchain.chat_models.ChatOpenAI 类已移除
#   2) OpenAI 类需要 OPENAI_API_KEY 且国内无法直连 OpenAI 官方服务
# from langchain.chat_models import ChatOpenAI
# from langchain.agents import initialize_agent, Tool
# from langchain.agents.agent_types import AgentType
# from langchain.memory import ConversationBufferMemory
# from langchain.prompts import PromptTemplate

# 本篇还有一个比 import 更深的问题——教材的自定义模板跑不通（原版 0.x 环境同样报错）：
#   教材的 custom_prompt 只是一个普通对话模板（"你是智能助理…{input}…{history}…"），
#   缺少 CONVERSATIONAL_REACT_DESCRIPTION 驱动所必需的三样东西：
#     1) {tools} 与 {tool_names} 变量——框架靠这两个占位符把工具清单注入提示词
#     2) {agent_scratchpad} 变量——框架靠它回传 Thought/Action/Observation 的中间轨迹
#     3) ReAct 格式指令——模型必须先被告知"Thought:/Action:/Final Answer:"的输出格式，
#        否则输出无法被 AgentOutputParser 解析，直接抛 OutputParserException
#   结论：教材展示的是"自定义提示词"的"概念示意"，而非可运行代码

# 改写（参照 01-05 篇的方式）：
#   - 经典 API 从 langchain_classic 导入，PromptTemplate 从 langchain_core.prompts 导入
#   - 模型类 ChatOpenAI 改为 ChatTongyi（阿里百炼平台），temperature=0.5 语义不变
#   - custom_prompt 升级为"中文 persona + 完整 ReAct 结构"的真实可用模板——
#     教材想教的核心（改提示词=定制 Agent 灵魂）被完整保留，且真正能跑
#   - 两个工具函数（wttr.in 真实天气 / 维基百科真实简介）、Tool 包装、memory、
#     agent_kwargs={"prompt": custom_prompt} 注入方式、三轮对话测试全部原样保留
import os
import requests

from langchain_classic.agents import initialize_agent, Tool, AgentType
from langchain_classic.memory import ConversationBufferMemory
from langchain_core.prompts import PromptTemplate
from langchain_community.chat_models import ChatTongyi

# 初始化大语言模型
# 原写法：llm = ChatOpenAI(model_name="gpt-3.5-turbo", temperature=0.5)
# 改写：换用百炼平台的 qwen-plus，从环境变量读取 DASHSCOPE_API_KEY
llm = ChatTongyi(
    model="qwen-plus",
    temperature=0.5,
    dashscope_api_key=os.environ.get("DASHSCOPE_API_KEY"),
)

# 工具函数：天气查询（原函数逻辑完全保留：wttr.in 单行格式真实 HTTP 调用）
def get_weather(city: str) -> str:
    try:
        url = f"https://wttr.in/{city}?format=3"
        response = requests.get(url)
        return response.text.strip()
    except Exception as e:
        return f"查询失败：{str(e)}"

# 工具函数：城市百科简介（原函数逻辑完全保留：维基百科 REST API 真实调用）
def get_city_intro(city: str) -> str:
    try:
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{city}"
        response = requests.get(url).json()
        return response.get("extract", "未找到该城市简介")
    except Exception as e:
        return f"查询失败：{str(e)}"

# 注册工具：需说明name, func, description（原样保留）
tools = [
    Tool(
        name="GetWeather",
        func=get_weather,
        description="输入城市名称，返回该城市当前天气情况"
    ),
    Tool(
        name="GetCityIntro",
        func=get_city_intro,
        description="输入城市名称，返回该城市的百科简介"
    )
]

# 自定义Prompt模板（本篇核心）
# 原写法：教材的 PromptTemplate + agent_kwargs={"prompt": custom_prompt}
# 原写法的问题（原版 0.x 环境同样跑不通，这是"概念示意代码"）：
#   1) agent_kwargs={"prompt": ...} 不被 CONVERSATIONAL_REACT_DESCRIPTION 支持——
#      查框架源码可知：该 Agent 的工具清单是"预格式化"拼进模板字符串的（不存在 {tools} 变量），
#      from_llm_and_tools 根本没有 prompt 参数，传入只会被丢弃或报错
#   2) 教材模板缺少 ReAct 必需的 {agent_scratchpad} 变量与格式指令，
#      即使能注入，模型输出也无法被 ConvoOutputParser 解析
#   3) 教材 memory_key="history" 与该 Agent 默认模板的 {chat_history} 变量名不匹配
# 原写法代码（注释保留）：
# custom_prompt = PromptTemplate(
#     input_variables=["input", "history"],
#     template="""
# 你是一位知识渊博的智能助理，可以调用两种工具：GetWeather用于查询天气，GetCityIntro用于提供城市简介。
# 用户的问题如下：{input}
# 历史对话记录如下：{history}
# 请根据问题内容选择合适的工具进行调用，并用自然语言回答。
# """
# )

# 改写：用框架官方支持的"部分定制"通道——prefix（角色设定）+ suffix（结尾流程），
#       工具清单与 ReAct 格式指令仍由框架自动组装（这是 ConvoOutputParser 能解析的前提）
#   - prefix = 教材 persona 原文（"知识渊博的智能助理"+两个工具中文说明）——教学核心完整保留
#   - suffix 用中文重写结尾流程，历史变量名用 {history}——与教材 memory_key="history" 对齐，
#     {agent_scratchpad} 保留（框架回传 ReAct 中间轨迹的必需变量）
#   - format_instructions 不定制（保留框架默认英文版）——最终回答格式 "AI: ..." 是解析器协议
custom_prefix = """你是一位知识渊博的智能助理，可以调用两种工具：GetWeather用于查询天气，GetCityIntro用于提供城市简介。
请根据问题内容选择合适的工具进行调用，并用自然语言回答。"""

custom_suffix = """开始！

历史对话记录如下：
{history}

用户的问题如下：{input}
{agent_scratchpad}"""

# 配置对话记忆（原样保留：memory_key="history" 与自定义 suffix 的 {history} 变量对齐）
memory = ConversationBufferMemory(memory_key="history")

# 构建Agent（AgentType、memory、verbose 原样保留；prompt 注入方式按框架真实协议修正）
agent = initialize_agent(
    tools=tools,
    llm=llm,
    agent=AgentType.CONVERSATIONAL_REACT_DESCRIPTION,
    memory=memory,
    verbose=True,
    agent_kwargs={"prefix": custom_prefix, "suffix": custom_suffix}
)

# 启动Agent并模拟多轮对话（原样保留）
print("====== 实际对话示例 ======")
print(agent.run("介绍一下上海"))
print(agent.run("那现在上海的天气如何？"))
print(agent.run("北京天气怎么样？"))
