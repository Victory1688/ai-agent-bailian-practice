# 【例3-9】 大模型的可信度评估
# 模型幻觉（Hallucination）是指模型生成看似合理，但实际上与事实不符、逻辑错误或完全虚构的内容。
# 这是当前所有基于深度学习的大语言模型（LLM）在生成内容时固有的、难以完全消除的风险。
# 基于生成概率评估：通过分析模型生成每个 Token 时的概率分布，计算输出的置信度。
# 生成概率越低的内容，往往意味着模型越不确定，产生"幻觉"的可能性越大。

# ========== 原写法：本地模型 + output_scores 捕获逐 token 概率（需要 GPU） ==========
# from fastapi import FastAPI
# from pydantic import BaseModel
# from transformers import AutoTokenizer, AutoModelForCausalLM
# import torch
# import torch.nn.functional as F
# import uvicorn
#
# # 初始化模型（需要 GPU）
# model_path = "Qwen/Qwen-1.8B"
# tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
# model = AutoModelForCausalLM.from_pretrained(...).cuda().eval()
#
# # build_prompt（裸基座模型手动拼角色标记——同 char03-05~08，改写后消息直接透传）
# def build_prompt(messages):
#     ...
#
# @app.post("/v1/chat/with_confidence")
# async def chat_with_confidence(req: ChatRequest):
#     prompt = build_prompt(req.messages)
#     input_ids = tokenizer(prompt, return_tensors="pt").input_ids.cuda()
#     with torch.no_grad():
#         output = model.generate(
#             input_ids=input_ids, max_new_tokens=req.max_tokens,
#             return_dict_in_generate=True,   # 关键 1：返回完整生成对象而不只是序列
#             output_scores=True)             # 关键 2：输出每一步的原始分数（logits）
#     generated_text = tokenizer.decode(output.sequences[0], ...).split("[助手]：")[-1].strip()
#
#     token_scores = []
#     for i, scores in enumerate(output.scores):
#         probs = F.softmax(scores[0], dim=-1)          # logits -> 概率分布
#         topk_probs, topk_indices = torch.topk(probs, k=req.top_k)  # 取前 k 个候选
#         tokens = [tokenizer.decode([idx.item()]) for idx in topk_indices]
#         probs_float = [float(p) for p in topk_probs]
#         token_scores.append({"step": i, "top_tokens": tokens, "top_probs": probs_float})
#     return {"response": generated_text, "token_confidence": token_scores}

# ========== 改写：dashscope OpenAI 兼容模式（唯一能拿到逐 token logprobs 的云端路径） ==========
# 改写要点：
#   1. dashscope 原生 SDK（Generation.call）不返回 logprobs，无法做逐 token 置信度评估
#   2. dashscope 的 OpenAI 兼容模式接口支持 logprobs + top_logprobs 参数——
#      正是原写法 output_scores=True + torch.topk 的云端等价物
#   3. 这也再次呼应 char03-05 的教学点：OpenAI 协议是行业通用方言，
#      高级能力（logprobs/工具调用/流式）都定义在这套协议里
from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn
import math
import os
import requests

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')

# 兼容模式端点：用 OpenAI 协议访问百炼（与原生 SDK 端点是同一平台的两扇门）
COMPATIBLE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

# FastAPI初始化（原样保留）
app = FastAPI()

# 请求结构定义（原样保留，top_k 在兼容模式里对应 top_logprobs）
class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    model: str
    messages: list[Message]
    max_tokens: int = 64
    top_k: int = 5          # 每步取概率最高的前 k 个候选（兼容模式上限 20）


@app.post("/v1/chat/with_confidence")
async def chat_with_confidence(req: ChatRequest):
    """带置信度评估的对话端点：回答内容 + 每个生成 token 的概率分布"""
    # 消息直接透传（build_prompt 的替代，云端原生理解 role/content）
    messages_list = [{"role": m.role, "content": m.content} for m in req.messages]

    # 云端推理 + 逐 token 概率（原写法 return_dict_in_generate + output_scores 的等价能力）
    resp = requests.post(
        COMPATIBLE_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": "qwen-plus",
            "messages": messages_list,
            "max_tokens": req.max_tokens,
            "logprobs": True,           # 返回每个生成 token 的对数概率
            "top_logprobs": req.top_k   # 每步附带回概率最高的前 k 个候选（= 原 torch.topk(k=req.top_k)）
        },
        timeout=60
    )
    data = resp.json()
    choice = data["choices"][0]
    generated_text = choice["message"]["content"]
    # logprobs.content 是逐 token 的列表：[{"token": "...", "logprob": -0.35, "top_logprobs": [...]}, ...]
    token_logprobs = choice["logprobs"]["content"]

    token_scores = []
    chosen_probs = []
    for i, item in enumerate(token_logprobs):
        # 模型实际选中的 token：logprob 是自然对数概率，exp() 还原成 0~1 的概率
        chosen_prob = math.exp(item["logprob"])
        chosen_probs.append(chosen_prob)
        # top-k 候选列表（等价原写法 torch.topk(probs, k) + tokenizer.decode）
        top_tokens = []
        top_probs = []
        for cand in item.get("top_logprobs", []):
            top_tokens.append(cand["token"])
            top_probs.append(math.exp(cand["logprob"]))
        token_scores.append({
            "step": i,
            "chosen_token": item["token"],
            "chosen_prob": round(chosen_prob, 4),
            "top_tokens": top_tokens,
            "top_probs": [round(p, 4) for p in top_probs]
        })

    # 置信度汇总（教材导语"计算输出的置信度"的落地：平均概率低 = 模型在"冒险说话"）
    avg_prob = sum(chosen_probs) / len(chosen_probs) if chosen_probs else 0.0
    low_ratio = sum(1 for p in chosen_probs if p < 0.5) / len(chosen_probs) if chosen_probs else 0.0
    confidence_summary = {
        "avg_token_prob": round(avg_prob, 4),         # 全程平均置信度（0~1）
        "low_confidence_ratio": round(low_ratio, 4),  # 置信度 < 0.5 的 token 占比
        "hint": "avg_token_prob 越低、low_confidence_ratio 越高，幻觉风险越大"
    }

    return {
        "response": generated_text,
        "token_confidence": token_scores,       # 与原写法相同结构的逐 token 明细
        "confidence_summary": confidence_summary  # 改写新增：直接可用的整体置信度指标
    }


# ========== 启动服务 ==========
# 原写法：uvicorn filename:app --reload（占位符 + 中文文件名无法作模块导入）
# 改写：直接传 app 对象
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)


# ========== 测试请求示例 ==========
# POST http://127.0.0.1:8000/v1/chat/with_confidence
# {
#   "model": "qwen-plus",
#   "messages": [{"role": "user", "content": "请解释一下LangChain的核心组件"}],
#   "max_tokens": 32,
#   "top_k": 5
# }
# 预期输出（结构沿用教材，数据为真实云端返回）：
# {
#   "response": "LangChain的核心组件包括模型I/O、Chains链式结构、Agents智能体...",
#   "token_confidence": [
#     {"step": 0, "chosen_token": "Lang", "chosen_prob": 0.83,
#      "top_tokens": ["Lang", "Lan", "大", "链", "这"], "top_probs": [0.83, 0.05, ...]},
#     ...
#   ],
#   "confidence_summary": {"avg_token_prob": 0.78, "low_confidence_ratio": 0.1, "hint": "..."}
# }


# # Windows CMD 单行版本
# curl -X POST http://127.0.0.1:8000/v1/chat/with_confidence -H "Content-Type: application/json" -d "{\"model\":\"qwen-plus\",\"messages\":[{\"role\":\"user\",\"content\":\"请解释一下LangChain的核心组件\"}],\"max_tokens\":32,\"top_k\":5}"
