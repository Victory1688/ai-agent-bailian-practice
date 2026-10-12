# 第7章 MCP协议：模型上下文通信标准
# 【例7-1】上下文段结构化表示
# 核心矛盾：如何在保证历史上下文可追溯、任务状态可恢复的同时，让上下文灵活适应任务的动态变化，避免状态僵化导致的逻辑失效？
# 解决方案：采用结构化上下文段表示，每个段包含角色、内容、类型、任务ID、元信息等字段，实现上下文的动态更新与恢复。
#
# 改写前的问题：
#   1) qwen_agent.Agent/Tool/Message——虚构框架（char02 已多次确认不存在）
#   2) call_deepseek_v1——模拟函数（直接返回假数据），保持原样
# 改写策略：
#   - Agent 调 dashscope.Generation.call（qwen-plus）
#   - StructuredContextQueryTool 去掉虚构 Tool 继承
#   - build_context_segment 纯 Python 函数原样保留（这是本篇核心教学资产）
#   - call_deepseek_v1 保持原样（模拟函数，DeepSeek 真接可以按 dashscope 兼容模式改）

# 原写法（注释保留）：虚构框架 import
# from qwen_agent.agent import Agent
# from qwen_agent.tools import Tool
# from qwen_agent.context import Message

import json
import os
from typing import List, Dict
import dashscope

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

## 上下文段结构体构建函数（原样保留——本篇核心教学资产）
def build_context_segment(role: str, content: str, segment_type: str, task_id: str, meta: Dict = None) -> Dict:
    """构建标准上下文段结构：五字段（role/content/type/task_id/meta）"""
    return {
        "role": role,           # 角色：user / system / tool / model
        "content": content,     # 上下文内容
        "type": segment_type,   # 段落类型：input / response / observation
        "task_id": task_id,     # 所属任务标识（跨任务隔离）
        "meta": meta or {}      # 附加元信息：时间戳、状态码、来源等
    }

## DeepSeek-V1 模拟调用接口（原样保留——模拟函数）
# 原代码注释说"调用DeepSeek-V1模型 API（此处用虚拟请求替代）"——确实是模拟，
# 标题里的"DeepSeek"同 char06-09 的假标题，改写时保持原状。
# 真接 DeepSeek 可以按 dashscope 兼容模式（openai-compatible）改写：
#   import openai; client = openai.OpenAI(base_url="https://api.deepseek.com")
def call_deepseek_v1(prompt: str) -> str:
    print("调用DeepSeek-V1生成中……（模拟，实际返回假数据）")
    return f"[DeepSeek] 回答：根据提示'{prompt}'生成的补充视角。"

## 结构化上下文管理工具（改写：去掉虚构 Tool 继承）
class StructuredContextQueryTool:
    """结构化上下文段解读工具（改写：去掉虚构 Tool 继承，纯类）"""
    def __init__(self, segments: List[Dict]):
        # 原写法：super().__init__(name="structured_context_query", description="...")
        self.segments = segments

    def call(self, query: str) -> str:
        """核心逻辑原样保留：抽取 input+response 类型的最近 4 段 → 拼成上下文摘要"""
        relevant = [seg for seg in self.segments if seg["type"] in ["input", "response"]]
        context_summary = "\n".join([f"{seg['role']}: {seg['content']}" for seg in relevant[-4:]])
        return f"【对话上下文】\n{context_summary}\n【用户问题】\n{query}"

## 主流程（改写：qwen_agent.Agent → dashscope.Generation.call）
if __name__ == "__main__":
    # 构建结构化上下文段（五字段，原样保留）
    context_segments = [
        build_context_segment("user", "我想了解2023年中国的财政支出情况。", "input", task_id="t001"),
        build_context_segment("model", "2023年中国财政支出约为26万亿元，主要用于民生保障、教育和基础设施建设。", "response", task_id="t001"),
        build_context_segment("user", "那2022年与2023年相比增长了多少？", "input", task_id="t001")
    ]

    # 构建结构化上下文摘要工具
    context_tool = StructuredContextQueryTool(segments=context_segments)

    # 用户最终提问
    query = "是否存在财政支出快速增长的趋势？"
    structured_prompt = context_tool.call(query)

    # ====== Qwen3.0 Agent 调用（改写：dashscope.Generation.call） ======
    # 原写法：agent = Agent(tools=[context_tool]); agent.chat(messages=[Message(role="user", content=structured_prompt)])
    print("调用qwen-plus生成中……")
    response = dashscope.Generation.call(
        model="qwen-plus",
        messages=[{"role": "user", "content": structured_prompt}],
        temperature=0.3,
        max_tokens=512,
        result_format='message'
    )
    qwen_content = response.output.choices[0].message.content

    # ====== DeepSeek-V1 模拟调用（原样保留） ======
    deepseek_response = call_deepseek_v1(prompt=structured_prompt)

    # 合并响应
    print("\n--- qwen-plus 回答 ---")
    print(qwen_content)

    print("\n--- DeepSeek 辅助回答（模拟） ---")
    print(deepseek_response)

    # 增加新段落——结构化记录（这是"可追溯、可恢复"的关键）
    context_segments.append(build_context_segment("model", qwen_content, "response", "t001"))
    context_segments.append(build_context_segment("model", deepseek_response, "observation", "t001", meta={"source": "deepseek", "is_mock": True}))

    # 打印结构化上下文记录
    print("\n--- 当前上下文段结构（JSON） ---")
    print(json.dumps(context_segments, ensure_ascii=False, indent=2))
