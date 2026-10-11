# 【例4-2】 Tools & Agent 集成
# ration  赋予模型行动能力，连接外部工具与知识库，让AI能够自主决策并与外部世界交互。

# 原写法：langchain 0.x 的 import 路径 + OpenAI 模型类，在当前环境无法运行，原因有二：
#   1) LangChain 1.x 路径拆分：initialize_agent / AgentType / Tool 属于经典 Agent API，
#      收纳进 langchain_classic.agents；langchain.llms.OpenAI 类已移除
#   2) OpenAI 类需要 OPENAI_API_KEY 且国内无法直连 OpenAI 官方服务
# from langchain.agents import Tool, initialize_agent
# from langchain.agents.agent_types import AgentType
# from langchain.llms import OpenAI

# 改写（参照 01_langchain多段链式处理.py 的方式）：
#   - 经典 Agent API 从 langchain_classic.agents 导入，Tool 从 langchain_core.tools 导入
#   - 模型类 OpenAI 改为 ChatTongyi（阿里百炼平台），temperature=0.3 语义不变
#   - 两个工具函数、Tool 包装、initialize_agent 的 ZERO_SHOT_REACT_DESCRIPTION 结构一字不动
#     （ReAct 智能体"思考->行动->观察"的循环是本篇教学核心）
import os

import requests
from langchain_classic.agents import AgentType, initialize_agent
from langchain_core.tools import Tool
from langchain_community.chat_models import ChatTongyi

# 初始化LLM和Agent（工具函数定义在模型之后不影响：函数体只在 agent.run 时被调用）
# 原写法：llm = OpenAI(temperature=0.3)
# 改写：换用百炼平台的 qwen-plus，从环境变量读取 DASHSCOPE_API_KEY
llm = ChatTongyi(
    model="qwen-plus",
    temperature=0.3,
    dashscope_api_key=os.environ.get("DASHSCOPE_API_KEY"),
)

# 工具1：网页内容摘要（原函数逻辑完全保留：requests 拉网页 + 截取前1000字再取前300字）
def fetch_summary(url: str) -> str:
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            content = resp.text[:1000]
            return f"网页摘要：{content[:300]}..."  # 仅返回前300字
        else:
            return "无法访问网页内容"
    except Exception as e:
        return str(e)

# 工具2：美元转人民币汇率计算
# 原写法：def convert_usd_to_cny(amount: float) -> str:  …  converted = round(amount * rate, 2)
# 注意：原代码这里还藏着一个 bug——ReAct 型智能体的工具输入是从文本协议
#       （"Action Input: 20.0"）解析出的【字符串】，直接乘浮点数会抛
#       TypeError: can't multiply sequence by non-int of type 'float'
#       原代码运行必然报错，不是版本迁移问题；这也是 ReAct 时代的经典坑：
#       工具输入永远是字符串，函数内部必须自己做类型转换
#       （对比 char02 系列：Function Calling 模型输出 JSON，框架已自动解析类型）
# 修复：加 float() 显式转换
def convert_usd_to_cny(amount) -> str:
    rate = 7.25
    converted = round(float(amount) * rate, 2)
    return f"{amount}美元 ≈ {converted}人民币（按汇率7.25）"

# 包装为LangChain工具（原 Tool 包装方式完全保留）
tools = [
    Tool(
        name="WebSummaryTool",
        func=fetch_summary,
        description="根据提供的网址提取网页摘要，适用于阅读网页内容",
    ),
    Tool(
        name="USDToCNYConverter",
        func=convert_usd_to_cny,
        description="将美元金额转换成人民币金额，适用于财务相关查询",
    )
]

# 初始化Agent（原 initialize_agent 的 ZERO_SHOT_REACT_DESCRIPTION 结构完全保留）
agent = initialize_agent(
    tools,
    llm,
    agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
    verbose=True
)

# 测试任务
response = agent.run("请帮我把20美元换算成人民币")

print("==== 输出结果 ====")
print(response)
