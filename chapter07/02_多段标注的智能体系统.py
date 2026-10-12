# 【例7-2】MCP协议基础设计理念：案例分析 — 多段标注的智能体系统
# 核心矛盾：如何在保证历史上下文可追溯、任务状态可恢复的同时，让智能体系统灵活适应任务的动态变化，避免状态僵化导致的逻辑失效？
# 解决方案：采用多段标注的智能体系统，整合三类关键信息——
#   ● 系统提示 (System)  —— 定义智能体的身份与行为风格
#   ● 记忆信息 (Memory)  —— 保留历史交互，理解用户偏好
#   ● 工具结果 (Tool)    —— 整合外部数据，辅助事实性推理
# 三类标注组装成结构化上下文段，让 LLM 同时看到"该怎么说话"、"用户喜欢什么"、"事实是什么"。
#
# 改写前的问题：
#   1) qwen_agent.Agent/Tool/Message——虚构框架（char02 已多次确认不存在）
#   2) call_deepseek_tool——模拟函数（返回假数据），保持原样
# 改写策略：
#   - Agent 调 dashscope.Generation.call（qwen-plus）
#   - FiscalForecastTool 去掉虚构 Tool 继承
#   - build_segment 原样保留（与 01 篇 build_context_segment 完全同构）
#   - 三类标注的组装逻辑原样保留（本篇核心教学资产）

# 原写法（注释保留）：虚构框架 import
# from qwen_agent.agent import Agent
# from qwen_agent.tools import Tool
# from qwen_agent.context import Message

import json
import os
from typing import List, Dict
import dashscope

api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# ========= 上下文段构造函数（与 01 篇完全同构，原样保留） =========
def build_segment(role: str, content: str, seg_type: str, task_id: str, meta: Dict = None) -> Dict:
    """构建结构化上下文段（五字段结构，与 01 篇 build_context_segment 同构）"""
    return {
        "role": role,
        "content": content,
        "type": seg_type,
        "task_id": task_id,
        "meta": meta or {}
    }

# ========= 模拟DeepSeek工具调用（原样保留——模拟函数） =========
def call_deepseek_tool(prompt: str) -> str:
    print("调用DeepSeek-V1模型工具中……（模拟，实际返回假数据）")
    return f"[DeepSeek Tool] 对于'{prompt}'的结构化回答：预计2024年财政收入将增长5%左右，主要来源为消费税和企业所得税。"

# ========= 财政预测工具（改写：去掉虚构 Tool 继承） =========
class FiscalForecastTool:
    """模拟财政预测工具（改写：去掉虚构 Tool 继承，纯类）"""
    def __init__(self):
        # 原写法：super().__init__(name="fiscal_forecast", description="...")
        self.name = "fiscal_forecast"

    def call(self, query: str) -> str:
        return call_deepseek_tool(query)

# ========= 主流程（改写：qwen_agent.Agent → dashscope.Generation.call） =========
if __name__ == "__main__":
    segments: List[Dict] = []

    # ====== 三类标注组装（本篇核心教学资产，原样保留） ======

    # 标注 1：系统提示段（type="system"）——指定风格与角色设定
    system_prompt = "你是一位熟悉中国经济政策的政府咨询顾问，回答需专业、简明、有依据。"
    segments.append(build_segment("system", system_prompt, "system", task_id="t001"))

    # 标注 2：记忆段（type="memory"）——注入用户长期偏好
    memory_info = "用户偏好获取简明扼要的政策摘要，避免冗长表述。"
    segments.append(build_segment("memory", memory_info, "memory", task_id="t001"))

    # 标注 3：用户输入段（type="input"）
    user_question = "请预测2024年中国的财政收入趋势，并说明主要增长来源。"
    segments.append(build_segment("user", user_question, "input", task_id="t001"))

    # 标注 4：工具段（type="tool"）——模拟调用结构化工具返回结果
    tool = FiscalForecastTool()
    tool_response = tool.call(user_question)
    segments.append(build_segment("tool", tool_response, "tool", task_id="t001", meta={"tool": "deepseek-v1"}))

    # ====== 构造上下文摘要 + 调 LLM ======
    # 构造结构化上下文摘要：每条段前加 [TYPE] 标注
    context_summary = "\n".join(
        [f"[{s['type'].upper()}] {s['role']}: {s['content']}" for s in segments]
    )

    # 原写法：agent = Agent(tools=[tool]); agent.chat(messages=[Message(...)])
    # 改写：dashscope.Generation.call
    print("调用qwen-plus生成中……")
    final_prompt = (
        f"以下是结构化上下文段（含系统提示、用户偏好、工具数据和用户问题），"
        f"请基于这些内容给出准确回答：\n{context_summary}"
    )
    response = dashscope.Generation.call(
        model="qwen-plus",
        messages=[{"role": "user", "content": final_prompt}],
        temperature=0.3,
        max_tokens=512,
        result_format='message'
    )
    qwen_content = response.output.choices[0].message.content

    # 输出
    print("\n--- qwen-plus 回答 ---")
    print(qwen_content)

    print("\n--- 当前上下文段结构 ---")
    print(json.dumps(segments, ensure_ascii=False, indent=2))
