# 【例8-4】LangChain中的Memory类详解
#
# 为什么需要 Memory？
#   为大模型应用提供一套标准化的记忆管理接口，屏蔽底层存储细节，专注业务逻辑开发。
#   无缝集成到智能体中，通过复用历史对话上下文，显著增强模型的长期对话感知能力。
#
# 常见的 Memory 类型：
#   ConversationBufferMemory        —— 全量存储（不截断）
#   ConversationSummaryMemory       —— LLM 摘要压缩存储
#   ConversationBufferWindowMemory  —— 窗口存储（只保留最近 k 轮，最常用）
#
# 改写前的问题：
#   1) qwen_agent.Agent/Message/Tool——虚构框架（char02 已多次确认不存在）
#   2) FakeDataFetcher——模拟工具（硬编码 if/elif 假数据），保持原样
#   3) 三个死 import：OpenAI / ConversationChain / messages_from_dict / messages_to_dict
#      全部导入但从未使用（教材模板残留）
#   4) FakeDataFetcher 虽然被初始化并注册给虚构 Agent，但 ask() 方法里从未显式调用
#      ——这是 char07-03/04 路由死代码谱系的延续
# 备注：本篇原代码无 redis 调用，无需按 cache.json 方案替换
# 改写策略：
#   - ConversationBufferWindowMemory(k=3, return_messages=True) + ask() 四步循环原样保留
#     （本篇核心教学资产：窗口存储机制 + 历史注入→LLM→回写 memory 模式）
#   - FakeDataFetcher 去掉虚构 Tool 继承，标注"注册但从未调用"
#   - 三个死 import 注释保留
#   - agent.chat() → dashscope.Generation.call（qwen-plus）

# 原写法（注释保留）：死 import
# from langchain.memory import ConversationBufferWindowMemory
# from langchain.schema import messages_from_dict, messages_to_dict  ← 从未使用
# from langchain.llms import OpenAI                                 ← 从未使用
# from langchain.chains import ConversationChain                   ← 从未使用

# 原写法（注释保留）：虚构框架 import
# from qwen_agent.agent import Agent
# from qwen_agent.context import Message
# from qwen_agent.tools import Tool

import os
import dashscope
# 原写法：from langchain.memory import ConversationBufferWindowMemory
# 改写：langchain 1.3.18 中 memory 已移至 langchain_classic
from langchain_classic.memory import ConversationBufferWindowMemory

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# ========= 模拟工具模块（改写：去掉虚构 Tool 继承；标注注册但从未调用） =========
class FakeDataFetcher:
    """提供历史数据支持的模拟工具（改写：去掉虚构 Tool 继承）
    
    注意：本类虽然在 LangChainQwenAgent.__init__ 里被初始化，
    但 ask() 方法里从未显式调用它——这是教材模板的遗留问题，
    与 char07-03/04 的路由死代码是同一家族。
    保留原样是为了让新人看到"注册了工具但没调用"的真实后果。
    """
    def __init__(self):
        # 原写法：super().__init__(name="data_fetch", description="提供历史数据支持的模拟工具")
        self.name = "data_fetch"
        self.description = "提供历史数据支持的模拟工具"

    def call(self, query: str) -> str:
        if "2025" in query:
            return "2025年GDP增长率为5.2%，主要受益于消费回暖和出口恢复"
        elif "2024" in query:
            return "2024年GDP增长为3.0%，疫情影响下内需低迷"
        else:
            return "暂无相关数据"

# ========= 配置 LangChain 内存机制（原样保留——本篇核心教学资产） =========
# k=3 表示只保留最近 3 轮对话（6 条 message：3 user + 3 AI）
# return_messages=True 让 .chat_memory.messages 返回 AIMessage/HumanMessage 对象列表
memory = ConversationBufferWindowMemory(k=3, return_messages=True)

# ========= 构造 Agent 包装器（改写：虚构 Agent 删掉；ask 四步循环原样保留） =========
class LangChainQwenAgent:
    def __init__(self, memory):
        self.memory = memory
        # 原写法：self.agent = Agent(tools=[FakeDataFetcher()])
        # 改写：删掉虚构 Agent。FakeDataFetcher 初始化但从未调用（死代码谱系）
        self.tool = FakeDataFetcher()

    def ask(self, user_input: str) -> str:
        """四步循环：历史注入 → LLM → 回写 memory（原样保留）"""
        # Step 1: 历史注入——从 memory.chat_memory.messages 取最近 k 轮
        history_str = "\n".join(
            [f"{m.content}" for m in self.memory.chat_memory.messages]
        )
        full_prompt = f"""以下是最近对话历史：
{history_str}

用户现在的问题是：
{user_input}

请结合历史与知识进行回答："""

        # Step 2: 调 Qwen 生成响应
        # 原写法：result = self.agent.chat(messages=[Message(role="user", content=full_prompt)])
        # 改写：dashscope.Generation.call（qwen-plus）
        print("调用qwen-plus生成中……")
        response = dashscope.Generation.call(
            model="qwen-plus",
            messages=[{"role": "user", "content": full_prompt}],
            temperature=0.3,
            max_tokens=512,
            result_format='message'
        )
        result_content = response.output.choices[0].message.content

        # Step 3: 回写 memory——LangChain 的 BufferWindowMemory 自动做窗口截断
        self.memory.chat_memory.add_user_message(user_input)
        self.memory.chat_memory.add_ai_message(result_content)

        # Step 4: 调试打印——当前 memory 里存了几条 message
        msg_count = len(self.memory.chat_memory.messages)
        print(f"  [Memory] 当前存储 {msg_count} 条 message（k=3 窗口上限 6 条）")

        return result_content

# ========= 初始化系统 =========
if __name__ == "__main__":
    print("=== 启动结合LangChain记忆机制的智能体 ===")
    bot = LangChainQwenAgent(memory=memory)

    # 4 轮对话设计是故意的——k=3 窗口意味着 Round 4 时 Round 1 应被裁掉
    print("\n[Round 1] 用户提问：2024年GDP是多少？")
    print(bot.ask("2024年GDP是多少？"))

    print("\n[Round 2] 用户提问：那2025年呢？")
    print(bot.ask("那2025年呢？"))

    print("\n[Round 3] 用户提问：你觉得2026年增长是否会更快？")
    print(bot.ask("你觉得2026年增长是否会更快？"))

    print("\n[Round 4] 用户追问：依据是什么？")
    print(bot.ask("依据是什么？"))
