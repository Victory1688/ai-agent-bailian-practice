# 以下是一个简单示例，展示如何通过上下文信息引导大模型分阶段完成任务：
# 原写法：直接使用 llm 变量，但本文件既未导入也未定义 llm，运行会报 NameError
# response = llm.chat.completions.create(
#     model="qwen-plus",
#     messages=[{"role": "user", "content": prompt}]
# )

# 改用阿里百炼平台 dashscope 调用大模型（参照 01-05 的改写方式）
import os
import dashscope

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

prompt = """
你是一位智能体助手，当前任务是多步骤问题求解。

任务目标：用户希望了解其信用卡的账单日、还款日，并获取本月账单详情。

已知上下文：
- 用户身份验证已完成；
- 已完成步骤：查询账单日，返回为每月15日；
- 当前阶段：继续查询还款日。

请根据上述上下文，生成用户当前还需了解的信息，并指导下一步行为。
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
response = get_response([{"role": "user", "content": prompt}])

# 输出结果
# 原写法：OpenAI 响应结构取值
# print(response.choices[0].message.content)
print(response.output.choices[0].message.content)
