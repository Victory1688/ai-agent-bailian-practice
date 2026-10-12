# 【例7-3】 上下文标注与路由机制：案例分析：多路由控制策略
# 核心代码逻辑
#
# 1. 路由规则：定义 `determine_route()` 函数，基于预设关键词判断目标模块。
# 2. 任务拆分：将复杂的用户请求，拆解为多个独立的原子化子任务。
# 3. 循环执行：遍历子任务列表，逐个调用对应模块并行处理。
# 4. 结果合并：汇总各模块返回结果，整理后统一输出给用户。
#
# 改写前的问题：
#   1) qwen_agent.Agent/Message/Tool——虚构框架（char02 已多次确认不存在）
#   2) call_deepseek_module——模拟函数（返回假数据），保持原样
# 额外发现（实测）：教材注释与实际路由行为不符——
#   sub_tasks[0] "分析2023年的财政数据" 注释标 route → tool，但该句含"数据"
#   且不含"调用"+"工具"，按 determine_route() 实际命中 deepseek 分支；
#   三个子任务没有一个同时含"调用"和"工具"，tool 路由分支永远不会触发。
# 改写策略：
#   - determine_route() 原样保留（本篇核心教学资产）
#   - DataSummaryTool 去掉虚构 Tool 继承
#   - build_context_message 虚构 Message → 直接返回 dict
#   - agent.chat() → dashscope.Generation.call（qwen-plus）

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

# ========= 路由规则定义（原样保留——本篇核心教学资产） =========
def determine_route(user_input: str) -> str:
    """根据关键词判断信息应路由到哪个模块"""
    if "政策" in user_input or "法律" in user_input:
        return "qwen"
    elif "数据" in user_input or "预测" in user_input:
        return "deepseek"
    elif "调用" in user_input and "工具" in user_input:
        return "tool"
    else:
        return "default"

# ========= 工具模块定义（改写：去掉虚构 Tool 继承） =========
class DataSummaryTool:
    """结构化数据总结工具（改写：去掉虚构 Tool 继承，纯类）"""
    def __init__(self):
        # 原写法：super().__init__(name="data_summary", description="结构化数据总结工具")
        self.name = "data_summary"
        self.description = "结构化数据总结工具"

    def call(self, query: str) -> str:
        return "[Tool] 已根据结构化数据对2023年财政执行情况完成分析，总支出同比增长6.8%。"

# ========= 模拟DeepSeek-V1调用（原样保留——模拟函数） =========
def call_deepseek_module(prompt: str) -> str:
    print("→ 已路由至 DeepSeek-V1 处理数据类任务。")
    return f"[DeepSeek] 回答：针对'{prompt}'，预测2024年经济增长为5%-5.5%。"

# ========= 构造Agent上下文消息（改写：虚构 Message → dict） =========
def build_context_message(role: str, content: str) -> Dict:
    # 原写法：return Message(role=role, content=content)
    return {"role": role, "content": content}

# ========= 主流程入口（改写：qwen_agent.Agent → dashscope.Generation.call） =========
if __name__ == "__main__":
    # 初始化模型与工具
    # 原写法：agent = Agent(tools=[tool])
    tool = DataSummaryTool()

    # 模拟用户请求
    # 注意：user_input 定义后未被使用——教材的子任务拆分是硬编码的，
    # 真实系统应由 LLM 完成"复杂请求 → 原子子任务"的拆分
    user_input = "请调用工具分析2023年的财政数据，并预测2024年中国GDP的增长情况，还要说明近期的主要财政政策。"

    # 拆分用户指令（教材注释标注意图路由；实际路由以 determine_route() 关键词匹配为准）
    sub_tasks = [
        "分析2023年的财政数据",  # 教材注释：route → tool（实测：命中"数据" → deepseek）
        "预测2024年中国GDP的增长情况",  # route → deepseek（含"预测"，实测一致）
        "说明近期的主要财政政策"  # route → qwen（含"政策"，实测一致）
    ]

    # 构建任务调度与执行路由
    responses: List[str] = []
    for task in sub_tasks:
        route = determine_route(task)

        if route == "qwen":
            print(f"→ 已路由至 Qwen3.0 处理政策类任务。任务内容：{task}")
            prompt = f"请作为政策专家，简要说明：{task}"
            # 原写法：result = agent.chat(messages=[build_context_message("user", prompt)])
            # 改写：dashscope.Generation.call（qwen-plus）
            print("调用qwen-plus生成中……")
            response = dashscope.Generation.call(
                model="qwen-plus",
                messages=[build_context_message("user", prompt)],
                temperature=0.3,
                max_tokens=512,
                result_format='message'
            )
            result = response.output.choices[0].message.content
            responses.append(result)

        elif route == "deepseek":
            result = call_deepseek_module(task)
            responses.append(result)

        elif route == "tool":
            result = tool.call(task)
            responses.append(result)

        else:
            print("→ 无匹配路由，使用默认模型。")
            prompt = f"默认处理：{task}"
            # 原写法：result = agent.chat(messages=[build_context_message("user", prompt)])
            # 改写：dashscope.Generation.call（qwen-plus）
            print("调用qwen-plus生成中……")
            response = dashscope.Generation.call(
                model="qwen-plus",
                messages=[build_context_message("user", prompt)],
                temperature=0.3,
                max_tokens=512,
                result_format='message'
            )
            result = response.output.choices[0].message.content
            responses.append(result)

    # 输出合并结果
    print("\n--- 多模块合并响应 ---")
    for idx, res in enumerate(responses, 1):
        print(f"[子任务{idx}] {res}")
