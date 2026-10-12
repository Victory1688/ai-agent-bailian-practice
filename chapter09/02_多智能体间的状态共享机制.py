# 【例9-2】带状态共享的多智能体系统
#
# 核心概念：通过独立的"中心状态管理器"来统一存储和分发任务中间结果与上下文，
#           实现智能体间的逻辑解耦与数据共享。
#
# 改写前的问题：
#   1) qwen_agent.Agent/Message/Tool——虚构框架（char02 起已多次确认不存在于真实环境）
#   2) AnalysisAgent / ReportAgent 的 call() 返回硬编码模拟数据（教材刻意为之，保留原样）
#   3) ControllerAgent 内部的 agent.chat() 是唯一真实 LLM 调用点
# 备注：本篇原代码无 redis 调用，无需按 cache.json 方案替换
# 改写策略：
#   - SharedState 中心管理器 + 两子 Agent 的写入/读取模式 + execute() 三步调度链原样保留
#     （本篇核心教学资产：状态共享让 Agent 解耦）
#   - AnalysisAgent / ReportAgent 去掉虚构 Tool 继承，改为纯类
#   - agent.chat() → dashscope.Generation.call（qwen-plus）

# 原写法（注释保留）：虚构框架 import
# from qwen_agent.agent import Agent
# from qwen_agent.context import Message
# from qwen_agent.tools import Tool

import os
from typing import Dict, Any
import dashscope

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# ========= 全局状态管理器（原样保留——本篇灵魂） =========
class SharedState:
    """中心状态管理器：所有 Agent 通过它读写数据，彼此不直接耦合"""
    def __init__(self):
        self.state: Dict[str, Any] = {}

    def update(self, key: str, value: Any):
        """写入状态：带 key-value，打印更新日志方便调试"""
        print(f"→ [状态更新] {key} = {value}")
        self.state[key] = value

    def get(self, key: str, default=None):
        """读取状态：不存在时返回 default"""
        return self.state.get(key, default)

    def dump(self) -> Dict[str, Any]:
        """导出当前全部状态快照（复制一份，防止外部改内部）"""
        return self.state.copy()

# ========= 分析Agent（改写：去掉虚构 Tool 继承，纯类；模拟数据保持原样） =========
class AnalysisAgent:
    """分析子Agent：往状态池写入 econ_trend，不关心谁会读"""
    def __init__(self, shared_state: SharedState):
        # 原写法：super().__init__(name="analysis_agent", description="执行数据分析任务")
        self.name = "analysis_agent"
        self.description = "执行数据分析任务"
        self.shared = shared_state

    def call(self, query: str) -> str:
        # 假设输入为"2024年宏观经济趋势"（模拟数据原样保留）
        result = "制造业增长、CPI温和回落、出口回升"
        self.shared.update("econ_trend", result)    # 写状态池
        return f"[分析完成] 趋势：{result}"

# ========= 报告Agent（改写：去掉虚构 Tool 继承，纯类；模拟逻辑保持原样） =========
class ReportAgent:
    """报告子Agent：从状态池读取 econ_trend，写入 final_report，不关心谁写的"""
    def __init__(self, shared_state: SharedState):
        # 原写法：super().__init__(name="report_agent", description="根据分析内容撰写最终报告")
        self.name = "report_agent"
        self.description = "根据分析内容撰写最终报告"
        self.shared = shared_state

    def call(self, _: str) -> str:
        trend = self.shared.get("econ_trend", "无数据")   # 读状态池
        report = f"2024年经济展望：预计{trend}，将推动GDP稳定增长。"
        self.shared.update("final_report", report)         # 写状态池
        return report

# ========= 主控Agent（改写：agent.chat → dashscope.Generation.call） =========
class ControllerAgent:
    """主控Agent：驱动调度链，同时也写状态池（user_input）和读状态池（合成 prompt）"""
    def __init__(self, tools: list, shared_state: SharedState):
        # 原写法：self.agent = Agent(tools=tools)
        # 改写：删掉虚构 Agent 实例——主控直调 dashscope 做最终合成
        self.shared = shared_state
        self.analysis_tool = tools[0]
        self.report_tool = tools[1]

    def execute(self, user_query: str) -> str:
        """三步调度链 + 状态池读写（原样保留）"""
        print("\n→ 主控Agent启动，任务分析中...")
        self.shared.update("user_input", user_query)   # 主控也写状态池

        # Step 1: 调用分析Agent（写 econ_trend）
        analysis = self.analysis_tool.call(user_query)
        print("→ 分析Agent响应：", analysis)

        # Step 2: 调用报告Agent（读 econ_trend，写 final_report）
        report = self.report_tool.call("")   # 注意参数是空串——数据靠状态池传递
        print("→ 报告Agent响应：", report)

        # Step 3: 最终合成响应（主控自己读状态池拼 prompt）
        prompt = f"""请基于以下信息生成一段完整用户报告：
用户问题：{self.shared.get('user_input')}
分析内容：{self.shared.get('econ_trend')}
最终报告：{self.shared.get('final_report')}"""

        # 原写法：result = self.agent.chat(messages=[Message(role="user", content=prompt)])
        # 改写：dashscope.Generation.call（qwen-plus）
        print("调用qwen-plus生成中……")
        response = dashscope.Generation.call(
            model="qwen-plus",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=512,
            result_format='message'
        )
        return response.output.choices[0].message.content

# ========= 主流程（原样保留） =========
if __name__ == "__main__":
    print("=== 启动多Agent状态共享系统 ===")
    shared = SharedState()
    agent1 = AnalysisAgent(shared)
    agent2 = ReportAgent(shared)
    controller = ControllerAgent([agent1, agent2], shared)

    query = "请分析2024年中国经济走势，并撰写总结报告"
    final_response = controller.execute(query)

    print("\n--- Qwen3.0最终响应 ---")
    print(final_response)
