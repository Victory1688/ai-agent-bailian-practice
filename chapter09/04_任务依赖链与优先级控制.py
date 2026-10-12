# 【例9-4】任务依赖链与优先级控制
#
# 核心概念解析：
#   任务依赖链：描述任务间的前后置约束，通常以有向无环图 (DAG) 建模，避免循环依赖死锁。
#   优先级控制：基于任务重要性、紧急度或业务价值排序，解决同层级或无依赖任务的执行顺序冲突。
#
# 调度执行逻辑：
#   1. 解锁任务：优先扫描并执行所有无前置依赖的"根任务"。
#   2. 级联触发：任务完成后，自动将其下游所有直接依赖任务解锁。
#   3. 择优执行：在同一批次可执行的任务池中，按照预设优先级规则调度执行。
#
# 改写前的问题：
#   1) qwen_agent.Agent/Message——虚构框架（char02 起已多次确认不存在于真实环境）
#   2) Agent() 实例化——原写法没传 tools 参数（比前几篇更简化，但仍是虚构）
#   3) 4 个任务函数用 time.sleep(1) 模拟耗时（原样保留，教学重点是调度逻辑）
# 备注：本篇原代码无 redis 调用，无需按 cache.json 方案替换
# 改写策略：
#   - Task + TaskExecutor 的 DAG 调度逻辑（heapq 优先级队列 + depends 解锁机制）
#     + 4 个任务函数原样保留（本篇核心教学资产：DAG + 优先级调度）
#   - Agent().chat() → dashscope.Generation.call（qwen-plus）

# 原写法（注释保留）：虚构框架 import
# from qwen_agent.agent import Agent
# from qwen_agent.context import Message

import os
import time
import heapq
from typing import Dict, List, Callable
import dashscope

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# ========= 任务定义类（原样保留） =========
class Task:
    """任务四元组：id + func + depends + priority + 执行状态"""
    def __init__(self, id: str, func: Callable, depends: List[str] = None, priority: int = 1):
        self.id = id
        self.func = func             # 任务要执行的函数（无参数，结果存 self.result）
        self.depends = depends or [] # 前置依赖的任务 ID 列表
        self.priority = priority     # 优先级（越大越高）
        self.executed = False        # 是否已执行（标记位）
        self.result = None           # 执行结果

# ========= 任务图执行器（原样保留——本篇灵魂） =========
class TaskExecutor:
    """DAG + 优先级队列调度器：先按依赖解锁，同层按优先级择优"""
    def __init__(self):
        self.tasks: Dict[str, Task] = {}
        self.execution_log = []

    def register(self, task: Task):
        """注册任务到执行器"""
        self.tasks[task.id] = task

    def _can_execute(self, task: Task) -> bool:
        """依赖检查：所有前置任务都已执行才能开始"""
        return all(self.tasks[dep].executed for dep in task.depends)

    def execute(self):
        """主调度循环（原样保留——核心算法）"""
        pq = []   # 优先级堆（heapq 是小堆，存 -priority 让大优先级先出）

        # Step 1：把所有"根任务"（无前置依赖）入堆
        for task in self.tasks.values():
            if not task.depends:
                heapq.heappush(pq, (-task.priority, task.id))

        # Step 2：堆不为空就循环
        while pq:
            _, tid = heapq.heappop(pq)     # 堆顶 = 当前最高优先级的可执行任务
            task = self.tasks[tid]

            if task.executed:
                continue                  # 已执行过（可能之前入堆了但还没轮到）
            if not self._can_execute(task):
                continue                  # 依赖还没满足（可能之前入堆时还没解锁）

            # 执行任务
            print(f"\n→ 执行任务：{tid}（优先级：{task.priority}）")
            task.result = task.func()
            task.executed = True
            self.execution_log.append((tid, task.result))

            # Step 3：解锁下游——检查所有未执行任务，看哪些现在可以了
            for t in self.tasks.values():
                if not t.executed and self._can_execute(t):
                    heapq.heappush(pq, (-t.priority, t.id))

    def get_summary(self) -> str:
        """导出执行日志汇总"""
        return "\n".join([f"{tid}: {res}" for tid, res in self.execution_log])

# ========= 模拟Agent行为函数（原样保留——sleep 模拟耗时） =========
def task_fetch_news():
    time.sleep(1)
    return "抓取完成：2024年CPI增速放缓、出口回升"

def task_model_analysis():
    time.sleep(1)
    return "分析完成：预计GDP增长5.4%"

def task_generate_graph():
    time.sleep(1)
    return "图表渲染完成"

def task_generate_report():
    time.sleep(1)
    return "最终报告生成完毕"

# ========= 主控整合（改写：Agent().chat → dashscope.Generation.call） =========
if __name__ == "__main__":
    print("=== 启动带依赖与优先级调度的Agent任务系统 ===")
    executor = TaskExecutor()

    # 注册任务：ID、函数、依赖项、优先级（越大越高）
    # 依赖链：fetch_news(3) → model(4) → graph(1)
    #                                  → report(2) （model 是 graph/report 的共同上游）
    executor.register(Task("fetch_news", task_fetch_news, priority=3))
    executor.register(Task("model", task_model_analysis, depends=["fetch_news"], priority=4))
    executor.register(Task("graph", task_generate_graph, depends=["model"], priority=1))
    executor.register(Task("report", task_generate_report, depends=["model"], priority=2))

    executor.execute()

    # 汇总并调用 LLM 生成总结
    # 原写法：agent = Agent(); result = agent.chat(messages=[Message(role="user", content=prompt)])
    # 改写：dashscope.Generation.call（qwen-plus）
    print("\n调用qwen-plus生成总结中……")
    prompt = f"""以下是多任务智能体执行结果，请生成一段完整分析总结：

{executor.get_summary()}"""
    response = dashscope.Generation.call(
        model="qwen-plus",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=512,
        result_format='message'
    )
    print("\n--- Qwen3.0输出总结 ---")
    print(response.output.choices[0].message.content)
