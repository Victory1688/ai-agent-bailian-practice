# 【例2-3】 中断恢复机制确保智能体在交互被意外中断后，能够从断点继续任务。
# 持久化上下文则是将对话状态存储到外部介质中，支持长时间、跨设备的交互体验，保障用户会话的连续性。

# persistent_memory_agent.py

# 原写法：qwen_agent 的这些 API 是虚构的（真实包没有这些类），运行报 ImportError，无法执行
# import os
# import json
# from typing import List
# from qwen_agent import Agent, Tool
# from qwen_agent.llm import QwenLLM
# from qwen_agent.tools.base import BaseTool
# from qwen_agent.utils.schema import CompletionConfig
# from qwen_agent.memory.base import BaseMemory

# 改用阿里百炼平台 dashscope 调用大模型（参照 01_智能启动过程展示.py 的改写方式）
import os
import json
import dashscope

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# ========== 持久化记忆（原 PersistentJSONMemory 的逻辑全部保留，无需框架） ==========
# 这部分原代码本身就是标准 Python（json 读写），只是继承了一个不存在的 BaseMemory——
# 去掉继承、去掉 add_message 里的强制落盘时机调整，核心的 load/save 逻辑原样保留
class PersistentJSONMemory:
    """自定义Memory：将上下文持久化至JSON文件，支持中断后恢复"""
    def __init__(self, session_id: str, path: str = "./memory"):
        os.makedirs(path, exist_ok=True)
        self.session_id = session_id
        self.memory_file = os.path.join(path, f"{session_id}.json")
        self.messages = self.load()

    def load(self):
        """启动时从 JSON 文件恢复历史消息（中断恢复的关键）"""
        if os.path.exists(self.memory_file):
            with open(self.memory_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return []

    def save(self):
        """把当前全部消息写入 JSON 文件（持久化的关键）"""
        with open(self.memory_file, "w", encoding="utf-8") as f:
            json.dump(self.messages, f, ensure_ascii=False, indent=2)

    def add_message(self, message: dict):
        self.messages.append(message)
        self.save()

    def get(self):
        return self.messages


# ========== 工具注册（原 LogUserInputTool 类改写为函数 + 说明书 + 注册表） ==========
# 原写法：继承虚构 BaseTool 的工具类（run 取 params + description/parameters 属性）
# 改写：普通函数（带参数）+ tools 说明书 + tool_registry 注册表

def log_user_input(content: str) -> str:
    """工具执行体：记录交互内容"""
    return f"记录完成：{content}"

tool_registry = {"log_user_input": log_user_input}

# 给模型看的工具说明书（等价于原写法 description + parameters 两个属性）
tools = [
    {"type": "function", "function": {
        "name": "log_user_input",
        "description": "将用户输入写入交互日志",
        "parameters": {"type": "object", "properties": {
            "content": {"type": "string", "description": "用户内容"}
        }, "required": ["content"]}}
    }
]

SYSTEM_MESSAGE = "你是一位具备上下文持久化能力的智能体，可以记录并恢复中断的多轮交互内容"


# ========== 构建Agent（原 build_agent 改写） ==========
# 原写法：QwenLLM + Agent(name, llm, tools, memory, system_message) 拼装
# 改写：config 字典 + PersistentJSONMemory，agent_chat 函数本身承担 Agent 循环
def build_agent(session_id: str):
    config = {
        "name": "SessionRecoveryAgent",
        "model": "qwen-plus",
        "temperature": 0.3,
        "max_tokens": 512,
        "system_message": SYSTEM_MESSAGE
    }
    memory = PersistentJSONMemory(session_id=session_id)   # 同一 session_id -> 恢复同一份记忆
    return config, memory


# ========== Agent 循环：带持久化记忆与工具调用 ==========
def agent_chat(config, user_input, memory_obj):
    """
    单次对话的 Agent 循环：从持久层恢复记忆 -> 对话 -> 结果写回持久层

    参数:
        config: 智能体配置字典
        user_input: 用户本轮输入
        memory_obj: PersistentJSONMemory 持久化记忆对象
    返回:
        模型回复文本
    """
    # 从持久层取历史消息（这就是"中断恢复"——上一次运行的对话还在）
    memory = list(memory_obj.get())
    if not memory:
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

        # 无工具调用 -> 最终回答，本轮完整消息写回持久层后返回
        if not tool_calls:
            memory = memory + [{"role": "assistant", "content": message.content}]
            memory_obj.messages = memory      # 原写法由框架在 add_message 时自动落盘
            memory_obj.save()                 # 改写后每轮结束统一落盘一次
            return message.content

        # 有工具调用 -> 本地执行，arguments 是 JSON 字符串需解析后传参
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


# 模拟用户对话过程（中断→恢复）
def simulate_session():
    session_id = "user_20250501"

    # 为让演示可重复运行，每次先清掉旧会话文件（持久化演示发生在本次运行内部）
    memory_file = os.path.join("./memory", f"{session_id}.json")
    if os.path.exists(memory_file):
        os.remove(memory_file)

    agent_config, memory = build_agent(session_id)

    print(agent_chat(agent_config, "我想订一张5月5日去上海的机票", memory))
    print(agent_chat(agent_config, "时间大约是早上8点左右", memory))
    print(agent_chat(agent_config, "帮我记录这个需求", memory))

    print("\n模拟中断后重新启动...\n")

    # 关键：用同一个 session_id 重新构建 -> PersistentJSONMemory.load() 从磁盘恢复全部历史
    agent_config2, memory2 = build_agent(session_id)

    print(agent_chat(agent_config2, "现在继续，出发地是北京", memory2))

if __name__ == "__main__":
    simulate_session()
