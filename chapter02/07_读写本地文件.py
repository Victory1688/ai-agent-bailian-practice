# 【例2-7】 核心概念：接入文件系统和代码执行环境，使智能体能够直接操作本地文件和运行脚本，
# 完成文档处理、数据分析等高级任务。这是智能体从"语言模型"进化为"自动化助手"的关键一步。

# agent_file_exec.py

# 原写法：qwen_agent 的这些 API 是虚构的（真实包没有这些类），运行报 ImportError，无法执行
# import os
# import traceback
# from qwen_agent import Agent, Tool
# from qwen_agent.llm import QwenLLM
# from qwen_agent.utils.schema import CompletionConfig
# from qwen_agent.tools.base import BaseTool

# 改用阿里百炼平台 dashscope 调用大模型（参照 01-06 的改写方式）
import os
import traceback    # 标准库，原代码已导入，保留（exec 出错时截取精简堆栈的关键）
import json
import dashscope

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# ========== 工具注册（三个 BaseTool 改写为函数 + 说明书 + 注册表） ==========
# 原写法：继承虚构 BaseTool 的 ReadFileTool / WriteFileTool / ExecCodeTool 三个工具类
# 改写：普通函数（带参数）+ tools 说明书 + tool_registry 注册表
#       但 run() 方法里的文件读写 / exec 逻辑原样保留——这是"操作本地文件与执行代码"的核心教学点

def read_file(filepath: str) -> str:
    """
    工具1执行体：读取指定文件内容（原 ReadFileTool.run 逻辑全部保留）

    参数:
        filepath: 文件路径
    返回:
        文件内容字符串；文件不存在或读取失败时返回错误说明（工具函数永不抛异常）
    """
    if not os.path.exists(filepath):
        return f"文件不存在：{filepath}"
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"读取失败：{str(e)}"


def write_file(filepath: str, content: str) -> str:
    """
    工具2执行体：将文本写入指定文件（原 WriteFileTool.run 逻辑全部保留）

    参数:
        filepath: 文件路径
        content: 要写入的文本内容
    返回:
        成功/失败的结果说明字符串
    """
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return f"内容已成功写入文件：{filepath}"
    except Exception as e:
        return f"写入失败：{str(e)}"


def exec_code(code: str) -> str:
    """
    工具3执行体：执行用户提供的Python代码（原 ExecCodeTool.run 逻辑全部保留）

    参数:
        code: 待执行的 Python 代码字符串
    返回:
        执行成功时返回 local_vars 中的输出变量；出错时返回精简堆栈信息
    """
    try:
        local_vars = {}
        exec(code, {}, local_vars)
        return "执行成功，输出变量：" + str(local_vars)
    except Exception:
        return "执行出错：" + traceback.format_exc(limit=2)


# 工具注册表（原 tools=[ReadFileTool(), WriteFileTool(), ExecCodeTool()] 三个类实例的等价物）
tool_registry = {
    "read_file": read_file,
    "write_file": write_file,
    "exec_code": exec_code,
}

# 给模型看的工具说明书（原三个工具类的 description + parameters 属性合并到此）
tools = [
    {"type": "function", "function": {
        "name": "read_file",
        "description": "读取指定文件内容",
        "parameters": {"type": "object", "properties": {
            "filepath": {"type": "string", "description": "文件路径"}
        }, "required": ["filepath"]}
    }},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "将文本写入指定文件",
        "parameters": {"type": "object", "properties": {
            "filepath": {"type": "string", "description": "文件路径"},
            "content": {"type": "string", "description": "写入内容"}
        }, "required": ["filepath", "content"]}
    }},
    {"type": "function", "function": {
        "name": "exec_code",
        "description": "执行用户提供的Python代码（仅限受控环境）",
        "parameters": {"type": "object", "properties": {
            "code": {"type": "string", "description": "待执行Python代码"}
        }, "required": ["code"]}
    }},
]

SYSTEM_MESSAGE = "你是一位具备文件系统与代码执行能力的助手，负责文本文件处理与Python代码运行"


# ========== Agent 循环（同 01-06 篇模式） ==========
def agent_chat(config, user_input, memory=None):
    """单次对话的 Agent 循环：函数调用 → 文件读写/代码执行 → 结果回传 → 生成回答"""
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


# ========== 构建 Agent（原 build_agent 改写） ==========
# 原写法：Agent(name, llm=QwenLLM(...), tools=[三个工具类实例], system_message=...) 拼装
# 改写：config 字典 + agent_chat 函数本身就是 Agent
def build_agent():
    config = {
        "name": "FileExecAgent",
        "model": "qwen-plus",
        "temperature": 0.2,       # 低随机性，文件处理任务要稳
        "max_tokens": 512,
        "system_message": SYSTEM_MESSAGE
    }
    return config


# ========== 测试流程（原 run_demo 改写） ==========
def run_demo():
    # 为让演示可重复运行，每次先删掉上次生成的 test.txt
    if os.path.exists("test.txt"):
        os.remove("test.txt")

    config = build_agent()
    memory = None  # 首轮传 None → agent_chat 内部注入 system_message

    reply, memory = agent_chat(config, "请将以下内容写入文件test.txt：你好，这是智能体写入的内容", memory)
    print(">>", reply)
    reply, memory = agent_chat(config, "读取文件test.txt中的内容", memory)
    print(">>", reply)
    reply, memory = agent_chat(config, "请运行如下代码：a = 5\nb = 3\nc = a * b", memory)
    print(">>", reply)

if __name__ == "__main__":
    run_demo()
