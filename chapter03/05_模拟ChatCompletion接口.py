# 【例3-5】 模拟 ChatCompletion 接口：用 FastAPI 实现 OpenAI 兼容的对话服务
# 核心教学点：OpenAI ChatCompletion 协议（请求体结构 / SSE 流式 / 响应格式），
#             让任何"会说 OpenAI 方言"的客户端都能无缝切换到你的服务

# 原写法：本地加载 Qwen-1.8B 做推理（无 GPU 环境跑不动，模型加载部分改用百炼云端调用）
# from fastapi import FastAPI, Request
# from pydantic import BaseModel
# from transformers import AutoTokenizer, AutoModelForCausalLM
# from fastapi.responses import StreamingResponse
# import torch
# import uvicorn
# import json
# import time
#
# # Step 1: 初始化模型与tokenizer（需要 GPU：.cuda() 在 CPU 机器上直接报错）
# model_path = "Qwen/Qwen-1.8B"
# tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
# model = AutoModelForCausalLM.from_pretrained(model_path, trust_remote_code=True,
#                                              torch_dtype=torch.float16).cuda().eval()

# 改写：FastAPI / Pydantic / StreamingResponse 全部保留（这是本篇教学重点），
#       只把"本地模型推理"替换为"dashscope 云端调用"
from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
import uvicorn
import json
import os
import dashscope

# 从环境变量中获取 DASHSCOPE_API_KEY（云端替代了原本地的模型加载）
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# Step 2: 构造FastAPI服务与数据结构（原样保留——OpenAI 请求体协议的核心）
app = FastAPI()

class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    model: str
    messages: list[Message]
    temperature: float = 0.7
    max_tokens: int = 256
    stream: bool = False

# Step 3: 构造Prompt拼接函数
# 原写法：本地基座模型不认识 messages 数组，必须手动拼成带角色标记的大字符串
# def build_prompt(messages):
#     history = []
#     for msg in messages:
#         role = msg.role
#         content = msg.content
#         if role == "system":
#             history.append(f"[系统提示]：{content}")
#         elif role == "user":
#             history.append(f"[用户]：{content}")
#         elif role == "assistant":
#             history.append(f"[助手]：{content}")
#     prompt = "\n".join(history) + "\n[助手]："
#     return prompt
# 改写：dashscope 原生支持 messages 数组（role/content 结构直接透传），
#       不再需要手动拼接——这正是 Chat 接口协议的价值：角色结构由服务端理解
def build_messages(req: ChatRequest):
    """把 Pydantic 请求体转成 dashscope 需要的 messages 列表"""
    return [{"role": m.role, "content": m.content} for m in req.messages]

# Step 4: 流式生成器函数
# 原写法："假流式"——先整段生成完毕，再切成 10 字符一片用 time.sleep 模拟打字机效果
# def stream_response(prompt, max_tokens, temperature):
#     input_ids = tokenizer(prompt, return_tensors="pt").input_ids.cuda()
#     with torch.no_grad():
#         output_ids = model.generate(input_ids=input_ids, max_new_tokens=max_tokens,
#                                     temperature=temperature, do_sample=True)
#     response = tokenizer.decode(output_ids[0], skip_special_tokens=True).split("[助手]：")[-1].strip()
#     for i in range(0, len(response), 10):
#         yield json.dumps({"choices": [{"delta": {"content": response[i:i+10]}}]}) + "\n"
#         time.sleep(0.05)
# 改写："真流式"——dashscope stream=True + incremental_output=True，
#       模型每生成一段就实时推给客户端（首字延迟从"整段生成完"降到"第一个字"）
#       并补上 OpenAI 协议标准的 data: 前缀与 [DONE] 结束标记
def stream_response(messages, max_tokens, temperature):
    """真流式生成器：逐块产出 OpenAI SSE 格式的 data 行"""
    responses = dashscope.Generation.call(
        model='qwen-plus',
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        result_format='message',
        stream=True,                    # 开启流式输出
        incremental_output=True         # 增量模式：每次只返回新增内容（而非全量重复）
    )
    for response in responses:
        chunk = response.output.choices[0].message.content or ""
        if chunk:
            # OpenAI 流式协议：data: + JSON（delta 表示增量）+ 两个换行
            yield f"data: {json.dumps({'choices': [{'delta': {'content': chunk}}]}, ensure_ascii=False)}\n\n"
    # OpenAI 协议的流式结束标记
    yield "data: [DONE]\n\n"

# Step 5: 构造主响应接口（OpenAI 兼容的 /v1/chat/completions）
@app.post("/v1/chat/completions")
async def chat_completion(req: ChatRequest):
    messages = build_messages(req)
    if req.stream:
        # 流式：返回 SSE（Server-Sent Events）
        return StreamingResponse(stream_response(messages, req.max_tokens, req.temperature),
                                 media_type="text/event-stream")
    else:
        # 原写法：本地 model.generate 整段生成
        # 改写：dashscope 云端调用，但响应结构保持 OpenAI 格式（教学点：协议兼容）
        response = dashscope.Generation.call(
            model='qwen-plus',
            messages=messages,
            max_tokens=req.max_tokens,
            temperature=req.temperature,
            result_format='message'
        )
        result = response.output.choices[0].message.content
        return {"id": "cmpl-local-001", "object": "chat.completion",
                "choices": [{"message": {"role": "assistant", "content": result}}]}

# Step 6: 启动服务
# 原写法：uvicorn.run("filename:app", ...) 中 filename 是占位符，直接运行会报 ImportError
# 改写：直接传 app 对象，避免中文文件名无法作为模块导入的问题
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)


# ========== 测试请求示例 ==========
# 服务启动后，用下面的请求体 POST http://127.0.0.1:8080/v1/chat/completions
# （内容中的引号使用中文引号，避免与 JSON/代码中的英文双引号冲突）
# {
#   "model": "qwen-plus",
#   "messages": [
#     {"role": "system", "content": "你是一名专业助手"},
#     {"role": "user", "content": "请解释一下LoRA技术的基本原理"}
#   ],
#   "temperature": 0.7,
#   "max_tokens": 200,
#   "stream": false
# }
# 流式测试：把 "stream" 改为 true，观察响应变成逐块到达的 SSE 数据

# windows下的测试请求示例：
# 1、 "stream" ： false
# curl -X POST http://127.0.0.1:8080/v1/chat/completions -H "Content-Type: application/json" -d "{\"model\":\"qwen-plus\",\"messages\":[{\"role\":\"system\",\"content\":\"你是一名专业助手\"},{\"role\":\"user\",\"content\":\"请解释一下LoRA技术的基本原理\"}],\"temperature\":0.7,\"max_tokens\":200,\"stream\":false}"
# 2、 "stream" ： true
# curl -X POST http://127.0.0.1:8080/v1/chat/completions -H "Content-Type: application/json" -d "{\"model\":\"qwen-plus\",\"messages\":[{\"role\":\"system\",\"content\":\"你是一名专业助手\"},{\"role\":\"user\",\"content\":\"请解释一下LoRA技术的基本原理\"}],\"temperature\":0.7,\"max_tokens\":200,\"stream\":true}"
