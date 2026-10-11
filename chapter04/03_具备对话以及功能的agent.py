# 【例4-3】 Memory 记忆管理
# Memory Management 赋予模型长期记忆，保留对话历史与上下文信息，实现具备连贯性的智能对话体验。

# 原写法：langchain 0.x 的 import 路径 + OpenAI 模型类，在当前环境无法运行，原因有二：
#   1) LangChain 1.x 路径拆分：initialize_agent 收纳进 langchain_classic.agents，
#      Tool 在 langchain_core.tools，ConversationBufferMemory 收纳进 langchain_classic.memory，
#      langchain.llms.OpenAI 类已移除
#   2) OpenAI 类需要 OPENAI_API_KEY 且国内无法直连 OpenAI 官方服务
# from langchain.agents import initialize_agent, Tool
# from langchain.memory import ConversationBufferMemory
# from langchain.llms import OpenAI

# 改写（参照 01/02 篇的方式）：
#   - 经典 API 从 langchain_classic 导入，Tool 从 langchain_core.tools 导入
#   - 模型类 OpenAI 改为 ChatTongyi（阿里百炼平台），temperature=0.4 语义不变
#   - 天气模拟函数、Tool 包装、ConversationBufferMemory 配置、三轮对话测试一字不动
#     （"记忆让省略主语的追问成为可能"是本篇教学核心）
import os

from langchain_classic.agents import initialize_agent
from langchain_classic.memory import ConversationBufferMemory
from langchain_core.tools import Tool
from langchain_community.chat_models import ChatTongyi

# 初始化模型与Agent（工具函数定义在模型之后不影响：函数体只在 agent.run 时被调用）
# 原写法：llm = OpenAI(temperature=0.4)
# 改写：换用百炼平台的 qwen-plus，从环境变量读取 DASHSCOPE_API_KEY
llm = ChatTongyi(
    model="qwen-plus",
    temperature=0.4,
    dashscope_api_key=os.environ.get("DASHSCOPE_API_KEY"),
)

# 自定义工具：天气响应模拟（原函数逻辑完全保留：字典查表，未收录城市返回提示）
def get_weather(city: str) -> str:
    dummy_weather = {
        "北京": "晴，25°C",
        "上海": "多云，23°C",
        "广州": "雷阵雨，29°C"
    }
    return dummy_weather.get(city, "当前城市暂无天气数据")

weather_tool = Tool(
    name="WeatherTool",
    func=get_weather,
    description="查询城市天气，如输入：北京"
)

# 初始化Memory：记录用户每轮对话（原配置完全保留）
memory = ConversationBufferMemory(
    memory_key="chat_history",
    input_key="input"
)

# 初始化Agent（原 initialize_agent 结构完全保留，含 memory 注入）
agent = initialize_agent(
    tools=[weather_tool],
    llm=llm,
    memory=memory,
    agent="zero-shot-react-description",
    verbose=True
)

# 连续执行多轮对话任务
print("用户：我想知道北京天气如何？")
res1 = agent.run("我想知道北京天气如何？")
print("回答：", res1)

print("\n用户：那广州呢？")
res2 = agent.run("那广州呢？")
print("回答：", res2)

print("\n用户：那明天去哪旅游好？")
res3 = agent.run("那明天去哪旅游好？")
print("回答：", res3)
