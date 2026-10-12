# 【例7-6】上下文存储与回调机制：提示词缓存与快速回放机制
#
# 当前痛点与挑战
#   重复的提示词构造与上下文拼接过程，会显著增加系统的计算开销，
#   不仅造成算力资源的浪费，还会直接导致用户侧的响应延迟，降低体验。
# 核心解决方案
#   引入"提示词(Prompt)缓存与快速回放"机制，识别并存储高频使用的提示词与上下文组合，
#   在后续请求中直接复用，避免重复构建成本。
#
# 改写前的问题：
#   1) qwen_agent.Agent/Message/Tool——虚构框架（char02 已多次确认不存在）
#   2) CACHE_FILE 相对路径——同 05 篇 LOG_FILE，写到运行目录而非脚本目录
#   3) tool_output 是硬编码字符串——未真实调 EconomicPredictor.call()，教学简化
# 改写策略：
#   - hash_prompt / load_prompt_cache / save_prompt_cache / check_prompt_cache 原样保留
#     （缓存三件套 + 命中判断，本篇核心教学资产）
#   - EconomicPredictor 去掉虚构 Tool 继承
#   - agent.chat() → dashscope.Generation.call（qwen-plus）
#   - CACHE_FILE 改为脚本目录绝对路径（原写法注释保留）

# 原写法（注释保留）：虚构框架 import
# from qwen_agent.agent import Agent
# from qwen_agent.context import Message
# from qwen_agent.tools import Tool

import json
import hashlib
import os
from typing import Dict, List
import dashscope

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# ========= 缓存路径配置（改写：相对路径 → 脚本目录绝对路径） =========
# 原写法：CACHE_FILE = "prompt_cache.json"（相对路径，写到运行目录）
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompt_cache.json")

# ========= 工具定义：DeepSeek模拟分析工具（改写：去掉虚构 Tool 继承） =========
class EconomicPredictor:
    """经济预测模拟工具（改写：去掉虚构 Tool 继承，纯类）"""
    def __init__(self):
        # 原写法：super().__init__(name="econ_predictor", description="经济预测模拟工具")
        self.name = "econ_predictor"
        self.description = "经济预测模拟工具"

    def call(self, query: str) -> str:
        print("→ DeepSeek-V1调用：分析完成")
        return f"[DeepSeek-V1] 预测结果：{query} 预计增长率为5.3%。"

# ========= 缓存三件套（原样保留——本篇核心教学资产） =========

def hash_prompt(prompt: str) -> str:
    """用 MD5 对完整 prompt 做哈希，作为缓存 key"""
    return hashlib.md5(prompt.encode("utf-8")).hexdigest()

def load_prompt_cache() -> Dict[str, str]:
    """从 JSON 文件读取缓存字典；文件不存在则返回空 dict"""
    if not os.path.exists(CACHE_FILE):
        return {}
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_prompt_cache(cache: Dict[str, str]):
    """把完整缓存字典写回 JSON 文件（覆盖写，非追加）"""
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

def check_prompt_cache(prompt: str, cache: Dict[str, str]) -> str:
    """查缓存：算 hash → 看字典里有没有，命中返回缓存值，未命中返回空串"""
    h = hash_prompt(prompt)
    return cache.get(h, "")

# ========= 主流程入口（改写：agent.chat→dashscope；tool_output 保持硬编码） =========
if __name__ == "__main__":
    print("=== Prompt缓存与快速回放机制测试系统 ===")

    # 原写法：agent = Agent(tools=[EconomicPredictor()])
    prompt_cache = load_prompt_cache()

    # 构造复杂任务 prompt（硬编码，与 05 篇真实调 tool 不同）
    user_query = "请结合当前宏观经济环境预测2024年GDP走势，并指出主要影响因素"
    system_prompt = "你是一位宏观经济分析师，回答应包含数据推理、趋势预测与政策建议"
    tool_output = "[Tool] 当前CPI指数为2.1%，PMI为51.4，消费同比上升6.2%"

    full_prompt = f"""【系统提示】
{system_prompt}
【外部工具输出】
{tool_output}
【用户提问】
{user_query}
请基于上述内容生成结构化分析结果"""

    prompt_hash = hash_prompt(full_prompt)
    print(f"→ 任务哈希ID：{prompt_hash}")

    # 检查缓存是否命中
    cached_output = check_prompt_cache(full_prompt, prompt_cache)
    if cached_output:
        print("\n--- 缓存命中，直接回放 ---")
        print(cached_output)
    else:
        print("\n--- 未命中缓存，调用模型生成 ---")
        # 原写法：result = agent.chat(messages=[Message(role="user", content=full_prompt)])
        # 改写：dashscope.Generation.call（qwen-plus）
        print("调用qwen-plus生成中……")
        response = dashscope.Generation.call(
            model="qwen-plus",
            messages=[{"role": "user", "content": full_prompt}],
            temperature=0.3,
            max_tokens=512,
            result_format='message'
        )
        generated_answer = response.output.choices[0].message.content
        print(generated_answer)

        # 写入缓存
        prompt_cache[prompt_hash] = generated_answer
        save_prompt_cache(prompt_cache)

    # 查看当前缓存总数
    print(f"\n当前缓存条目数量：{len(prompt_cache)}")
