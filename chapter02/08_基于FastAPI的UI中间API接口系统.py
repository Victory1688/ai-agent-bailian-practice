# 【例2-8】
# agent_ui_api.py
# 08_基于FastAPI的UI中间API接口系统.py

# 原写法：qwen_agent 的这些 API 是虚构的（真实包没有这些类），运行报 ImportError，无法执行
# from qwen_agent import Agent, Tool
# from qwen_agent.llm import QwenLLM
# from qwen_agent.utils.schema import CompletionConfig

# FastAPI / pydantic / CORS 是真实可用的第三方库，原样保留——这是"把 Agent 包成 HTTP 服务"的关键
from fastapi import FastAPI, Request
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional

# 改用阿里百炼平台 dashscope 调用大模型（参照 01-07 的改写方式）
import json
import os
import dashscope

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

## UI API 请求结构（Pydantic 模型，原代码原样保留）
class ChatRequest(BaseModel):
    session_id: str
    message: str

class ChatResponse(BaseModel):
    session_id: str
    reply: str

## Agent 工具注册（原 AddRecordTool 类改写为函数 + 说明书 + 注册表）
# 原写法：继承虚构 Tool 的工具类
# 改写：普通函数（带参数）+ tools 说明书 + tool_registry 注册表
#       但 run() 方法里的记账逻辑原样保留——这是"记账工具"的核心教学点

def add_record(category: str, amount: str) -> str:
    """工具执行体：记录一笔消费信息（原 AddRecordTool.run 逻辑全部保留）"""
    return f"已记录消费：{category} - {amount}元"

# 工具注册表
tool_registry = {"add_record": add_record}

# 给模型看的工具说明书（原 AddRecordTool 的 description + parameters 属性合并到此）
tools = [
    {"type": "function", "function": {
        "name": "add_record",
        "description": "记录一笔消费信息",
        "parameters": {"type": "object", "properties": {
            "category": {"type": "string", "description": "消费类别"},
            "amount": {"type": "string", "description": "金额（单位：元）"}
        }, "required": ["category", "amount"]}
    }},
]

SYSTEM_MESSAGE = "你是一个家庭记账助手，接收用户输入并记录消费类型与金额"


# ========== Agent 循环（同 01-07 篇模式） ==========
def agent_chat(config, user_input, memory=None):
    """单次对话的 Agent 循环：模型决策 → 记账工具执行 → 结果回传 → 生成回答"""
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
# 原写法：Agent(name, llm=QwenLLM(...), tools=[AddRecordTool()], system_message=...) 拼装
# 改写：config 字典 + agent_chat 函数本身就是 Agent
def build_agent():
    config = {
        "name": "FinanceBot",
        "model": "qwen-plus",
        "temperature": 0.3,
        "max_tokens": 512,
        "system_message": SYSTEM_MESSAGE
    }
    return config


## FastAPI 服务构建（原代码原样保留，仅 agent_instance 换成 config 字典）
app = FastAPI()
agent_config = build_agent()

# CORS 允许跨域（用于网页调用）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# 根接口
@app.get("/")
def index():
    return {"message": "Agent API 运行中"}

# 聊天API：接收用户输入→Agent处理→返回输出
@app.post("/chat", response_model=ChatResponse)
def chat_with_agent(req: ChatRequest):
    # 原写法：reply = agent_instance.chat(req.message)   ← 虚构框架的黑盒调用
    # 改写：调 agent_chat 循环（session_id 原代码就预留而未用于记忆，这里同样先不使用）
    reply, _memory = agent_chat(agent_config, req.message)
    return ChatResponse(session_id=req.session_id, reply=reply)




# 使用如下命令启动脚本：
# uvicorn agent_ui_api:app --reload --port 8080
# uvicorn 08_基于FastAPI的UI中间API接口系统:app --reload --port 8080
# d:/MyCode/.venv/Scripts/python.exe "d:/MyCode/codeandppt/AI Agent Development Code/aiTest/char02/08_基于FastAPI的UI中间API接口系统.py"

# 使用如下方式请求API：
#curl -X POST http://localhost:8080/chat   -H "Content-Type: application/json"   -d '{"session_id": "user123", "message": "刚刚买菜花了20元"}'
