# 【例8-3】工具异常处理机制
# 为什么需要异常处理？
#
# 现实世界的不确定性
#   工具调用可能因网络波动、API调用限制、参数传递错误或外部服务不可用等原因失败，
#   是无法完全避免的。
#
# 系统健壮性 (Robustness)
#   一个生产级的智能体系统，必须具备"优雅降级"的能力，在依赖的工具不可用时，
#   依然能提供基础的服务，而不是直接抛出错误导致整个流程崩溃。
#
# 改写前的问题：
#   1) qwen_agent.Agent/Message/Tool——虚构框架（char02 已多次确认不存在）
#   2) RiskyEconomicTool——模拟工具（random 50% 失败 + 假数据），随机机制原样保留
#     （随机失败正是本篇教学重点：让降级路径可复现地被触发）
# 备注：本篇原代码无 redis 调用，无需按 cache.json 方案替换
# 改写策略：
#   - RiskyEconomicTool 的 try/except + random 失败模拟原样保留（教学核心）
#   - RobustAgent 的降级分支判断（"[ERROR]" in tool_response）原样保留
#   - agent.chat() → dashscope.Generation.call（qwen-plus）

# 原写法（注释保留）：虚构框架 import
# from qwen_agent.agent import Agent
# from qwen_agent.context import Message
# from qwen_agent.tools import Tool

import time
import random
from typing import Dict, Any
import os
import dashscope

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# ========= 工具定义（带异常处理，原样保留——教学核心：随机失败+自捕获） =========
class RiskyEconomicTool:
    """可能失败的经济预测工具（改写：去掉虚构 Tool 继承；random 失败模拟原样保留）"""
    def __init__(self):
        # 原写法：super().__init__(name="unstable_forecast", description="可能失败的经济预测工具")
        self.name = "unstable_forecast"
        self.description = "可能失败的经济预测工具"

    def call(self, inputs: Dict[str, Any]) -> str:
        # 工具内部自捕获异常——永不向上抛，失败也返回字符串（char02 惯例）
        try:
            region = inputs.get("region")
            if not region:
                raise ValueError("缺少region字段")

            # 模拟远程调用失败（50% 概率，原样保留——教学核心）
            if random.random() < 0.5:
                raise ConnectionError("远程API调用失败：连接超时")

            # 正常预测结果
            return f"[DeepSeek-V1] 预测：{region} 2026年GDP增长预计为5.3%"

        except Exception as e:
            return f"[ERROR] 工具执行失败：{str(e)}"

# ========= Agent包装器（改写：去掉虚构 Agent；降级逻辑原样保留） =========
class RobustAgent:
    def __init__(self, tool):
        # 原写法：self.agent = Agent(tools=[tool])
        self.tool = tool

    def process(self, user_input: str) -> str:
        # 简单参数提取（同 02 篇 parse_input 思想的极简版）
        region = "美国" if "美国" in user_input else "中国"

        # 工具调用
        tool_response = self.tool.call({"region": region})
        print(f"\n→ 工具返回结果：{tool_response}")

        if "[ERROR]" in tool_response:
            # 降级逻辑（原样保留——本篇核心教学资产）
            print("→ 进入降级流程，切换为模型直接生成")
            prompt = f"""注意：外部工具调用失败，请直接基于常识与历史数据，预测{region}在2026年的经济走势，并给出简明解释。"""
        else:
            # 正常逻辑（原样保留）
            prompt = f"""根据以下数据生成经济分析总结：
工具输出：{tool_response}
分析要求：语言简洁、观点明确、适合决策参考"""

        # 交由Qwen生成
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

# ========= 主流程运行 =========
if __name__ == "__main__":
    print("=== 启动带异常处理的Agent系统 ===")

    tool = RiskyEconomicTool()
    agent = RobustAgent(tool=tool)

    # 模拟用户提问
    query = "请预测2026年美国的GDP增长趋势"
    response = agent.process(query)

    print("\n--- Qwen3.0 最终输出 ---")
    print(response)
