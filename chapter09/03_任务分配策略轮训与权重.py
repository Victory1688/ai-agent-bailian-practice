# 【例9-3】任务分配策略：轮询与权重
#
# 核心问题：如何将子任务合理地分配给不同智能体，以保障系统整体的高并发处理性能、
#           毫秒级响应效率，以及各个节点的任务负载均衡？
# 轮询分配 (Round-Robin)：将任务按请求顺序均匀、依次地分配给一组可用的智能体，形成循环分配队列。
# 加权分配 (Weighted Dispatch)：为每个智能体节点赋予一个"权重系数"，系统根据权重占比进行概率性的任务分配。
#
# 改写前的问题：
#   1) qwen_agent.Agent/Message/Tool——虚构框架（char02 起已多次确认不存在于真实环境）
#   2) EconomicAgent 的 call() 返回硬编码模拟数据（教材刻意为之，保留原样）
#   3) ControlSystem 内部的 agent.chat() 是唯一真实 LLM 调用点
# 备注：本篇原代码无 redis 调用，无需按 cache.json 方案替换
# 改写策略：
#   - TaskDispatcher 的两种调度策略（轮询 / 加权）+ EconomicAgent 模拟类 + 主流程双策略对比
#     原样保留（本篇核心教学资产：调度器设计）
#   - EconomicAgent 去掉虚构 Tool 继承，改为纯类
#   - agent.chat() → dashscope.Generation.call（qwen-plus）

# 原写法（注释保留）：虚构框架 import
# from qwen_agent.agent import Agent
# from qwen_agent.context import Message
# from qwen_agent.tools import Tool

import os
import random
from typing import List, Dict
import dashscope

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# ========= 模拟多个财经Agent（改写：去掉虚构 Tool 继承，纯类；quality 评分 + call 模拟逻辑原样保留） =========
class EconomicAgent:
    """财经子Agent：模拟分析任务，quality 属性表示性能评分（越高越准）"""
    def __init__(self, name, quality: float):
        # 原写法：super().__init__(name=name, description=f"财经预测Agent（性能评分：{quality}）")
        self.name = name
        self.description = f"财经预测Agent（性能评分：{quality}）"
        self.quality = quality   # 核心属性：调度器可据此做加权（本篇的权重与 quality 独立配置）

    def call(self, query: str) -> str:
        # 模拟分析结果（原样保留）：random.random() 让每次输出略有差异
        return f"[{self.name}] 分析完成：预计增长为 {round(5 + random.random(), 2)}%。性能评分为 {self.quality}"

# ========= 调度器定义（原样保留——本篇灵魂） =========
class TaskDispatcher:
    """任务调度器：根据策略（轮询 / 加权）从 Agent 池中选一个来干活"""
    def __init__(self, agents: List, strategy: str = "round_robin", weights: Dict[str, int] = None):
        self.agents = agents
        self.strategy = strategy
        self.weights = weights or {}
        self.counter = 0   # 轮询专用计数器
        # 加权策略预构造"重池"——把 Agent 按权重复制多份，之后 random.choice 直接用
        self.pool = self._build_weighted_pool() if strategy == "weighted" else agents

    def _build_weighted_pool(self):
        """构造加权重池：agent 权重几就复制几份，之后 random.choice 自然按权重概率选"""
        pool = []
        for agent in self.agents:
            weight = self.weights.get(agent.name, 1)   # 没配置权重默认 1
            pool.extend([agent] * weight)
        return pool

    def dispatch(self):
        """选一个 Agent 出来干活"""
        if self.strategy == "round_robin":
            agent = self.agents[self.counter % len(self.agents)]
            self.counter += 1
            return agent
        elif self.strategy == "weighted":
            return random.choice(self.pool)   # 重池里选，权重高的自然被选概率大

# ========= 主控系统（改写：agent.chat → dashscope.Generation.call） =========
class ControlSystem:
    """主控：拿到调度器选出来的 Agent 调 call()，再把结果交 LLM 润色"""
    def __init__(self, dispatcher: TaskDispatcher):
        self.dispatcher = dispatcher
        # 原写法：self.agent = Agent(tools=dispatcher.agents)
        # 改写：删掉虚构 Agent 实例——主控直调 dashscope 做最终整合

    def run_task(self, query: str) -> str:
        tool = self.dispatcher.dispatch()
        print(f"\n→ 当前调度策略：{self.dispatcher.strategy.upper()}")
        print(f"→ 分配给Agent：{tool.name}")
        tool_output = tool.call(query)

        prompt = f"""请根据以下Agent的分析生成最终简明财经预测：

用户问题：{query}
Agent分析：{tool_output}
"""

        # 原写法：result = self.agent.chat(messages=[Message(role="user", content=prompt)])
        # 改写：dashscope.Generation.call（qwen-plus）
        print("调用qwen-plus生成中……")
        response = dashscope.Generation.call(
            model="qwen-plus",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=512,
            result_format='message'
        )
        return response.output.choices[0].message.content

# ========= 启动流程（原样保留——双策略对比是本篇核心演示） =========
if __name__ == "__main__":
    print("=== 启动任务调度系统 ===")

    # 创建三个经济Agent副本（quality 0.85 / 0.90 / 0.95，越右越准）
    agent1 = EconomicAgent("econ_agent_1", 0.85)
    agent2 = EconomicAgent("econ_agent_2", 0.90)
    agent3 = EconomicAgent("econ_agent_3", 0.95)

    # ===== 轮询策略：1→2→3→1→2→3 均匀分配 =====
    print("\n===== 轮询策略 ROUND-ROBIN =====")
    round_dispatcher = TaskDispatcher([agent1, agent2, agent3], strategy="round_robin")
    system_rr = ControlSystem(dispatcher=round_dispatcher)
    for i in range(3):
        print(f"\n--- 轮询第 {i+1} 次 ---")
        print(system_rr.run_task("预测2024年中国GDP增长"))

    # ===== 加权策略：权重 1:1:3 → econ_agent_3 分到约 60% 的任务 =====
    print("\n===== 加权策略 WEIGHTED =====")
    weight_map = {"econ_agent_1": 1, "econ_agent_2": 1, "econ_agent_3": 3}
    weighted_dispatcher = TaskDispatcher([agent1, agent2, agent3], strategy="weighted", weights=weight_map)
    system_weighted = ControlSystem(dispatcher=weighted_dispatcher)
    for i in range(3):
        print(f"\n--- 加权第 {i+1} 次 ---")
        print(system_weighted.run_task("预测2024年中国GDP增长"))
