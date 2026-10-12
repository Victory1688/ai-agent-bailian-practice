# 【例7-5】上下文存储与回调机制：持久化上下文日志设计
#
# 核心必要性
#
# 构建日志系统是实现以下关键能力的基础：
# • 任务中断后的状态恢复 • 长期用户画像的动态构建 • 多轮复杂对话的记忆维护 • 系统异常时的故障快速审计
# 关键日志字段
#
# 日志记录需包含高价值的元数据与内容：
# • 唯一任务编号 (task_id) • 交互时间戳 (timestamp) • 模型响应状态 (state) • 段落类型 / 模型来源 / 内容体
#
# 改写前的问题：
#   1) qwen_agent.Agent/Message/Tool——虚构框架（char02 已多次确认不存在）
#   2) DeepSeekPredictor——模拟工具（返回假数据），保持原样
#   3) LOG_FILE 相对路径——运行目录不一定是脚本目录，日志会写到不可预期的位置
# 改写策略：
#   - create_log_segment / persist_segment 原样保留（本篇核心教学资产：七字段 JSONL 日志）
#   - DeepSeekPredictor 去掉虚构 Tool 继承
#   - agent.chat() → dashscope.Generation.call（qwen-plus），日志 model 字段如实记 qwen-plus
#   - LOG_FILE 改为基于脚本目录的绝对路径（char06 gensim 相对路径教训），原写法注释保留

# 原写法（注释保留）：虚构框架 import
# from qwen_agent.agent import Agent
# from qwen_agent.context import Message
# from qwen_agent.tools import Tool

import os
import json
import uuid
from datetime import datetime
from typing import Dict, List
import dashscope

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# ========= 日志持久化路径设置 =========
# 原写法：LOG_FILE = "agent_context_log.jsonl"（相对路径，写到运行目录而非脚本目录）
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_context_log.jsonl")

# ========= 工具定义：模拟DeepSeek工具（改写：去掉虚构 Tool 继承） =========
class DeepSeekPredictor:
    """经济数据预测模拟工具（改写：去掉虚构 Tool 继承，纯类）"""
    def __init__(self):
        # 原写法：super().__init__(name="deepseek_predict", description="用于经济数据预测的模拟工具")
        self.name = "deepseek_predict"
        self.description = "用于经济数据预测的模拟工具"

    def call(self, query: str) -> str:
        print("→ 已调用 DeepSeek-V1 预测模块")
        return f"[DeepSeek-V1] 针对'{query}'预测2024年GDP增长率为5.2%。"

# ========= 上下文日志段生成函数（原样保留——本篇核心教学资产） =========
# 七字段结构：比 01 篇五字段多出 id（唯一记录号）和 timestamp（交互时间戳）
def create_log_segment(role: str, content: str, segment_type: str, model: str, task_id: str) -> Dict:
    return {
        "id": str(uuid.uuid4()),                            # 唯一记录号：全局不重复
        "timestamp": datetime.now().isoformat(),            # 交互时间戳：ISO 8601 格式
        "task_id": task_id,                                 # 任务编号：跨任务隔离
        "role": role,                                       # 角色：system / user / tool / assistant
        "type": segment_type,                               # 段落类型：system_prompt / input / tool_output / response
        "model": model,                                     # 模型来源：哪一方产生的内容
        "content": content                                  # 内容体
    }

# ========= 持久化日志写入函数（原样保留——JSONL 追加写入） =========
def persist_segment(segment: Dict):
    """每段即时追加写入 JSONL 文件（一行一个 JSON 对象），不缓存不批量"""
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(segment, ensure_ascii=False) + "\n")

# ========= 主流程执行（改写：qwen_agent.Agent → dashscope.Generation.call） =========
if __name__ == "__main__":
    print("=== 持久化上下文日志系统启动 ===")

    # 初始化工具
    # 原写法：agent = Agent(tools=[tool])
    tool = DeepSeekPredictor()
    task_id = "t006"

    # 1. 系统提示段
    system_prompt = "你是中国国家财政专家助手，所有回答需简洁、严谨、有数据支撑。"
    # 原写法：model 字段为 "qwen-3.0"（教材虚构版本号），改写后如实记录
    seg = create_log_segment("system", system_prompt, "system_prompt", "qwen-plus", task_id)
    persist_segment(seg)

    # 2. 用户提问段
    user_input = "请预测2024年中国GDP增长，并说明依据。"
    seg = create_log_segment("user", user_input, "input", "user", task_id)
    persist_segment(seg)

    # 3. 工具调用段（模拟DeepSeek预测）
    tool_output = tool.call(user_input)
    seg = create_log_segment("tool", tool_output, "tool_output", "deepseek-v1", task_id)
    persist_segment(seg)

    # 4. 最终生成回答段（改写：qwen_agent.Agent.chat → dashscope.Generation.call）
    final_prompt = f"""系统提示：{system_prompt}
工具信息：{tool_output}
用户提问：{user_input}
请基于以上信息进行严谨回答："""
    # 原写法：result = agent.chat(messages=[Message(role="user", content=final_prompt)])
    print("调用qwen-plus生成中……")
    response = dashscope.Generation.call(
        model="qwen-plus",
        messages=[{"role": "user", "content": final_prompt}],
        temperature=0.3,
        max_tokens=512,
        result_format='message'
    )
    result_content = response.output.choices[0].message.content

    seg = create_log_segment("assistant", result_content, "response", "qwen-plus", task_id)
    persist_segment(seg)

    # 输出结果
    print("\n--- 最终回答输出 ---")
    print(result_content)

    # 展示持久化日志（最近5条）
    print("\n--- 最新上下文日志（展示最后5条） ---")
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()[-5:]
        for line in lines:
            print(json.loads(line))
