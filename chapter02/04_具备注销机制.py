# 【例2-4】 智能体注销与资源释放
# 智能体在完成任务或会话结束后，需执行安全、完整的注销操作，释放占用的计算与存储资源，
# 规避内存与连接泄漏，保障系统长期的稳定性、性能与安全性。

# agent_shutdown_cleanup.py

# 原写法：qwen_agent 的这些 API 是虚构的（真实包没有这些类），运行报 ImportError，无法执行
# import os
# import json
# import datetime
# from typing import List
# from qwen_agent import Agent, Tool
# from qwen_agent.llm import QwenLLM
# from qwen_agent.utils.schema import CompletionConfig
# from qwen_agent.tools.base import BaseTool
# from qwen_agent.memory.base import BaseMemory

# 改用阿里百炼平台 dashscope 调用大模型（参照 01_智能启动过程展示.py 的改写方式）
import os
import json
import datetime
import dashscope

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# Agent 使用的本地存储路径
MEMORY_PATH = "./memory_cleanup"

# ========== LoggingMemory（原逻辑保留，去掉虚构 BaseMemory 继承） ==========
class LoggingMemory:
    """支持写入日志文件的持久化记忆，注销时 clear() 删除 JSON 文件"""
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.memory_file = os.path.join(MEMORY_PATH, f"{session_id}.json")
        self.logs = []                           # 运行时的消息列表（相当于 self.messages）

    def add_message(self, message: dict):
        self.logs.append(message)

    def get(self):
        return self.logs

    def save(self):
        """把当前全部消息写入 JSON 文件（注销前先落盘一份）"""
        os.makedirs(MEMORY_PATH, exist_ok=True)
        with open(self.memory_file, "w", encoding="utf-8") as f:
            json.dump(self.logs, f, ensure_ascii=False, indent=2)

    def clear(self):
        """注销时删除 JSON 文件（释放存储资源）"""
        if os.path.exists(self.memory_file):
            os.remove(self.memory_file)


# ========== 工具注册（原 TaskTool 类改写为函数 + 说明书 + 注册表） ==========
# 原写法：继承虚构 BaseTool 的工具类
# 改写：普通函数（带参数）+ tools 说明书 + tool_registry 注册表

def handle_task(task: str) -> str:
    """工具执行体：处理一个示例任务"""
    return f"任务『{task}』已完成"

tool_registry = {"handle_task": handle_task}

# 给模型看的工具说明书
tools = [
    {"type": "function", "function": {
        "name": "handle_task",
        "description": "处理一个示例任务",
        "parameters": {"type": "object", "properties": {
            "task": {"type": "string", "description": "任务内容"}
        }, "required": ["task"]}}
    }
]

SYSTEM_MESSAGE = "你是一位临时任务助手，任务完成后需要注销并清理所有资源"


# ========== Agent 循环 ==========
def agent_chat(config, user_input, memory_obj):
    """单次对话的 Agent 循环，带工具调用（同 02/03 篇模式）"""
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

        if not tool_calls:
            memory = memory + [{"role": "assistant", "content": message.content}]
            memory_obj.logs = memory
            return message.content

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


# ========== ManagedAgent（注销机制的核心封装） ==========
class ManagedAgent:
    """
    带注销机制的 Agent 包装类：chat() 对话 → shutdown() 释放资源

    原写法：self.agent.chat(user_input) 是框架黑盒
    改写：chat() 方法内部调 agent_chat()，注销逻辑全显式可见
    """
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.memory = LoggingMemory(session_id)
        self.config = {
            "name": "CleanableAgent",
            "model": "qwen-plus",
            "temperature": 0.2,       # 低随机性，任务助手不要太跳
            "max_tokens": 256,        # 短回答，节省 tokens
            "system_message": SYSTEM_MESSAGE
        }

    def chat(self, user_input: str) -> str:
        result = agent_chat(self.config, user_input, self.memory)
        return result

    def shutdown(self):
        """
        注销流程：保存 → 清理 → 写摘要日志

        教学点：不是"直接删"，而是先落盘一份日志供事后审计，再删 JSON 释放存储
        """
        print(">> 执行Agent注销流程...")

        # 步骤 1：先把对话历史保存为 JSON（注销前留底）
        self.memory.save()

        # 步骤 2：删除 JSON 文件（释放存储资源）
        self.memory.clear()

        # 步骤 3：写一份精简的文本摘要日志（便于事后审计）
        log_file = os.path.join(MEMORY_PATH, f"{self.session_id}_log.txt")
        with open(log_file, "w", encoding="utf-8") as f:
            for item in self.memory.logs:
                ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                role = item.get("role", "unknown")
                content_preview = (item.get("content", "") or "")[:50]
                f.write(f"[{ts}] {role}: {content_preview}\n")

        print(">> Agent已成功注销并释放资源")


# 模拟流程：运行→完成→注销
def run_task_session():
    session_id = "temp_agent_001"

    # 为让演示可重复运行，每次先清掉旧会话残留
    for suffix in [".json", "_log.txt"]:
        f = os.path.join(MEMORY_PATH, f"{session_id}{suffix}")
        if os.path.exists(f):
            os.remove(f)

    agent = ManagedAgent(session_id)

    print(agent.chat("请帮我完成今天的日报任务"))
    print(agent.chat("现在关闭智能体"))

    agent.shutdown()

    # 演示注销后 JSON 已删、日志文件存在
    json_path = os.path.join(MEMORY_PATH, f"{session_id}.json")
    log_path = os.path.join(MEMORY_PATH, f"{session_id}_log.txt")
    print(f"\n验证：JSON 文件存在={os.path.exists(json_path)}（应为 False）")
    print(f"验证：  日志文件存在={os.path.exists(log_path)}（应为 True）")

if __name__ == "__main__":
    run_task_session()
