# 【例3-6】 支持 Qwen 模型函数调用标准结构
# 核心教学点：Function Calling 协议（tools 说明书 → 模型自主决策 → 本地执行 → 结果回传）
# 与 char02 各篇的 Function Calling 是同一个核心技能，这里以 FastAPI 服务化形态呈现

# ========== 原写法：本地模型 + 假 Function Calling（关键词匹配硬编码） ==========
# 教学说明：原代码的 FastAPI 骨架、function_registry、dispatch_function 都是好教材。
# 但"函数调用提取"是假的——它用关键词匹配（"调用函数" / "get_weather"）硬编码返回固定结构，
# 模型根本没看到工具说明书，也没有自主决策调不调函数。改写时保留骨架，补齐真正的 Function Calling 循环。
#
# from fastapi import FastAPI, Request
# from pydantic import BaseModel
# from transformers import AutoTokenizer, AutoModelForCausalLM
# import uvicorn
# import torch
# import json
#
# # 模型初始化（需要 GPU：.cuda() 在 CPU 机器上直接报错）
# model_path = "Qwen/Qwen-1.8B"
# tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
# model = AutoModelForCausalLM.from_pretrained(...).cuda().eval()
#
# # Prompt构建（裸基座模型不认识 messages，手动拼角色标记——同 char03-05）
# def build_prompt(messages):
#     ...
#
# # 主处理函数里的"模拟提取"（假 Function Calling）：
# # if "调用函数" in output_text:
# #     if "get_weather" in output_text:  return {"function_call": {"name": "get_weather", "arguments": {"city": "北京"}}}
# #     if "calculate_sum" in output_text: return {"function_call": {"name": "calculate_sum", "arguments": {"a": "8", "b": "12"}}}
# # return {"response": output_text}
# 问题：模型没看到工具说明 → 不会主动说"调用函数"；返回值硬编码 → 换个输入就对不上

# ========== 改写：FastAPI 骨架保留 + 真 Function Calling（dashscope 云端） ==========
# 改写核心：
#   1. function_registry 的 value 里补上完整的 tools 说明书（name/description/parameters 的 JSON Schema）
#   2. dispatch_function 逻辑原样保留（本地执行体）
#   3. FastAPI 端点改为 POST /v1/chat/function_call，内部走真正的 Function Calling 循环
#   4. 模型自主决策：要不要调函数、调哪个、参数什么——全部由 qwen-plus 自主决定
from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn
import json
import os
import dashscope

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# ========== FastAPI 服务 + 数据结构（原样保留） ==========
app = FastAPI()

class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    model: str
    messages: list[Message]
    stream: bool = False


# ========== 函数注册（function_registry 重写为完整结构） ==========
# 原写法：value 只有 description + parameters 列表（不是真正的 JSON Schema）
# 改写：value 拆成两块——tools 说明书（给模型看）+ execute 执行体（本地跑）
#       这正是 char02 Function Calling 的三件套：注册表 + 说明书 + 执行体
def get_weather(city: str) -> str:
    """工具1执行体：模拟查天气（原代码逻辑原样保留）"""
    return f"{city}的当前天气是晴，气温25°C"

def calculate_sum(a: float, b: float) -> str:
    """工具2执行体：两数求和（原代码逻辑原样保留）"""
    return f"{a} + {b} = {int(a) + int(b)}"

# 工具注册表：函数名 → 执行体（原 dispatch_function 的 if/elif 链 → 字典查表）
tool_registry = {
    "get_weather": get_weather,
    "calculate_sum": calculate_sum,
}

# 给模型看的工具说明书（OpenAI Function Calling 协议的标准格式）
# 模型根据这份说明书自主决定：要不要调 / 调哪个 / 参数填什么
tools = [
    {"type": "function", "function": {
        "name": "get_weather",
        "description": "获取指定城市的当前天气",
        "parameters": {"type": "object", "properties": {
            "city": {"type": "string", "description": "城市名称，如 北京、上海、深圳"}
        }, "required": ["city"]}
    }},
    {"type": "function", "function": {
        "name": "calculate_sum",
        "description": "计算两个数字的和",
        "parameters": {"type": "object", "properties": {
            "a": {"type": "number", "description": "第一个数字"},
            "b": {"type": "number", "description": "第二个数字"}
        }, "required": ["a", "b"]}
    }},
]


# ========== 核心：Function Calling 循环（原代码没有，改写后补齐） ==========
def run_function_call(messages_list):
    """
    真正的 Function Calling 循环：
    1. 模型看 tools 说明书 → 自主决策要不要调函数
    2. 如果调 → 本地 dispatch 执行 → 结果回传给模型 → 模型生成最终回答
    3. 如果不调 → 直接返回模型的自然语言回答

    参数:
        messages_list: ChatRequest.messages 转成的 [{"role": ..., "content": ...}, ...]
    返回:
        dict: {
            "response": "最终自然语言回答",
            "tool_calls": [{"name": "...", "arguments": {...}}, ...]  # 本轮发生了哪些函数调用
        }
    """
    # 第 1 轮：让模型看 tools，自主决策
    response = dashscope.Generation.call(
        model='qwen-plus',
        messages=messages_list,
        tools=tools,                                 # ← 原代码完全没有这行！
        temperature=0.3,
        max_tokens=512,
        result_format='message'
    )
    message = response.output.choices[0].message
    tool_calls = getattr(message, 'tool_calls', None)

    # 模型决定不调函数 → 直接返回自然语言回答
    if not tool_calls:
        return {"response": message.content, "tool_calls": []}

    # 模型决定调函数 → 本地执行 + 结果回传
    messages_list = messages_list + [message]       # 把模型的 tool_call 意图加进对话历史
    executed_calls = []                              # 记录本轮发生了哪些调用（用于返回给客户端）

    for call in tool_calls:
        fn_name = call['function']['name']
        fn_args = json.loads(call['function'].get('arguments') or '{}')
        fn = tool_registry.get(fn_name)
        # 本地执行（原 dispatch_function 的 if/elif → 字典查表，逻辑更清晰）
        tool_result = fn(**fn_args) if fn else f"未注册的函数: {fn_name}"
        executed_calls.append({"name": fn_name, "arguments": fn_args, "result": tool_result})
        # 结果回传给模型（tool 角色）
        messages_list = messages_list + [{
            "role": "tool",
            "content": tool_result,
            "name": fn_name,
            "tool_call_id": call.get('id', fn_name)
        }]

    # 第 2 轮：模型拿到函数执行结果，生成最终自然语言回答
    final_response = dashscope.Generation.call(
        model='qwen-plus',
        messages=messages_list,
        temperature=0.3,
        max_tokens=512,
        result_format='message'
    )
    final_content = final_response.output.choices[0].message.content
    return {"response": final_content, "tool_calls": executed_calls}


# ========== FastAPI 端点（改写：内部走真 Function Calling） ==========
@app.post("/v1/chat/function_call")
async def function_call(req: ChatRequest):
    """Function Calling 端点：接收请求 → 模型决策 → 本地执行 → 返回最终回答"""
    messages_list = [{"role": m.role, "content": m.content} for m in req.messages]
    result = run_function_call(messages_list)
    return result


# ========== 启动服务 ==========
# 原写法：uvicorn.run("filename:app", ...) —— filename 占位符直接运行报 ImportError
# 改写：直接传 app 对象
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)


# ========== 测试请求示例 ==========
# 服务启动后，POST http://127.0.0.1:8080/v1/chat/function_call
# 请求体：
# {
#   "model": "qwen-plus",
#   "messages": [
#     {"role": "system", "content": "你可以调用函数获取天气或进行加法"},
#     {"role": "user", "content": "请告诉我北京的天气"}
#   ],
#   "stream": false
# }
# 预期响应（模型自主决策调用 get_weather → 拿到结果后生成自然语言回答）：
# {
#   "response": "北京当前天气晴朗，气温25°C，适合出门活动。",
#   "tool_calls": [{"name": "get_weather", "arguments": {"city": "北京"}, "result": "北京的当前天气是晴，气温25°C"}]
# }
# 再加一条"帮我算一下 8 + 12" → 模型自主决策调用 calculate_sum
# 再加一条"今天心情不错" → 模型决策不调函数，直接返回自然语言（tool_calls 为空数组）


# ========== 测试请求示例 ==========
# Windows cmd 环境下，多行写法会有问题，可以压缩成单行版本：
# curl -X POST http://127.0.0.1:8080/v1/chat/function_call -H "Content-Type: application/json" -d "{\"model\":\"qwen-plus\",\"messages\":[{\"role\":\"system\",\"content\":\"你可以调用函数获取天气或进行加法\"},{\"role\":\"user\",\"content\":\"请告诉我北京的天气\"}],\"stream\":false}"
# \"stream\":true
# curl -X POST http://127.0.0.1:8080/v1/chat/function_call -H "Content-Type: application/json" -d "{\"model\":\"qwen-plus\",\"messages\":[{\"role\":\"system\",\"content\":\"你可以调用函数获取天气或进行加法\"},{\"role\":\"user\",\"content\":\"请告诉我北京的天气\"}],\"stream\":true}"
