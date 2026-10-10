# 【例2-2】 核心概念 · Core Concept
# 对话状态追踪是智能体在多轮交互中保持"记忆"和"逻辑"的核心机制。
# 它让智能体能够跟踪任务进度、存储中间变量，从而确保交互过程的连贯性与任务达成率。

# agent_state_tracking.py

# 原写法：qwen_agent 的这些 API 是虚构的（真实包没有顶层 Agent/Tool/ChatMessage 导出，
#         也没有 QwenLLM / SimpleMemory / CompletionConfig），运行报 ImportError，无法执行
# from qwen_agent import Agent, Tool, ChatMessage
# from qwen_agent.llm import QwenLLM
# from qwen_agent.memory import SimpleMemory
# from qwen_agent.utils.schema import CompletionConfig
# from qwen_agent.tools.base import BaseTool

# 改用阿里百炼平台 dashscope 调用大模型（参照 01_智能启动过程展示.py 的改写方式）
import json
import os
import dashscope

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# ========== 状态追踪的核心：任务状态字典 ==========
# 原写法用 SimpleMemory() 存状态；改写为显式的 task_state 字典——
# 工具执行时把信息写进来，"总结会议信息"时模型从工具回传结果中读到，这就是状态追踪
task_state = {"topic": None, "time": None, "attendees": None}

# ========== 工具注册 ==========
# 原写法：三个继承虚构 BaseTool 的工具类（含 params.get 取参）
# 改写：普通函数（带参数）+ tools 说明书 + tool_registry 注册表

def set_topic(topic: str) -> str:
    """工具1执行体：设置会议主题，并写入任务状态"""
    task_state["topic"] = topic
    return f"会议主题已设置为：{topic}"

def set_time(time: str) -> str:
    """工具2执行体：设置会议时间，并写入任务状态"""
    task_state["time"] = time
    return f"会议时间已设置为：{time}"

def set_attendees(attendees: str) -> str:
    """工具3执行体：设置与会人员，并写入任务状态"""
    task_state["attendees"] = attendees
    return f"与会人员已设定为：{attendees}"

# 工具注册表：函数名 -> 执行体
tool_registry = {
    "set_topic": set_topic,
    "set_time": set_time,
    "set_attendees": set_attendees,
}

# 给模型看的工具说明书（dashscope tools 格式，参数声明等价于原写法各工具类的 parameters）
tools = [
    {"type": "function", "function": {
        "name": "set_topic", "description": "设置会议主题",
        "parameters": {"type": "object", "properties": {
            "topic": {"type": "string", "description": "会议主题"}}, "required": ["topic"]}}},
    {"type": "function", "function": {
        "name": "set_time", "description": "设置会议时间",
        "parameters": {"type": "object", "properties": {
            "time": {"type": "string", "description": "会议时间"}}, "required": ["time"]}}},
    {"type": "function", "function": {
        "name": "set_attendees", "description": "设置与会人员",
        "parameters": {"type": "object", "properties": {
            "attendees": {"type": "string", "description": "人员名单"}}, "required": ["attendees"]}}},
]

SYSTEM_MESSAGE = "你是一个会议助手Agent，请协助用户完成会议主题、时间和与会人员设定，需记录所有输入信息以备后续回顾"

# ========== Agent 循环：带状态追踪与记忆注入 ==========
def agent_chat(user_input, memory=None):
    """
    单次对话的 Agent 循环：函数调用 + 工具执行写入 task_state + 多轮记忆

    参数:
        user_input: 用户本轮输入
        memory: 历史消息列表（None 表示首轮）
    返回:
        (回复文本, 更新后的记忆列表)
    """
    if memory is None:
        memory = [{"role": "system", "content": SYSTEM_MESSAGE}]
    memory = memory + [{"role": "user", "content": user_input}]
    print(f"[状态追踪] 用户输入: {user_input}")

    while True:
        response = dashscope.Generation.call(
            model="qwen-plus",
            messages=memory,
            tools=tools,
            temperature=0.3,
            max_tokens=512,
            result_format='message'
        )
        message = response.output.choices[0].message
        tool_calls = getattr(message, 'tool_calls', None)

        # 无工具调用 -> 最终回答
        if not tool_calls:
            reply = message.content
            memory = memory + [{"role": "assistant", "content": reply}]
            print(f"[状态追踪] 当前任务状态: {task_state}")  # 展示状态随轮次演进
            return reply, memory

        # 有工具调用 -> 本地执行，arguments 是 JSON 字符串需解析后传参
        memory = memory + [message]
        for call in tool_calls:
            fn_name = call['function']['name']
            fn_args = json.loads(call['function'].get('arguments') or '{}')
            fn = tool_registry.get(fn_name)
            tool_result = fn(**fn_args) if fn else f"未注册的工具: {fn_name}"
            print(f"[状态追踪] 调用工具 {fn_name}({fn_args}) -> {tool_result}")
            memory = memory + [{
                "role": "tool",
                "content": tool_result,
                "name": fn_name,
                "tool_call_id": call.get('id', fn_name)
            }]

# 运行模拟对话过程
def run_tracking_test():
    memory = None  # 跨轮共享的记忆（对话连贯性的来源）

    # 每轮都把更新后的 memory 传给下一轮——这就是多轮状态追踪的实现方式
    reply, memory = agent_chat("我要安排一个关于AI发展的会议", memory)
    print(">>", reply)
    reply, memory = agent_chat("会议时间定在5月3号上午10点", memory)
    print(">>", reply)
    reply, memory = agent_chat("参加人包括张三、李四和王五", memory)
    print(">>", reply)
    reply, memory = agent_chat("请总结一下目前的会议信息", memory)
    print(">>", reply)

if __name__ == "__main__":
    run_tracking_test()
