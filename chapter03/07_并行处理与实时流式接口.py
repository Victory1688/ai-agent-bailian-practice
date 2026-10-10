# 【例3-7】 并行处理与实时流式接口
# 批处理 (Batch Processing)：将多个独立的推理请求合并成一个批次并行处理。优势：高吞吐量。适用：离线任务、大规模数据处理。
# 流式传输 (Streaming)：将模型输出逐块传输给客户端，而不是一次性返回。优势：实时性高、极低的感知延迟。适用：实时对话、聊天机器人。

# ========== 原写法：本地 GPU 批处理 + 假流式（需要 GPU，且流式是"装出来"的） ==========
# 教学说明：原代码的 FastAPI 骨架、BatchRequest/StreamRequest 数据结构是好教材。
# 两个问题：
#   1. 批处理依赖本地 GPU 的 batch generate（一次前向算多组输入），无 GPU 跑不动
#   2. 流式是假的——先整段生成完，再切成 8 字符一片 sleep 模拟打字机（首字延迟 = 整段生成时间）
#
# from fastapi import FastAPI, Request
# from pydantic import BaseModel
# from transformers import AutoTokenizer, AutoModelForCausalLM
# from fastapi.responses import StreamingResponse
# import torch, uvicorn, time, json
#
# # 初始化模型（需要 GPU）
# model_path = "Qwen/Qwen-1.8B"
# tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
# model = AutoModelForCausalLM.from_pretrained(...).cuda().eval()
#
# # 构造Prompt函数（裸基座模型不认识 messages，手动拼角色标记——同 char03-05/06）
# def build_prompt(messages):
#     prompt = ""
#     for msg in messages:
#         if msg.role == "user":      prompt += f"[用户]：{msg.content}\n"
#         elif msg.role == "assistant": prompt += f"[助手]：{msg.content}\n"
#         elif msg.role == "system":    prompt += f"[系统提示]：{msg.content}\n"
#     prompt += "[助手]："
#     return prompt
#
# # 批处理接口（GPU batch：多组输入 padding 对齐后一次 forward）
# @app.post("/v1/chat/batch")
# async def batch_chat(req: BatchRequest):
#     prompts = [build_prompt(messages) for messages in req.messages_list]
#     input_ids = tokenizer(prompts, return_tensors="pt", padding=True, truncation=True).input_ids.cuda()
#     with torch.no_grad():
#         output_ids = model.generate(input_ids, max_new_tokens=req.max_tokens)
#     decoded = tokenizer.batch_decode(output_ids, skip_special_tokens=True)
#     results = [text.split("[助手]：")[-1].strip() for text in decoded]
#     return {"results": results}
#
# # 流式输出生成器（假流式：整段生成完再切片）
# def stream_generator(prompt, max_tokens, temperature):
#     ...
#     output_text = tokenizer.decode(...).split("[助手]：")[-1].strip()
#     for i in range(0, len(output_text), 8):
#         yield json.dumps({"choices": [{"delta": {"content": output_text[i:i+8]}}]}) + "\n"
#         time.sleep(0.05)

# ========== 改写：FastAPI 骨架保留 + 云端并发批处理 + 真流式 ==========
# 改写核心：
#   1. 批处理：GPU batch generate → ThreadPoolExecutor 线程池并发调用 dashscope
#      （"合并多请求并行处理"的教学思想不变，实现从"一次 GPU 前向"变成"多线程同时发请求"）
#   2. 流式：假流式 → 真流式（dashscope stream=True + incremental_output=True），
#      补齐 data: 前缀与 [DONE] 结束标记（同 char03-05 的升级）
#   3. build_prompt 消失——云端 Chat 模型原生理解 messages 数组
from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
from concurrent.futures import ThreadPoolExecutor
import uvicorn
import json
import os
import dashscope

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# 初始化FastAPI应用（原样保留）
app = FastAPI()

# 输入结构定义（原样保留——批处理与流式两种请求协议）
class ChatItem(BaseModel):
    role: str
    content: str

class BatchRequest(BaseModel):
    model: str
    messages_list: list[list[ChatItem]]  # 多组对话历史（批处理的"批"就批在这里）
    max_tokens: int = 128

class StreamRequest(BaseModel):
    model: str
    messages: list[ChatItem]
    max_tokens: int = 128
    temperature: float = 0.7

# 线程池：批处理的并发执行器（最多同时处理 8 个请求）
_executor = ThreadPoolExecutor(max_workers=8)


# ========== 单次推理函数（批处理的基本单元） ==========
def infer_one(messages_list_of_dicts, max_tokens: int) -> str:
    """
    单组对话的云端推理

    参数:
        messages_list_of_dicts: [{"role": ..., "content": ...}, ...]
        max_tokens: 回复长度上限
    返回:
        模型回复文本；失败返回错误说明字符串
    """
    try:
        response = dashscope.Generation.call(
            model='qwen-plus',
            messages=messages_list_of_dicts,
            max_tokens=max_tokens,
            result_format='message'
        )
        return response.output.choices[0].message.content.strip()
    except Exception as e:
        return f"调用失败: {str(e)}"


# ========== 批处理接口（原 /v1/chat/batch 保留，GPU batch → 线程池并发） ==========
@app.post("/v1/chat/batch")
async def batch_chat(req: BatchRequest):
    """
    批处理端点：多组对话并行推理，一次性返回全部结果

    原写法：tokenizer(prompts, padding=True) 把多组输入对齐成一个 batch，
            model.generate 一次前向并行算完（GPU batch）
    改写：ThreadPoolExecutor 把多组请求同时发给云端（网络 IO 并行）
         ——教学思想相同（并行处理多个独立请求），实现载体不同
    """
    # 把 Pydantic 对象转成 dashscope 需要的字典列表（build_prompt 的替代）
    all_messages = [[{"role": m.role, "content": m.content} for m in group]
                    for group in req.messages_list]

    # 线程池并发：所有请求同时发出，全部完成后一次性收集结果
    futures = [_executor.submit(infer_one, msgs, req.max_tokens) for msgs in all_messages]
    results = [f.result() for f in futures]

    return {"results": results}


# ========== 真流式生成器（假流式升级，同 char03-05） ==========
def stream_generator(messages_list_of_dicts, max_tokens, temperature):
    """真流式：模型每生成一段就实时推送，而非整段生成完再切片"""
    responses = dashscope.Generation.call(
        model='qwen-plus',
        messages=messages_list_of_dicts,
        max_tokens=max_tokens,
        temperature=temperature,
        result_format='message',
        stream=True,                    # 开启流式输出
        incremental_output=True         # 增量模式：每次只返回新增内容
    )
    for response in responses:
        chunk = response.output.choices[0].message.content or ""
        if chunk:
            yield f"data: {json.dumps({'choices': [{'delta': {'content': chunk}}]}, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"            # OpenAI 协议结束标记


# ========== 流式输出接口（原 /v1/chat/stream 保留） ==========
@app.post("/v1/chat/stream")
async def stream_chat(req: StreamRequest):
    messages_list = [{"role": m.role, "content": m.content} for m in req.messages]
    return StreamingResponse(
        stream_generator(messages_list, req.max_tokens, req.temperature),
        media_type="text/event-stream")


# ========== 启动服务 ==========
# 原写法：uvicorn.run("filename:app", ...) 占位符直接运行报 ImportError，改为传 app 对象
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)


# ========== 测试请求示例 ==========
# 批处理请求（POST http://127.0.0.1:8000/v1/chat/batch）：
# {
#   "model": "qwen-plus",
#   "messages_list": [
#     [{"role": "user", "content": "介绍一下LangChain"}],
#     [{"role": "user", "content": "什么是LoRA技术？"}]
#   ]
# }
# 预期响应：{"results": ["LangChain是...", "LoRA是..."]}（两路并发，总耗时≈单次耗时）

# 流式请求（POST http://127.0.0.1:8000/v1/chat/stream）：
# {
#   "model": "qwen-plus",
#   "messages": [{"role": "user", "content": "请解释一下大语言模型的上下文窗口"}],
#   "max_tokens": 100,
#   "temperature": 0.7
# }
# 预期响应（SSE 持续推送）：
# data: {"choices": [{"delta": {"content": "大语言"}}]}
# data: {"choices": [{"delta": {"content": "模型的"}}]}
# ...
# data: [DONE]


# ---- 输出： Windows cmd 环境下，多行写法会有问题，可以压缩成单行版本：
#  curl -X POST http://127.0.0.1:8000/v1/chat/batch -H "Content-Type: application/json" -d "{\"model\":\"qwen-plus\",\"messages_list\":[[{\"role\":\"user\",\"content\":\"介绍一下LangChain\"}],[{\"role\":\"user\",\"content\":\"什么是LoRA技术？\"}]]}"

# # Windows CMD 单行版本
#  curl -X POST http://127.0.0.1:8000/v1/chat/stream -H "Content-Type: application/json" -d "{\"model\":\"qwen-plus\",\"messages\":[{\"role\":\"user\",\"content\":\"请解释一下大语言模型的上下文窗口\"}],\"max_tokens\":100,\"temperature\":0.7}"
