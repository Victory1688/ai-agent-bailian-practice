# 【例7-7】上下文存储与回调机制：动态上下文合并策略
# 核心痛点
#   无差别拼接所有上下文，极易导致输入文本冗长超限。此外，历史信息的随意堆砌，
#   还会引发语义冲突，干扰模型对当前意图的准确理解。
# 解决方案：动态上下文合并策略
#   通过对上下文段进行分类、加权、裁剪与重排序，有选择地组合最有价值的信息，
#   在保持上下文关联的同时，实现输入内容的最优化。
#
# 常见实施策略
#   • 基于时间的窗口截断：保留最近对话，移除遥远的历史。
#   • 基于内容的语义抽取：只保留与当前问题语义强相关的片段。
#   • 基于权重与剪裁：区分用户提问与系统回复，优先保留关键信息。
# 最终目标
#   在严格遵守模型输入Token限制、保留上下文语义完整性的前提下，
#   为每次模型调用生成结构最优、信息密度最高的提示词（Prompt）。
#
# 改写前的问题：
#   1) qwen_agent.Agent/Message/Tool——虚构框架（char02 已多次确认不存在）
#   2) MacroForecastTool——模拟工具（返回假数据），保持原样
# 备注：本篇原代码无 redis 调用，无需按 cache.json 方案替换
# 改写策略：
#   - build_segment / dynamic_merge_context 原样保留（本篇核心教学资产：三级筛选合并）
#   - MacroForecastTool 去掉虚构 Tool 继承
#   - agent.chat() → dashscope.Generation.call（qwen-plus）

# 原写法（注释保留）：虚构框架 import
# from qwen_agent.agent import Agent
# from qwen_agent.context import Message
# from qwen_agent.tools import Tool

import json
import os
import time
from typing import List, Dict
import dashscope

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# ========= 结构化上下文段结构（原样保留——四字段，比 01 篇五字段少了 task_id/meta） =========
def build_segment(role: str, content: str, segment_type: str, timestamp: float = None) -> Dict:
    return {
        "role": role,
        "content": content,
        "type": segment_type,
        "timestamp": timestamp or time.time()
    }

# ========= 模拟DeepSeek工具模块（改写：去掉虚构 Tool 继承） =========
class MacroForecastTool:
    """经济趋势分析模拟工具（改写：去掉虚构 Tool 继承，纯类）"""
    def __init__(self):
        # 原写法：super().__init__(name="macro_forecast", description="经济趋势分析工具")
        self.name = "macro_forecast"
        self.description = "经济趋势分析工具"

    def call(self, query: str) -> str:
        print("→ DeepSeek-V1 调用中...")
        return f"[DeepSeek-V1] 分析：{query} 增长趋势预期良好，2024年预计5.3%。"

# ========= 上下文合并策略（原样保留——本篇核心教学资产） =========
def dynamic_merge_context(segments: List[Dict], task_type: str) -> str:
    """三级筛选合并：系统提示全保留 → 工具段留最新1条 → 交互历史留最近4条"""
    # 策略：优先保留系统提示、工具输出，其次为最近2条用户+模型交互
    selected = []

    # 第一级：系统提示全保留（身份设定不可丢）
    system_segments = [s for s in segments if s["type"] == "system"]
    selected.extend(system_segments)

    # 第二级：工具段保留最新1条（按时间戳倒序取第一条——最新事实优先）
    tool_segments = sorted([s for s in segments if s["type"] == "tool"], key=lambda x: -x["timestamp"])
    if tool_segments:
        selected.append(tool_segments[0])

    # 第三级：最近交互保留2轮（input+response 合计最多4条，按时间戳倒序截断）
    history = sorted([s for s in segments if s["type"] in ["input", "response"]], key=lambda x: -x["timestamp"])
    selected.extend(history[:4])

    # 构造合并Prompt：每段前加 [ROLE-TYPE] 标注前缀
    merged = ""
    for seg in selected:
        prefix = f"[{seg['role'].upper()}-{seg['type']}]"
        merged += f"{prefix} {seg['content']}\n"

    return merged

# ========= 主流程执行（改写：qwen_agent.Agent → dashscope.Generation.call） =========
if __name__ == "__main__":
    print("=== 启动动态上下文合并策略系统 ===")

    # 初始化上下文池与工具
    context_pool: List[Dict] = []
    # 原写法：agent = Agent(tools=[tool])
    tool = MacroForecastTool()

    # 生成系统提示段
    context_pool.append(build_segment("system", "你是一位国家政策与宏观经济专家，语言要严谨、简洁、具数据支撑", "system"))

    # 模拟历史对话与工具输出
    context_pool.append(build_segment("user", "2022年GDP增长率是多少？", "input"))
    context_pool.append(build_segment("assistant", "2022年中国GDP增长为3.0%。", "response"))

    context_pool.append(build_segment("user", "2023年预计呢？", "input"))
    context_pool.append(build_segment("assistant", "2023年GDP增长约为5.2%。", "response"))

    tool_output = tool.call("2024年GDP预测")
    context_pool.append(build_segment("tool", tool_output, "tool"))

    # 用户当前提问
    new_question = "请基于历史数据与趋势，判断2024年GDP是否可能超过5.5%？"
    context_pool.append(build_segment("user", new_question, "input"))

    # 合并上下文并调用模型
    final_prompt = dynamic_merge_context(context_pool, task_type="forecast")
    print("\n--- 合并后的Prompt结构 ---")
    print(final_prompt)

    # 交给模型处理
    # 原写法：result = agent.chat(messages=[Message(role="user", content=final_prompt)])
    # 改写：dashscope.Generation.call（qwen-plus）
    print("调用qwen-plus生成中……")
    response = dashscope.Generation.call(
        model="qwen-plus",
        messages=[{"role": "user", "content": final_prompt}],
        temperature=0.3,
        max_tokens=512,
        result_format='message'
    )
    result_content = response.output.choices[0].message.content
    print("\n--- Qwen3.0 输出结果 ---")
    print(result_content)
