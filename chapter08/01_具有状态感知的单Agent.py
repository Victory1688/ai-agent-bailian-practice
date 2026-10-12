# 第8章 单智能体系统构建实战
# 【例8-1】实战解析：具备状态感知能力的单智能体
#
# 单智能体是构建复杂多智能体系统的基础单元。理解其内部构造，是掌握整个智能体架构的关键。
#
# 什么是状态管理？
#   跟踪和控制智能体在执行任务过程中所处的不同阶段。
#   对于长任务链、多轮会话或工具调用，状态管理是实现稳定交互、
#   任务全链路跟踪和异常快速恢复的核心基石。
#
# 智能体核心逻辑 (StatefulAgent)
#   核心 `execute` 方法串联起了完整的任务处理流程，配合 `update_state` 方法
#   实时记录并打印状态变更。逻辑涵盖：初始化任务ID、状态流转控制、工具调用协同、
#   异常捕获与失败处理，完整展示了具备状态感知能力的智能体如何稳定处理复杂任务。
#
# 改写前的问题：
#   1) qwen_agent.Agent/Message/Tool——虚构框架（char02 已多次确认不存在）
#   2) ForecastTool——模拟工具（返回假数据 + time.sleep(1) 模拟耗时），保持原样
# 备注：本篇原代码无 redis 调用，无需按 cache.json 方案替换
# 改写策略：
#   - AgentState 六态枚举 + execute 状态流转 + update_state/show_history 原样保留
#     （本篇核心教学资产：状态机思维）
#   - ForecastTool 去掉虚构 Tool 继承
#   - self.agent = Agent(tools=tools) 删掉（StatefulAgent 内直接调 dashscope）
#   - agent.chat() → dashscope.Generation.call（qwen-plus）

# 原写法（注释保留）：虚构框架 import
# from qwen_agent.agent import Agent
# from qwen_agent.context import Message
# from qwen_agent.tools import Tool

import uuid
import time
from enum import Enum
from typing import Dict, List
import os
import dashscope

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# ========= 状态定义（原样保留——本篇核心教学资产） =========
class AgentState(Enum):
    INITIALIZED = "initialized"
    READY = "ready"
    RUNNING = "running"
    WAITING_TOOL = "waiting_tool"
    COMPLETED = "completed"
    FAILED = "failed"

# ========= 工具定义（改写：去掉虚构 Tool 继承） =========
class ForecastTool:
    """经济预测模拟工具（改写：去掉虚构 Tool 继承，纯类）"""
    def __init__(self):
        # 原写法：super().__init__(name="deepseek_forecast", description="经济预测工具")
        self.name = "deepseek_forecast"
        self.description = "经济预测工具"

    def call(self, query: str) -> str:
        print("→ 调用 DeepSeek-V1 工具进行预测...")
        time.sleep(1)
        return f"[DeepSeek-V1] 预测结果：{query} 的增长预期为5.2%"

# ========= Agent任务结构（改写：虚构 Agent 去掉，类型注解去掉 Tool 泛型） =========
class StatefulAgent:
    def __init__(self, tools: List):
        self.task_id = str(uuid.uuid4())
        self.state = AgentState.INITIALIZED
        self.history: List[Dict] = []
        # 原写法：self.agent = Agent(tools=tools)
        self.tool = tools[0]

    def update_state(self, new_state: AgentState):
        """状态变更 + 记录历史（原样保留）"""
        print(f"→ 状态变更：{self.state.value} → {new_state.value}")
        self.state = new_state
        self.history.append({
            "timestamp": time.time(),
            "task_id": self.task_id,
            "state": self.state.value
        })

    def execute(self, system_prompt: str, user_question: str) -> str:
        """完整任务处理流程：六态流转 + try/except 异常兜底（原样保留，仅改写 LLM 调用）"""
        try:
            self.update_state(AgentState.READY)

            full_prompt = f"""【系统提示】
{system_prompt}

【用户提问】
{user_question}

请结合相关经济数据工具完成结构化分析。"""

            self.update_state(AgentState.RUNNING)

            # 工具调用阶段
            self.update_state(AgentState.WAITING_TOOL)
            tool_result = self.tool.call(user_question)

            self.update_state(AgentState.RUNNING)

            # 构造模型最终输入
            merged_prompt = f"{full_prompt}\n【工具响应】\n{tool_result}\n请生成回答："
            # 原写法：result = self.agent.chat(messages=[Message(role="user", content=merged_prompt)])
            # 改写：dashscope.Generation.call（qwen-plus）
            print("调用qwen-plus生成中……")
            response = dashscope.Generation.call(
                model="qwen-plus",
                messages=[{"role": "user", "content": merged_prompt}],
                temperature=0.3,
                max_tokens=512,
                result_format='message'
            )
            result_content = response.output.choices[0].message.content

            self.update_state(AgentState.COMPLETED)
            return result_content

        except Exception as e:
            self.update_state(AgentState.FAILED)
            return f"[ERROR] 任务执行失败：{str(e)}"

    def show_history(self):
        """打印状态变更日志（原样保留）"""
        print("\n--- 状态变更日志 ---")
        for entry in self.history:
            t = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(entry["timestamp"]))
            print(f"{t} | 状态：{entry['state']}")

# ========= 主执行流程 =========
if __name__ == "__main__":
    print("=== 启动具备状态管理的智能体系统 ===")

    tool = ForecastTool()
    agent = StatefulAgent(tools=[tool])

    system_prompt = "你是一名宏观经济顾问，所有回答需结合当前CPI和GDP数据，表达严谨、简明。"
    user_question = "请预测2026年GDP增长趋势，并说明主要影响因素。"

    output = agent.execute(system_prompt, user_question)
    print("\n--- 模型响应输出 ---")
    print(output)

    agent.show_history()
