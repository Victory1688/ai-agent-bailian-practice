# 【例7-4】模型分支路由与入口决策逻辑
# 核心痛点
#   单一通用模型处理所有类型的请求时，无法兼顾专业度与响应效率，
#   容易产生算力浪费和回答冗余，导致整体服务体验下降。
# 解决方案
#   引入"模型分支路由机制"与"入口决策逻辑"，构建模型网络。
#   系统根据任务特征动态分发，精准匹配到最擅长的模型入口进行处理。
# 决策依据 & MCP支持
#   •维度：用户意图、上下文特征、任务类型、语言风格
#   •赋能：通过MCP协议在上下文段中嵌入路由指令与入口权重，实现精细化控制。
#
# 改写前的问题：
#   1) qwen_agent.Agent/Message/Tool——虚构框架（char02 已多次确认不存在）
#   2) call_qwen3 / call_deepseek——模拟函数（返回假数据），保持原样
# 改写策略：
#   - route_decision() 原样保留（本篇核心教学资产：any() 生成器表达式关键词匹配）
#   - HybridAnalysisTool 去掉虚构 Tool 继承（call 签名 Dict 输入原样保留）
#   - default 分支的 agent.chat() → dashscope.Generation.call（qwen-plus）
#   - call_qwen3 / call_deepseek 模拟函数原样保留（其他三个分支全走模拟）

# 原写法（注释保留）：虚构框架 import
# from qwen_agent.agent import Agent
# from qwen_agent.context import Message
# from qwen_agent.tools import Tool

import json
import os
from typing import List, Dict
import dashscope

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# ========= 模拟模型调用函数定义（原样保留——其余三个分支全走模拟） =========
def call_qwen3(prompt: str) -> str:
    print("→ Qwen3.0入口已触发。")
    return f"[Qwen3.0] 回答：针对'{prompt}'，已完成语言生成与政策解读。"

def call_deepseek(prompt: str) -> str:
    print("→ DeepSeek-V1入口已触发。")
    return f"[DeepSeek-V1] 分析：关于'{prompt}'的预测已完成，增长预期为5.3%。"

# ========= 分支决策逻辑器（原样保留——本篇核心教学资产） =========
# 注意：与 03 篇 determine_route() 写法不同——03 篇用 "x in query"，
# 本篇用 any(k in query for k in [...]) 生成器表达式，可扩展性更好
def route_decision(query: str) -> str:
    """根据语义关键词决策模型入口"""
    if any(k in query for k in ["政策", "法规", "概述", "总结"]):
        return "qwen"
    elif any(k in query for k in ["预测", "趋势", "估计", "数据"]):
        return "deepseek"
    elif any(k in query for k in ["综合分析", "多维度", "对比"]):
        return "hybrid"
    else:
        return "default"

# ========= 工具模块示例（改写：去掉虚构 Tool 继承；call 签名 Dict 原样保留） =========
class HybridAnalysisTool:
    """多模型结果融合工具（改写：去掉虚构 Tool 继承，纯类；call 签名 Dict[str,str] 原样保留）"""
    def __init__(self):
        # 原写法：super().__init__(name="hybrid_analysis", description="多模型结果融合工具")
        self.name = "hybrid_analysis"
        self.description = "多模型结果融合工具"

    def call(self, inputs: Dict[str, str]) -> str:
        """组合分析：内部调两个模拟模型，再拼接结果"""
        qwen_result = call_qwen3(inputs["policy"])
        deepseek_result = call_deepseek(inputs["forecast"])
        return f"[组合分析] 综合政策视角：{qwen_result}\n数据预测视角：{deepseek_result}"

# ========= 主流程入口（改写：仅 default 分支 agent.chat→dashscope） =========
if __name__ == "__main__":
    print("=== 启动模型入口决策示例系统 ===")

    # 模拟用户提问集（覆盖 qwen / deepseek / hybrid 三种路由 + default 兜底）
    user_queries = [
        "请概述近期财政补贴政策的主要方向",                        # → qwen（含"概述"、"政策"）
        "请预测2024年GDP增长趋势",                                 # → deepseek（含"预测"、"趋势"）
        "请对近期财政补贴政策与经济增长趋势进行多维度综合分析"       # → hybrid（含"综合分析"、"多维度"）
    ]

    # 原写法：agent = Agent(tools=[tool])
    tool = HybridAnalysisTool()

    # 按任务决策执行分支
    for idx, query in enumerate(user_queries, 1):
        print(f"\n--- 处理第{idx}条请求 ---")
        decision = route_decision(query)

        if decision == "qwen":
            result = call_qwen3(query)

        elif decision == "deepseek":
            result = call_deepseek(query)

        elif decision == "hybrid":
            result = tool.call(inputs={
                "policy": "财政补贴政策分析",
                "forecast": "2024年经济趋势"
            })

        else:
            print("→ 默认模型入口激活")
            # 原写法：result = agent.chat(messages=[Message(role="user", content=query)]).content
            # 改写：dashscope.Generation.call（qwen-plus）
            print("调用qwen-plus生成中……")
            response = dashscope.Generation.call(
                model="qwen-plus",
                messages=[{"role": "user", "content": query}],
                temperature=0.3,
                max_tokens=512,
                result_format='message'
            )
            result = response.output.choices[0].message.content

        print(f"\n结果输出：\n{result}")
