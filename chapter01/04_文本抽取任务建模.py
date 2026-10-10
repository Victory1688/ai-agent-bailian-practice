# 案例二：文本抽取任务建模（抽取企业名与地址）
# 原写法：直接使用 llm 变量，但本文件既未导入也未定义 llm，运行会报 NameError
# result = llm.chat.completions.create(
#     model="qwen-plus",
#     messages=[{"role": "user", "content": prompt}]
# )

# 改用阿里百炼平台 dashscope 调用大模型（参照 01/02/03 的改写方式）
import os
import dashscope

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

instruction = "从以下文本中提取公司名称和地址信息，以JSON格式返回。\n\n文本：浙江橙龙科技有限公司位于杭州市余杭区五常街道五常大道100号。"

prompt = f"""
任务说明：从文本中识别并提取公司名称与地址信息。

输出格式：
{{
  "company": "...",
  "address": "..."
}}

请处理如下文本：
{instruction}
"""

# 封装模型响应函数（参照 01_textSummarization.py）
def get_response(messages):
    response = dashscope.Generation.call(
        model='qwen-plus',
        messages=messages,
        result_format='message'  # 将输出设置为message形式
    )
    return response

# 调用大模型
messages = [{"role": "user", "content": prompt}]
result = get_response(messages)

# 输出结果
# 原写法：OpenAI 响应结构取值
# print(result.choices[0].message.content)
print(result.output.choices[0].message.content)
