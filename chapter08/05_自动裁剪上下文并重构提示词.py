# 【例8-5】上下文动态剪辑策略
# 为什么需要动态剪辑？
#   1) 上下文长度限制——大模型的输入窗口有固定的 Token 数量上限，
#      无法一次性承载过长的历史对话或海量文档。
#   2) 避免信息过载与浪费——在长对话中简单传递所有历史信息，
#      会消耗大量 Token 在低价值或不相关的内容上，降低模型推理效率。
#
# 本篇与 char07-07 的关系（重要认知）：
#   07 篇 dynamic_merge_context 是"按类型规则筛选"（system 全留 → tool 最新1 → 历史最近4）
#   本篇 dynamic_clip_context 是"按 Token 预算装填"（优先级排序 + 贪心装填）
#   两者是上下文压缩的两个流派：规则窗口 vs 预算装填，本篇显式引入了 priority 和 token 计量
#
# 改写前的问题：
#   1) qwen_agent.Agent/Message/Tool——虚构框架（char02 已多次确认不存在）
#   2) EconomicSummaryTool——模拟工具（返回假数据），保持原样
# 备注：本篇原代码无 redis 调用，无需按 cache.json 方案替换
# 改写策略：
#   - build_segment 六字段结构 + dynamic_clip_context 贪心装填算法原样保留
#     （本篇核心教学资产：priority 排序 + token_limit 装填）
#   - EconomicSummaryTool 去掉虚构 Tool 继承
#   - agent.chat() → dashscope.Generation.call（qwen-plus）

# 原写法（注释保留）：虚构框架 import
# from qwen_agent.agent import Agent
# from qwen_agent.context import Message
# from qwen_agent.tools import Tool

import time
from typing import List, Dict
import os
import dashscope

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# ========= 模拟工具模块（改写：去掉虚构 Tool 继承） =========
class EconomicSummaryTool:
    """生成结构化经济总结（改写：去掉虚构 Tool 继承，纯类；模拟函数保持原样）"""
    def __init__(self):
        # 原写法：super().__init__(name="econ_summary", description="生成结构化经济总结")
        self.name = "econ_summary"
        self.description = "生成结构化经济总结"

    def call(self, query: str) -> str:
        return f"[DeepSeek-V1] 分析完成：{query} 的GDP趋势良好。"

# ========= 构建上下文段结构（原样保留——本篇核心教学资产） =========
def build_segment(role: str, content: str, segment_type: str, timestamp=None) -> Dict:
    """构建六字段上下文段（与 char07-01 五字段相比：去掉 task_id/meta，新增 timestamp/priority/length）"""
    return {
        "role": role,
        "content": content,
        "type": segment_type,
        "timestamp": timestamp or time.time(),
        "priority": 1 if segment_type == "system" else 0.5,   # system 段优先级最高
        "length": len(content) // 2  # 模拟token数（中文约2字符=1token的粗略估计）
    }

# ========= 动态剪辑策略（原样保留——本篇核心教学资产） =========
def dynamic_clip_context(segments: List[Dict], token_limit=150) -> str:
    """贪心装填算法：按优先级与时间排序后，在 token 预算内尽量多装"""
    # 按优先级降序 + 时间戳降序排序（system 段优先，同优先级取最新的）
    segments.sort(key=lambda x: (-x["priority"], -x["timestamp"]))

    total = 0
    clipped = []
    for seg in segments:
        if total + seg["length"] <= token_limit:
            clipped.append(seg)
            total += seg["length"]

    # 构造Prompt（[ROLE-TYPE] 标注前缀，与 char07-07 同款）
    merged = ""
    for seg in clipped:
        merged += f"[{seg['role']}-{seg['type']}] {seg['content']}\n"
    return merged

# ========= 主系统结构（改写：agent.chat → dashscope.Generation.call） =========
if __name__ == "__main__":
    print("=== 启动具备上下文动态剪辑能力的Agent系统 ===")

    tool = EconomicSummaryTool()
    # 原写法：agent = Agent(tools=[tool])
    context_pool = []

    # 构建上下文段（原样保留——注意 2023/2025 段的内容与轮次错位，是教材的笔误）
    context_pool.append(build_segment("system", "你是资深经济顾问，语言需精准、简洁", "system"))
    context_pool.append(build_segment("user", "2024年GDP是多少？", "input"))
    context_pool.append(build_segment("assistant", "2024年增长为3.0%", "response"))
    context_pool.append(build_segment("user", "那2023年呢？", "input"))
    context_pool.append(build_segment("assistant", "2025年为5.2%", "response"))
    context_pool.append(build_segment("tool", tool.call("2026年预测"), "tool"))
    context_pool.append(build_segment("user", "2026年会不会更高？", "input"))
    context_pool.append(build_segment("assistant", "预计增长可达5.4%", "response"))
    context_pool.append(build_segment("user", "主要依据有哪些？", "input"))

    # 执行动态剪辑（token_limit=100 是教学用的紧预算，原样保留）
    prompt = dynamic_clip_context(context_pool, token_limit=100)

    print("\n--- 剪辑后上下文结构 ---")
    print(prompt)

    # 模型调用
    # 原写法：result = agent.chat(messages=[Message(role="user", content=prompt)])
    # 改写：dashscope.Generation.call（qwen-plus）
    print("调用qwen-plus生成中……")
    response = dashscope.Generation.call(
        model="qwen-plus",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=512,
        result_format='message'
    )
    result_content = response.output.choices[0].message.content
    print("\n--- Qwen3.0 响应输出 ---")
    print(result_content)
