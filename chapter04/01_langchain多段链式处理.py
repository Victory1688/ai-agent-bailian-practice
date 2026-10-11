# 第4章 LangChain框架与智能体构建流程
# 【例4-1】 Chains 链式构造器  Chains Logic Builder
# 组织任务流程的骨架，将复杂任务拆解为有序步骤，实现多步骤任务的自动化执行。

# 原写法：langchain 0.x 的 import 路径 + OpenAI 模型类，在当前环境无法运行，原因有二：
#   1) LangChain 1.x 中这三个模块路径已拆分：prompts 移入 langchain_core.prompts，
#      经典链（LLMChain/SequentialChain）收纳进 langchain_classic.chains，
#      langchain.llms.OpenAI 类已移除
#   2) OpenAI 类需要 OPENAI_API_KEY 且国内无法直连 OpenAI 官方服务
# from langchain.llms import OpenAI
# from langchain.prompts import PromptTemplate
# from langchain.chains import LLMChain, SequentialChain

# 改写（参照 char01-02_提示词驱动的Agent.py 的方式）：
#   - PromptTemplate 改从 langchain_core.prompts 导入（1.x 的新家）
#   - LLMChain / SequentialChain 属于经典链，从 langchain_classic.chains 导入
#   - 模型类 OpenAI 改为 ChatTongyi（阿里百炼平台），temperature=0.5 语义不变
#   - 三段子链 + SequentialChain 的链式结构一字不动——这是本篇的教学核心
import os

from langchain_core.prompts import PromptTemplate
from langchain_classic.chains import LLMChain, SequentialChain
from langchain_community.chat_models import ChatTongyi

# 初始化大语言模型
# 原写法：llm = OpenAI(temperature=0.5)
# 改写：换用百炼平台的 qwen-plus，从环境变量读取 DASHSCOPE_API_KEY
llm = ChatTongyi(
    model="qwen-plus",
    temperature=0.5,
    dashscope_api_key=os.environ.get("DASHSCOPE_API_KEY"),
)

# 子链一：根据主题生成子主题（原 prompt1 的模板文本与变量定义完全保留）
prompt1 = PromptTemplate(
    input_variables=["topic"],
    template="请列出与“{topic}”相关的三个细分研究方向，用逗号分隔。"
)
chain1 = LLMChain(llm=llm, prompt=prompt1, output_key="subtopics")

# 子链二：基于子主题生成研究问题
prompt2 = PromptTemplate(
    input_variables=["subtopics"],
    template="以下是子主题：{subtopics}，请为每个子主题提出一个具挑战性的研究问题。"
)
chain2 = LLMChain(llm=llm, prompt=prompt2, output_key="questions")

# 子链三：总结研究问题的社会价值
prompt3 = PromptTemplate(
    input_variables=["questions"],
    template="以下是若干研究问题：{questions}，请简要分析其对于推动社会发展的意义。"
)
chain3 = LLMChain(llm=llm, prompt=prompt3, output_key="impact")

# 构造完整链式结构（原 SequentialChain 的组装方式完全保留）
full_chain = SequentialChain(
    chains=[chain1, chain2, chain3],
    input_variables=["topic"],
    output_variables=["subtopics", "questions", "impact"],
    verbose=True
)

# 执行任务
# 原写法：response = full_chain.run(topic="人工智能伦理")
# 注意：原代码这里还藏着一个 bug——.run() 只支持"恰好一个输出键"的链，
#       而 SequentialChain 声明了 3 个输出变量，即使在 0.x 旧版同样会抛出
#       ValueError: `run` not supported when there is not exactly one output key
# 改写：统一用 1.x 的标准入口 invoke，传入变量字典、返回包含全部输出变量的字典
result = full_chain.invoke({"topic": "人工智能伦理"})

# 打印输出
# 原写法：print(response)
# 改写：分三段打印全部中间产物与最终结论，链式拆解的效果一目了然
print("== 子主题 subtopics ==")
print(result["subtopics"])
print("\n== 研究问题 questions ==")
print(result["questions"])
print("\n== 社会价值 impact ==")
print(result["impact"])
