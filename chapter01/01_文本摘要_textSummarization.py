# 以下是一个用于文本摘要的提示词设计示例：
# 改用阿里百炼平台 dashscope 调用大模型（参照 1-情感分析-Qwen.py 的写法）
import os
import dashscope

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

prompt = """
你是一位专业的中文技术文档撰写专家，
请将以下文本进行简洁、准确的摘要，
要求语言通顺，保留技术要点，控制在100字以内：

【原文内容】：
{}
"""

document = "Transformer结构是一种基于注意力机制的深度学习架构..."

# 拼接输入内容
final_prompt = prompt.format(document)

# 封装模型响应函数
def get_response(messages):
    response = dashscope.Generation.call(
        model='qwen-plus',  # 百炼平台模型名
        messages=messages,
        result_format='message'  # 将输出设置为message形式
    )
    return response

# 组装消息并调用模型生成
messages = [
    {"role": "user", "content": final_prompt}
]
response = get_response(messages)
print(response.output.choices[0].message.content)
