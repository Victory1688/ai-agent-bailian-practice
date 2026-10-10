# 第3章 大模型开发基础
# 【例3-1】 构建通过远程调用大模型的语义助手，输入中文成语，返回其典故、来历与含义，
# 支持上下文结构化构造与温度参数调整

# openai_saas_example.py

# 原写法：OpenAI 老版本 SDK 调用方式，且未配置 OPENAI_API_KEY（国内无法直连 OpenAI 服务）
# import openai
# import os
# import json
# import requests
# from typing import List, Dict
#
# # 设置OpenAI的API Key
# openai.api_key = os.getenv("OPENAI_API_KEY")
#
# # 调用OpenAI Chat API函数
# def chat_with_openai(prompt: str, temperature: float = 0.5, max_tokens: int = 300) -> str:
#     response = openai.ChatCompletion.create(
#         model="gpt-3.5-turbo",
#         messages=messages,
#         temperature=temperature,
#         max_tokens=max_tokens
#     )
#     reply = response['choices'][0]['message']['content']

# 改用阿里百炼平台 dashscope 调用大模型（参照 char01/char02 的改写方式）
import os
import json
import dashscope
from typing import List, Dict

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# ========== 封装消息构造函数（原 build_message 逻辑完全保留） ==========
# 这是教学重点：system 角色锚定"语言学家"身份，user 角色放具体请求
def build_message(user_prompt: str) -> List[Dict[str, str]]:
    return [
        {"role": "system", "content": "你是一位语言学家，擅长解释中文成语的典故、来历与含义"},
        {"role": "user", "content": user_prompt}
    ]

# ========== 远程调用大模型函数（原 chat_with_openai 改写，业务逻辑完全保留） ==========
# 原写法：openai.ChatCompletion.create(...) 老版本 SDK 调用
# 改写：dashscope.Generation.call(...) 百炼平台调用
#       但参数 temperature / max_tokens / 异常兜底逻辑原样保留
def chat_with_llm(prompt: str, temperature: float = 0.5, max_tokens: int = 300) -> str:
    """
    远程调用大模型：构造消息 → 发起请求 → 取回复内容

    参数:
        prompt: 用户输入（如"请解释成语'破釜沉舟'的来历和含义"）
        temperature: 生成温度，越低越确定性，越高越有创造性（0-2）
        max_tokens: 单次回复的最大 token 数上限
    返回:
        模型回复文本；调用失败时返回错误说明字符串（永不抛异常）
    """
    messages = build_message(prompt)

    try:
        response = dashscope.Generation.call(
            model='qwen-plus',                     # 百炼平台模型名（替换原 gpt-3.5-turbo）
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            result_format='message'                # 统一 message 格式，取值路径一致
        )
        reply = response.output.choices[0].message.content
        return reply.strip()

    except Exception as e:
        return f"调用失败: {str(e)}"

# ========== 批量调用（原 batch_inference 逻辑完全保留） ==========
# 教学点：一个函数调用的循环就是批量推理，results 字典收集成语→解释映射
def batch_inference():
    """批量请求多个成语解释，返回 {成语: 解释} 字典"""
    idioms = [
        "破釜沉舟", "卧薪尝胆", "指鹿为马", "望梅止渴", "画龙点睛"
    ]
    results = {}
    for idiom in idioms:
        # 用中文引号嵌套，避免与 f-string 的英文双引号冲突
        reply = chat_with_llm(f"请解释成语\u201c{idiom}\u201d的来历和含义")
        results[idiom] = reply
    return results

# ========== 主程序 ==========
if __name__ == "__main__":
    print(">>> 开始批量调用阿里百炼大模型")
    result = batch_inference()
    for idiom, explanation in result.items():
        print(f"\n【{idiom}】\n{explanation}\n")
