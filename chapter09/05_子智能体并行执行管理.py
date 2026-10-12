# 【例9-5】子智能体并行执行管理
#
# 案例目标：构建一个支持多智能体并行协作的执行系统，解决串行任务处理效率低的问题。
# 核心是利用 Python 多线程机制，同时触发并管理多个子智能体的任务流程，
# 通过线程锁保证共享数据的安全写入，最终统一汇总所有子任务的执行结果。
#
# 改写前的问题：
#   1) qwen_agent.Agent/Message/Tool——虚构框架（char02 起已多次确认不存在于真实环境）
#   2) 三个子 Agent 的 call() 用 time.sleep() 模拟耗时（教材刻意为之，保留原样）
#   3) Agent() 实例化没传 tools 参数（同 04 篇，仍是虚构）
# 备注：本篇原代码无 redis 调用，无需按 cache.json 方案替换
# 改写策略：
#   - ParallelExecutor 的 threading + Lock 并行机制 + 三个子 Agent + 主流程汇总
#     原样保留（本篇核心教学资产：并行执行 + 线程安全）
#   - 子 Agent 去掉虚构 Tool 继承，改为纯类
#   - Agent().chat() → dashscope.Generation.call（qwen-plus）

# 原写法（注释保留）：虚构框架 import
# from qwen_agent.agent import Agent
# from qwen_agent.context import Message
# from qwen_agent.tools import Tool

import os
import time
import threading
from typing import Dict
import dashscope

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# ========= 子Agent定义（改写：去掉虚构 Tool 继承，纯类；sleep 模拟耗时原样保留） =========
class PolicyAgent:
    """政策分析子Agent：模拟耗时 1.2 秒"""
    def __init__(self):
        # 原写法：super().__init__(name="policy_agent", description="分析最新宏观政策")
        self.name = "policy_agent"
        self.description = "分析最新宏观政策"

    def call(self, _: str) -> str:
        time.sleep(1.2)   # 模拟耗时（原样保留）
        return "政策导向积极，财政刺激与减税政策持续发力。"

class SentimentAgent:
    """市场情绪子Agent：模拟耗时 1.5 秒"""
    def __init__(self):
        # 原写法：super().__init__(name="sentiment_agent", description="提取市场情绪")
        self.name = "sentiment_agent"
        self.description = "提取市场情绪"

    def call(self, _: str) -> str:
        time.sleep(1.5)   # 模拟耗时（原样保留）
        return "市场情绪整体乐观，投资者信心显著回暖。"

class TrendAgent:
    """趋势预测子Agent：模拟耗时 1.7 秒"""
    def __init__(self):
        # 原写法：super().__init__(name="trend_agent", description="预测经济增长趋势")
        self.name = "trend_agent"
        self.description = "预测经济增长趋势"

    def call(self, _: str) -> str:
        time.sleep(1.7)   # 模拟耗时（原样保留）
        return "预计2024年GDP增长为5.5%，主要来源于消费与出口复苏。"

# ========= 并行执行管理器（原样保留——本篇灵魂） =========
class ParallelExecutor:
    """并行执行器：多线程同时跑多个子 Agent，Lock 保护共享 results 字典"""
    def __init__(self):
        self.results: Dict[str, str] = {}   # 所有线程共享的结果字典
        self.lock = threading.Lock()         # 写 results 时加锁

    def run_agent(self, agent, name: str):
        """线程入口函数：调 agent.call()，加锁写共享字典"""
        print(f"→ 启动{name}")
        result = agent.call("")
        with self.lock:                    # 临界区：同一时刻只有一个线程能写 results
            self.results[name] = result
        print(f"→ {name}完成")

    def execute_all(self, agents: Dict):
        """启动所有子 Agent 并行执行，等全部完成后返回汇总"""
        threads = []
        for name, agent in agents.items():
            t = threading.Thread(target=self.run_agent, args=(agent, name))
            t.start()
            threads.append(t)
        for t in threads:
            t.join()                        # 屏障：等所有线程都结束
        return self.results

# ========= 主控整合（改写：Agent().chat → dashscope.Generation.call） =========
if __name__ == "__main__":
    print("=== 启动子Agent并行执行系统 ===")

    # 注册子 Agent（三个耗时不同的子 Agent）
    agents = {
        "政策分析": PolicyAgent(),      # 1.2s
        "市场情绪": SentimentAgent(),    # 1.5s
        "趋势预测": TrendAgent()         # 1.7s
    }

    # 并行执行 + 计时（新增：实测并行加速比）
    executor = ParallelExecutor()
    t0 = time.time()
    results = executor.execute_all(agents)
    elapsed = time.time() - t0
    print(f"\n并行执行总耗时：{elapsed:.2f}秒（串行预计 {1.2+1.5+1.7:.1f} 秒）")

    # 汇总生成 Prompt
    prompt = "请根据以下信息撰写2024年一季度中国经济简报：\n"
    for title, content in results.items():
        prompt += f"\n【{title}】：{content}"

    print("\n→ 汇总Prompt：")
    print(prompt)

    # 原写法：agent = Agent(); final_response = agent.chat(messages=[Message(role="user", content=prompt)])
    # 改写：dashscope.Generation.call（qwen-plus）
    print("\n调用qwen-plus生成中……")
    response = dashscope.Generation.call(
        model="qwen-plus",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=512,
        result_format='message'
    )
    print("\n--- Qwen3.0响应输出 ---")
    print(response.output.choices[0].message.content)
