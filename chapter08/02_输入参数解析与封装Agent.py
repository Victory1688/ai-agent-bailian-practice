# 【例8-2】实战解析：输入参数解析与封装
# 为什么需要参数解析？
#
# 填补"人机"鸿沟
#   模型生成的是自然语言，而工具/API需要的是结构化参数。解析器就是连接二者的关键桥梁。
#
# 保障调用准确性
#   输入参数格式错误或缺失，会直接导致工具调用失败，或返回无意义的错误结果。
#
# 改写前的问题：
#   1) qwen_agent.Agent/Message/Tool——虚构框架（char02 已多次确认不存在）
#   2) EconomicForecastTool——模拟工具（返回假数据），保持原样
# 备注：本篇原代码无 redis 调用，无需按 cache.json 方案替换
# 改写策略：
#   - parse_input 规则解析器 + print_parameters 原样保留（本篇核心教学资产：
#     NL→结构化参数的最小实现）
#   - EconomicForecastTool 去掉虚构 Tool 继承（call 签名 Dict 原样保留）
#   - agent.chat() → dashscope.Generation.call（qwen-plus）

# 原写法（注释保留）：虚构框架 import
# from qwen_agent.agent import Agent
# from qwen_agent.context import Message
# from qwen_agent.tools import Tool

import json
from typing import Dict, List, Any
import os
import dashscope

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# ========= 工具定义：经济预测工具（改写：去掉虚构 Tool 继承） =========
class EconomicForecastTool:
    """经济预测模拟工具（改写：去掉虚构 Tool 继承，纯类；call 签名 Dict 原样保留）"""
    def __init__(self):
        # 原写法：super().__init__(name="econ_forecast", description="基于区域和时间预测经济增长")
        self.name = "econ_forecast"
        self.description = "基于区域和时间预测经济增长"

    def call(self, params: Dict[str, Any]) -> str:
        # .get() 带默认值——参数缺失时的兜底（原样保留）
        region = params.get("region", "中国")
        year = params.get("year", 2026)
        focus = params.get("focus", "GDP")

        return f"[DeepSeek-V1] 预测结果：{region}在{year}年的{focus}增长率预计为5.2%"

# ========= 输入参数解析器（原样保留——本篇核心教学资产） =========
def parse_input(user_text: str) -> Dict[str, Any]:
    """
    简单的规则解析器：从文本中提取区域、年份和指标类型
    """
    region = "中国"
    year = 2026
    focus = "GDP"

    # 年份解析：按空格分词，找"数字+年"的 token
    for token in user_text.split():
        if token.endswith("年") and token[:-1].isdigit():
            year = int(token[:-1])

    # 区域解析：关键词优先级 美国 > 欧盟 > 默认中国
    if "美国" in user_text:
        region = "美国"
    elif "欧盟" in user_text:
        region = "欧盟"

    # 指标关键词：CPI > PMI > 默认GDP
    if "CPI" in user_text:
        focus = "CPI"
    elif "PMI" in user_text:
        focus = "PMI"

    return {
        "region": region,
        "year": year,
        "focus": focus
    }

# ========= 日志打印函数（原样保留） =========
def print_parameters(params: Dict[str, Any]):
    print("\n--- 结构化参数 ---")
    for k, v in params.items():
        print(f"{k}: {v}")

# ========= 主流程：Agent解析执行（改写：agent.chat→dashscope） =========
if __name__ == "__main__":
    print("=== 启动输入参数解析与封装系统 ===")

    # 初始化工具
    # 原写法：agent = Agent(tools=[forecast_tool])
    forecast_tool = EconomicForecastTool()

    # 模拟用户自然语言输入
    user_input = "请预测2026年美国的GDP增长趋势"

    # 参数解析：自然语言 → 结构化参数
    structured_params = parse_input(user_input)
    print_parameters(structured_params)

    # 传入工具执行（结构化参数直接 .get() 取值）
    tool_output = forecast_tool.call(structured_params)
    print("\n--- 工具输出结果 ---")
    print(tool_output)

    # 构造最终Prompt交由Qwen生成回答
    prompt = f"""请根据以下工具数据生成简洁经济解读：

工具输出：{tool_output}
问题原文：{user_input}
请用政策分析师的视角进行总结："""

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
    print("\n--- Qwen3.0 输出结果 ---")
    print(result_content)
