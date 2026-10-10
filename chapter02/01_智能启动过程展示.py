# 第2章 智能体系统的组成结构与运行机制
# 实现一个基于百炼平台 dashscope 的智能体启动过程，涵盖模型加载，工具注册，系统提示词配置，
# 初始化记忆注入及多轮日志追踪，并通过函数调用能力实现工具调度。

# 【例2-1】
# agent_startup.py

# 原写法：qwen_agent 的这些 API 是虚构的（真实 qwen-agent 包没有顶层 Agent/Tool/ChatMessage 导出，
#         也没有 QwenLLM / CompletionConfig 类），运行会报 ImportError，无法执行
# import logging
# import datetime
# from typing import List
# from qwen_agent import Agent, Tool, ChatMessage
# from qwen_agent.llm import QwenLLM
# from qwen_agent.tools.base import BaseTool
# from qwen_agent.utils.schema import CompletionConfig

# 改用阿里百炼平台 dashscope 调用大模型（参照 01-06 的改写方式）
import logging
import datetime
import json
import os
import dashscope

# 从环境变量中获取 DASHSCOPE_API_KEY（等价于原写法的"模型加载"环节）
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# 配置日志（多轮日志追踪）
logging.basicConfig(
    filename='agent_startup.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# ========== 工具注册 ==========
# 原写法：继承虚构的 BaseTool 类（含 run/description/parameters）
# 改写：工具注册 = "可执行函数 + 给模型看的 function calling 声明" 两部分

def get_current_time() -> str:
    """工具1的执行体：返回当前系统时间"""
    now = datetime.datetime.now()
    return now.strftime("当前时间是：%Y年%m月%d日 %H:%M:%S")

def startup_check() -> str:
    """工具2的执行体：执行Agent启动时的系统检查任务"""
    checks = ["模型加载完成", "工具已注册", "Memory注入成功", "上下文初始化完成"]
    return "系统初始化检查通过：" + "，".join(checks)

# 工具注册表：函数名 -> 执行体（模型只发"调用指令"，本地负责执行）
tool_registry = {
    "get_current_time": get_current_time,
    "startup_check": startup_check,
}

# 给模型看的工具说明书（dashscope tools 格式，等价于原写法每个工具类的 description + parameters）
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "获取当前系统时间",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "startup_check",
            "description": "执行Agent启动时的系统检查任务",
            "parameters": {"type": "object", "properties": {}}
        }
    }
]

# ========== 构建 Agent（模型 + 工具 + 系统提示词） ==========
# 原写法：build_agent() 内用虚构的 QwenLLM/CompletionConfig/Agent 类拼装
def build_agent():
    """构建智能体配置：等价于原写法 Agent(name/llm/tools/system_message) 的拼装过程"""
    logging.info("启动Agent构建流程")
    config = {
        "name": "SystemStartupAgent",
        "model": "qwen-plus",           # 模型加载（等价于 QwenLLM(model="qwen-plus")）
        "temperature": 0.3,             # 等价于 CompletionConfig(temperature=0.3)
        "max_tokens": 512,              # 等价于 CompletionConfig(max_tokens=512)
        "system_message": "你是一位系统智能体助手，负责初始化流程、工具检查与运行日志监控。"
    }
    logging.info("Agent构建完成")
    return config

# ========== Agent 循环：模型自主决定是否调用工具 ==========
def agent_chat(config, user_input, memory=None):
    """
    单次对话的 Agent 循环：带记忆注入 + 函数调用工具调度 + 多轮日志追踪

    参数:
        config: build_agent() 返回的智能体配置
        user_input: 用户本轮输入
        memory: 历史消息列表（初始化记忆注入；None 表示首轮）
    返回:
        (回复文本, 更新后的记忆列表)
    """
    # 初始化记忆注入：system 提示词 + 历史对话
    if memory is None:
        memory = [{"role": "system", "content": config["system_message"]}]
    memory = memory + [{"role": "user", "content": user_input}]
    logging.info("用户输入: %s", user_input)

    # Agent 循环：模型返回 tool_calls 就执行工具并把结果回传，直到模型给出最终回答
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

        # 无工具调用 -> 模型给出最终回答，循环结束
        if not tool_calls:
            reply = message.content
            memory = memory + [{"role": "assistant", "content": reply}]
            logging.info("模型回复: %s", reply)
            return reply, memory

        # 有工具调用 -> 本地执行注册表里的函数，结果以 role=tool 回传
        # 注意：dashscope 返回的 tool_calls 列表元素是 dict（非 OpenAI SDK 的对象），用字典取值
        memory = memory + [message]
        for call in tool_calls:
            fn_name = call['function']['name']
            logging.info("模型请求调用工具: %s", fn_name)
            fn = tool_registry.get(fn_name)
            tool_result = fn() if fn else f"未注册的工具: {fn_name}"
            logging.info("工具执行结果: %s", tool_result)
            memory = memory + [{
                "role": "tool",
                "content": tool_result,
                "name": fn_name,
                "tool_call_id": call.get('id', fn_name)
            }]

# 启动测试交互
def run_startup_sequence():
    config = build_agent()
    memory = None  # 跨轮共享的记忆（多轮对话上下文）

    logging.info("执行工具调用测试")
    res1, memory = agent_chat(config, "请执行一次系统检查", memory)
    print(">> 系统检查响应：", res1)

    logging.info("执行时间工具测试")
    res2, memory = agent_chat(config, "请告诉我现在几点", memory)
    print(">> 当前时间响应：", res2)

    logging.info("Agent初始化流程全部完成")

if __name__ == "__main__":
    run_startup_sequence()
