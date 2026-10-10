# 以下是典型的接口模式设计：
# from openai import OpenAI  # 原写法：OpenAI() 未配置 api_key 和 base_url，无法调用
# llm = OpenAI()

# 改用阿里百炼平台 dashscope 调用大模型（参照 01-04 的改写方式）
import os
import dashscope

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# 构建消息序列
messages = [
    {"role": "system", "content": "你是一位金融知识专家，请严格按照要求回答问题。"},
    {"role": "user", "content": "请告诉我债券和股票的区别，用表格列出。"}
]

# 封装模型响应函数（参照 01_textSummarization.py）
def get_response(messages):
    response = dashscope.Generation.call(
        model='qwen-plus',
        messages=messages,
        temperature=0.3,          # 参数与原 OpenAI 写法一致，dashscope 同样支持
        max_tokens=512,
        result_format='message'   # 将输出设置为message形式
    )
    return response

# 调用模型
# 原写法：OpenAI 兼容接口调用（无 key 无法执行）
# response = llm.chat.completions.create(
#     model="qwen-plus",
#     messages=messages,
#     temperature=0.3,
#     max_tokens=512
# )
response = get_response(messages)

# 输出结果
# 原写法：OpenAI 响应结构取值
# print(response.choices[0].message.content)
print(response.output.choices[0].message.content)
