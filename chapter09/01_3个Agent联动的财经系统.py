# 第9章 多智能体系统构建实战
# 【例9-1】主控智能体与子任务智能体划分
#
# 核心概念：主从架构——主流的多智能体架构通常采用"主控智能体 - 子任务智能体"的层级结构，
#           实现功能解耦与逻辑划分，平衡全局控制与执行灵活性。
# 案例目标：构建一个协同工作的多智能体财经系统，包含"主控、资讯、分析"三类角色，通过分工实现：
#           复杂财经任务拆解分发、全网财经资讯自动抓取与摘要、基于数据的预测建模与分析，
#           最终为用户提供整合后的深度财经洞察。
#
# 改写前的问题：
#   1) qwen_agent.Agent/Message/Tool——虚构框架（char02 起已多次确认不存在于真实环境）
#   2) NewsAgent / ForecastAgent 的 call() 返回硬编码模拟数据（教材刻意为之，保留原样）
#      ——真实子 Agent 应接入新闻 API / 数据库，本篇教学重点是"调度结构"而非数据真实性
#   3) ControlAgent 内部的 agent.chat() 是唯一真实 LLM 调用点
# 备注：本篇原代码无 redis 调用，无需按 cache.json 方案替换
# 改写策略：
#   - 三类角色的职责划分 + run() 三步调度链原样保留（本篇核心教学资产：主从架构）
#   - NewsAgent / ForecastAgent 去掉虚构 Tool 继承，改为纯类（模拟数据保持原样）
#   - agent.chat() → dashscope.Generation.call（qwen-plus）

# 原写法（注释保留）：虚构框架 import
# from qwen_agent.agent import Agent
# from qwen_agent.context import Message
# from qwen_agent.tools import Tool

import os
from typing import Dict, List
import dashscope

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# ========= 资讯Agent定义（改写：去掉虚构 Tool 继承，纯类；模拟数据保持原样） =========
class NewsAgent:
    """资讯子Agent：负责抓取并提取财经新闻（模拟实现，教学重点是调度位次而非数据真实性）"""
    def __init__(self):
        # 原写法：super().__init__(name="news_agent", description="抓取并提取财经新闻")
        self.name = "news_agent"
        self.description = "抓取并提取财经新闻"

    def call(self, query: str) -> str:
        # 模拟新闻摘要（原样保留）
        return f"[资讯摘要] 当前宏观新闻显示：制造业回暖，CPI保持温和，出口增长稳定。"

# ========= 分析Agent定义（改写：去掉虚构 Tool 继承，纯类；模拟数据保持原样） =========
class ForecastAgent:
    """分析子Agent：根据资讯预测GDP趋势（模拟实现，输入来自上游 NewsAgent 的输出）"""
    def __init__(self):
        # 原写法：super().__init__(name="forecast_agent", description="根据资讯预测GDP趋势")
        self.name = "forecast_agent"
        self.description = "根据资讯预测GDP趋势"

    def call(self, summary: str) -> str:
        return f"[预测结果] 综合判断2024年GDP预计增长5.3%。分析依据为：{summary}"

# ========= 主控Agent封装（改写：agent.chat → dashscope.Generation.call） =========
class ControlAgent:
    """主控Agent：不干活，只负责任务拆解、按依赖顺序调度子Agent、最终整合 LLM 回应"""
    def __init__(self, tools: List):
        # 原写法：self.agent = Agent(tools=tools)
        # 改写：删掉虚构 Agent 实例——主控只持有子Agent引用，LLM 调用走 dashscope
        self.news_tool = tools[0]
        self.forecast_tool = tools[1]

    def run(self, user_query: str) -> str:
        """三步调度链（原样保留）：资讯 → 预测 → LLM 整合"""
        print("→ 开始执行主控Agent任务拆解与调度")

        # Step 1：交由新闻Agent处理
        print("→ 调用新闻Agent进行资讯提取...")
        summary = self.news_tool.call(user_query)
        print(f"→ 资讯Agent返回：{summary}")

        # Step 2：交由分析Agent进行预测（输入依赖 Step 1 的输出——串行流水线）
        print("→ 调用预测Agent进行经济建模...")
        forecast = self.forecast_tool.call(summary)
        print(f"→ 分析Agent返回：{forecast}")

        # Step 3：整理回应交由Qwen输出
        final_prompt = f"""请基于以下任务链条返回统一回应：

任务目标：{user_query}
资讯摘要：{summary}
预测输出：{forecast}
请以财经顾问语气生成最终报告："""

        # 原写法：result = self.agent.chat(messages=[Message(role="user", content=final_prompt)])
        # 改写：dashscope.Generation.call（qwen-plus）
        print("调用qwen-plus生成中……")
        response = dashscope.Generation.call(
            model="qwen-plus",
            messages=[{"role": "user", "content": final_prompt}],
            temperature=0.3,
            max_tokens=512,
            result_format='message'
        )
        return response.output.choices[0].message.content

# ========= 主流程运行（原样保留） =========
if __name__ == "__main__":
    print("=== 启动基于职责建模的多Agent系统 ===")

    news = NewsAgent()
    forecast = ForecastAgent()
    control_agent = ControlAgent(tools=[news, forecast])

    query = "请预测2024年中国GDP走势，并说明依据"
    response = control_agent.run(query)

    print("\n--- Qwen3.0最终响应 ---")
    print(response)
