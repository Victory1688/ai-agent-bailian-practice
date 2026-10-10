# 案例一：生成SQL语句的任务建模
# from openai import OpenAI  # 原写法：OpenAI() 未配置 api_key 和 base_url，无法调用
# llm = OpenAI()

# 改用阿里百炼平台 dashscope 调用大模型（参照 01_textSummarization.py / 02_提示词驱动的Agent.py 的改写方式）
import os
import dashscope

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# 构建任务Prompt
user_instruction = "我想查询所有注册时间在2023年之后的用户姓名和邮箱"

prompt = f"""
你是一位数据库专家，请根据以下用户指令生成SQL语句。
要求：
1. 表名为users；
2. 字段包括name和email；
3. 使用标准SQL语法；
4. 输出格式为JSON，字段包括sql和explanation。

指令：{user_instruction}
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
# 原写法：OpenAI 兼容接口调用（无 key 无法执行）
# response = llm.chat.completions.create(
#     model="qwen-plus",
#     messages=[{"role": "user", "content": prompt}],
#     temperature=0
# )
messages = [{"role": "user", "content": prompt}]
response = get_response(messages)

# 输出结果
# 原写法：OpenAI 响应结构取值
# print(response.choices[0].message.content)
print(response.output.choices[0].message.content)
