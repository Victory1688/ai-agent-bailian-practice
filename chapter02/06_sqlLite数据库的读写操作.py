# 【例2-6】 与数据库系统的读写操作
# 核心概念：与数据库交互是智能体实现结构化数据管理的关键，
# 使其能够高效地存储业务数据、精准查询历史记录以及灵活更新动态信息，
# 为复杂业务逻辑提供坚实的数据底座。

# agent_sqlite_db.py

# 原写法：qwen_agent 的这些 API 是虚构的（真实包没有这些类），运行报 ImportError，无法执行
# import sqlite3
# from qwen_agent import Agent, Tool
# from qwen_agent.llm import QwenLLM
# from qwen_agent.utils.schema import CompletionConfig
# from qwen_agent.tools.base import BaseTool

# 改用阿里百炼平台 dashscope 调用大模型（参照 01-05 的改写方式）
import sqlite3    # 标准库，原代码已导入，保留（真正操作数据库的关键）
import json
import os
import dashscope

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

DB_PATH = "./employee.db"

# ========== 初始化数据库（原 init_db 逻辑完全保留） ==========
def init_db():
    """首次运行时创建 employees 表（幂等：表已存在则跳过）"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            department TEXT,
            title TEXT
        )
    ''')
    conn.commit()
    conn.close()


# ========== 工具注册（两个 BaseTool 改写为函数 + 说明书 + 注册表） ==========
# 原写法：继承虚构 BaseTool 的 AddEmployeeTool + QueryEmployeeTool 两个工具类
# 改写：普通函数（带参数）+ tools 说明书 + tool_registry 注册表
#       但 run() 方法里的 sqlite3 操作逻辑原样保留——这是"数据库交互"的核心教学点

def add_employee(name: str, department: str = "", title: str = "") -> str:
    """工具1执行体：向 employees 表插入一条记录"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        # 使用 ? 占位符是 SQL 注入防护的标准写法（绝不能用字符串拼接）
        cursor.execute(
            "INSERT INTO employees (name, department, title) VALUES (?, ?, ?)",
            (name, department, title)
        )
        conn.commit()
        conn.close()
        return f"员工{name}添加成功"
    except Exception as e:
        return f"添加失败：{str(e)}"


def query_employee(name: str = "") -> str:
    """工具2执行体：按姓名查询所有员工信息；name 为空时返回全部"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        if name:
            # 同样用 ? 参数化查询，防 SQL 注入
            cursor.execute(
                "SELECT name, department, title FROM employees WHERE name = ?", (name,)
            )
        else:
            cursor.execute("SELECT name, department, title FROM employees")
        rows = cursor.fetchall()
        conn.close()
        if not rows:
            return "未找到匹配员工"
        return "\n".join([f"{n} | {d} | {t}" for n, d, t in rows])
    except Exception as e:
        return f"查询失败：{str(e)}"


# 工具注册表
tool_registry = {
    "add_employee": add_employee,
    "query_employee": query_employee,
}

# 给模型看的工具说明书（原两个工具类的 description + parameters 合并到此）
tools = [
    {"type": "function", "function": {
        "name": "add_employee",
        "description": "添加一名员工信息，需要姓名、可选部门和职务",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "员工姓名"},
            "department": {"type": "string", "description": "所属部门"},
            "title": {"type": "string", "description": "职务"}
        }, "required": ["name"]}
    }},
    {"type": "function", "function": {
        "name": "query_employee",
        "description": "查询员工信息，可按姓名精确查询；不传姓名则返回全部员工",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "员工姓名（可选，不传则查全部）"}
        }}
    }},
]

SYSTEM_MESSAGE = "你是一位人事数据库助手，能添加和查询员工信息，信息包含姓名、部门与职务"


# ========== Agent 循环（同 02-05 篇模式） ==========
def agent_chat(config, user_input, memory=None):
    """单次对话的 Agent 循环：函数调用 → 数据库读写 → 结果回传 → 生成回答"""
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


# ========== 构建 Agent（原 build_db_agent 改写） ==========
def build_db_agent():
    config = {
        "name": "EmployeeDBAgent",
        "model": "qwen-plus",
        "temperature": 0.2,
        "max_tokens": 512,
        "system_message": SYSTEM_MESSAGE
    }
    return config


# ========== 模拟用户对话流程 ==========
def run_demo():
    # 为让演示可重复运行，每次先清掉旧数据库
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    init_db()
    config = build_db_agent()
    memory = None

    reply, memory = agent_chat(config, "请添加一名员工，姓名是王小明，部门是技术部，职位是高级工程师", memory)
    print(">>", reply)
    reply, memory = agent_chat(config, "请查询王小明的详细信息", memory)
    print(">>", reply)
    reply, memory = agent_chat(config, "我想看看所有员工列表", memory)
    print(">>", reply)

if __name__ == "__main__":
    run_demo()
