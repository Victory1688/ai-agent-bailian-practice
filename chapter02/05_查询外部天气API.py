# 【例2-5】 调用Web API与插件机制
# 核心概念：通过调用外部Web API或引入插件，智能体可以突破自身能力的限制，
# 极大地扩展其功能边界，实现从"单一对话"到"执行任务"的跨越。

# agent_web_api_weather.py

# 原写法：qwen_agent 的这些 API 是虚构的（真实包没有这些类），运行报 ImportError，无法执行
# import requests
# import json
# from qwen_agent import Agent, Tool
# from qwen_agent.llm import QwenLLM
# from qwen_agent.utils.schema import CompletionConfig
# from qwen_agent.tools.base import BaseTool

# 改用阿里百炼平台 dashscope 调用大模型（参照 01_智能启动过程展示.py 的改写方式）
import requests       # 这个是标准库，原代码已导入，保留（真正调用外部 API 的关键）
import json
import os
import dashscope

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# ========== 天气查询工具（原 WeatherAPITool.run 的 API 调用逻辑全部保留） ==========
# 原写法：继承虚构 BaseTool 的工具类，run() 里调 wttr.in 接口
# 改写：普通函数（带参数）+ tools 说明书 + tool_registry 注册表
#       但 run() 里的 requests.get 真实 API 调用逻辑原样保留——这是"调用外部 API"的核心教学点

def get_weather(city: str) -> str:
    """
    工具执行体：调用 wttr.in 接口获取城市天气

    原 run() 方法的逻辑全部保留：
    - 城市名校验（strip + 空值判断）
    - requests.get(url, timeout=5) 调 wttr.in 免费天气 API
    - 解析 JSON 取 temp_C / humidity / weatherDesc
    - try/except 异常兜底
    """
    city = city.strip()
    if not city:
        return "请输入有效的城市名"
    try:
        url = f"https://wttr.in/{city}?format=j1"
        resp = requests.get(url, timeout=5)
        if resp.status_code != 200:
            return f"查询失败，状态码：{resp.status_code}"
        data = resp.json()
        current = data["current_condition"][0]
        temp = current["temp_C"]
        humidity = current["humidity"]
        desc = current["weatherDesc"][0]["value"]
        return f"{city}当前天气：{desc}，温度：{temp}℃，湿度：{humidity}%"
    except Exception as e:
        return f"调用天气API出错：{str(e)}"

# 工具注册表
tool_registry = {"get_weather": get_weather}

# 给模型看的工具说明书（原 WeatherAPITool 的 description + parameters 两个属性合并到此）
tools = [
    {"type": "function", "function": {
        "name": "get_weather",
        "description": "获取指定城市的实时天气信息",
        "parameters": {"type": "object", "properties": {
            "city": {"type": "string", "description": "城市名称"}
        }, "required": ["city"]}}
    }
]

SYSTEM_MESSAGE = "你是一位天气查询助手，支持调用外部API获取城市实时天气信息"


# ========== Agent 循环（同 02/03/04 篇模式） ==========
def agent_chat(config, user_input, memory=None):
    """单次对话的 Agent 循环：函数调用 → 外部 API → 结果回传 → 生成回答"""
    if memory is None:
        memory = [{"role": "system", "content": config["system_message"]}]
    memory = memory + [{"role": "user", "content": user_input}]

    while True:
        response = dashscope.Generation.call(
            model=config["model"],
            messages=memory,
            tools=tools,
            temperature=config["temperature"],
            max_tokens=config["max_tokens"],
            result_format='message'
        )
        message = response.output.choices[0].message
        tool_calls = getattr(message, 'tool_calls', None)

        if not tool_calls:
            memory = memory + [{"role": "assistant", "content": message.content}]
            return message.content, memory

        memory = memory + [message]
        for call in tool_calls:
            fn_name = call['function']['name']
            fn_args = json.loads(call['function'].get('arguments') or '{}')
            fn = tool_registry.get(fn_name)
            tool_result = fn(**fn_args) if fn else f"未注册的工具: {fn_name}"
            memory = memory + [{
                "role": "tool",
                "content": tool_result,
                "name": fn_name,
                "tool_call_id": call.get('id', fn_name)
            }]


# ========== 构建 Agent（原 build_weather_agent 改写） ==========
# 原写法：Agent(name, llm, tools, system_message) 拼装
# 改写：config 字典 + agent_chat 函数本身就是 Agent
def build_weather_agent():
    config = {
        "name": "WeatherQueryAgent",
        "model": "qwen-plus",
        "temperature": 0.3,
        "max_tokens": 256,
        "system_message": SYSTEM_MESSAGE
    }
    return config


# ========== 模拟用户查询天气 ==========
def run_weather_query():
    config = build_weather_agent()
    memory = None  # 首轮传 None → agent_chat 内部注入 system_message

    reply, memory = agent_chat(config, "请告诉我北京现在的天气", memory)
    print(">>", reply)
    reply, memory = agent_chat(config, "上海的天气怎么样？", memory)
    print(">>", reply)
    reply, memory = agent_chat(config, "请查询一下深圳的当前温度和湿度", memory)
    print(">>", reply)

if __name__ == "__main__":
    run_weather_query()
