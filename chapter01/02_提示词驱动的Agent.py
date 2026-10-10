# 以下示例展示如何在LangChain中构建提示词驱动的Agent：
# from langchain.prompts import PromptTemplate  # 原写法：LangChain 1.x 中该路径已不存在，PromptTemplate 移至 langchain_core.prompts
# from langchain.llms import OpenAI             # 原写法：langchain.llms 在 1.x 中已移除，且无 API Key 无法调用
# from langchain.chains import LLMChain         # 原写法：LLMChain 已迁移至 langchain_classic.chains（官方已弃用）

# 改用阿里百炼平台：LangChain PromptTemplate 原样保留 + ChatTongyi 接百炼（方案A，走 dashscope SDK，零新增依赖）
import os
from langchain_core.prompts import PromptTemplate              # 1.x 中 PromptTemplate 在 langchain_core
from langchain_community.chat_models.tongyi import ChatTongyi  # 百炼官方封装，底层用已安装的 dashscope 包
from langchain_core.output_parsers import StrOutputParser

# 定义提示词模板（原样保留）
template = PromptTemplate(
    input_variables=["question"],
    template="""
你是一位知识图谱专家，请基于已有知识，回答以下问题，
并说明判断依据：

问题：{question}
答案：
"""
)

# 原写法：OpenAI() 未配置 key，无法调用，改用 ChatTongyi 接百炼
# llm = OpenAI(model_name="qwen-plus")
# chain = LLMChain(llm=llm, prompt=template)

# ChatTongyi 也会自动读取 DASHSCOPE_API_KEY 环境变量，这里显式传入更直观
llm = ChatTongyi(
    model="qwen-plus",
    dashscope_api_key=os.environ.get('DASHSCOPE_API_KEY'),
)

# 执行任务
# 原写法：LLMChain.run 已弃用，LangChain 1.x 推荐 LCEL 管道写法（模板 -> 模型 -> 解析器）
# response = chain.run("什么是实体消歧？")
chain = template | llm | StrOutputParser()
response = chain.invoke({"question": "什么是实体消歧？"})
print(response)
