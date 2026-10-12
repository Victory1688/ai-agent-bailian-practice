# 【例9-6】上下文切换与隔离设计
#
# 核心痛点：状态污染与响应混乱
#   如果上下文无法有效隔离，多任务并发时，历史对话、任务参数极易相互渗透，
#   导致智能体逻辑错乱，无法准确响应用户需求。
# 技术方案：动态切换与作用域隔离
#   • 上下文切换：实现上下文环境的动态加载、暂停、恢复与清除，确保任务间无残留。
#   • 上下文隔离：引入命名空间与任务ID机制，严格管理每个任务上下文的生命周期，物理与逻辑上双重隔离。
#
# 改写前的问题：
#   1) qwen_agent.Message——虚构消息类（实际就是 {"role":..., "content":...} 字典）
#   2) qwen_agent.Agent——虚构框架（Agent() 无参实例化后 chat() 是虚构 API）
#   3) AgentTask.run() 内部的 agent.chat() 是唯一真实 LLM 调用点（原代码每次调都新建 Agent 实例）
# 备注：本篇原代码无 redis 调用，无需按 cache.json 方案替换
# 改写策略：
#   - ContextScope 的 task_id 命名空间隔离 + AgentTask 线程化多任务执行
#     原样保留（本篇核心教学资产：上下文隔离）
#   - Message 类 → 普通 dict；Agent().chat() → dashscope.Generation.call（qwen-plus）
#   - 每个 AgentTask 内部有自己的 LLM 调用，三个并行任务各自独立

# 原写法（注释保留）：虚构框架 import
# from qwen_agent.agent import Agent
# from qwen_agent.context import Message

import os
import time
import threading
from typing import Dict, List
import dashscope

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# ========= 上下文容器类（原样保留——本篇灵魂） =========
class ContextScope:
    """上下文作用域：用 task_id 做 key，每个任务有独立的对话历史列表"""
    def __init__(self):
        self.contexts: Dict[str, list] = {}   # 命名空间：task_id → 消息列表

    def create(self, task_id: str):
        """为新任务创建独立的上下文列表"""
        self.contexts[task_id] = []

    def append(self, task_id: str, message: dict):
        """往指定任务的上下文追加消息（改写：Message → dict）"""
        if task_id in self.contexts:
            self.contexts[task_id].append(message)

    def get(self, task_id: str) -> list:
        """取出指定任务的完整上下文列表"""
        return self.contexts.get(task_id, [])

    def destroy(self, task_id: str):
        """销毁指定任务的上下文（清理内存）"""
        if task_id in self.contexts:
            del self.contexts[task_id]

# ========= 多任务Agent任务模拟（改写：Message → dict；Agent → dashscope） =========
class AgentTask(threading.Thread):
    """一个独立的任务线程：有自己的 task_id、独立的上下文、独立的 LLM 调用"""
    def __init__(self, task_id: str, user_input: str, scope: ContextScope):
        super().__init__()
        self.task_id = task_id
        self.user_input = user_input
        self.scope = scope
        self.result = None

    def run(self):
        print(f"→ 启动任务[{self.task_id}]")

        # Step 1: 为自己创建独立的上下文空间
        self.scope.create(self.task_id)

        # Step 2: 把用户输入追加到自己的上下文（改写：Message → dict）
        self.scope.append(self.task_id, {"role": "user", "content": self.user_input})

        # Step 3: 取出自己的上下文，调 LLM（改写：Agent().chat → dashscope.Generation.call）
        history = self.scope.get(self.task_id)
        # 原写法：agent = Agent(); result = agent.chat(messages=history)
        # 改写：dashscope.Generation.call（qwen-plus），每个线程独立调
        response = dashscope.Generation.call(
            model="qwen-plus",
            messages=history,
            temperature=0.3,
            max_tokens=512,
            result_format='message'
        )
        assistant_content = response.output.choices[0].message.content

        # Step 4: 把 LLM 回复追加回自己的上下文
        self.scope.append(self.task_id, {"role": "assistant", "content": assistant_content})

        self.result = assistant_content
        print(f"→ 任务[{self.task_id}]完成，结果前50字：{self.result[:50]}...")

# ========= 主流程（改写：Agent().chat → dashscope.Generation.call） =========
if __name__ == "__main__":
    print("=== 启动多任务上下文隔离系统 ===")

    context_scope = ContextScope()

    # 三个并行任务，三个完全不同的主题
    tasks = [
        AgentTask("task_001", "请简要说明当前中国宏观经济趋势", context_scope),
        AgentTask("task_002", "总结2023年人工智能的发展方向", context_scope),
        AgentTask("task_003", "请写一段300字的自然语言处理技术简介", context_scope)
    ]

    # 并行启动所有任务
    print("\n--- 并行启动三个任务 ---")
    t0 = time.time()
    for task in tasks:
        task.start()

    for task in tasks:
        task.join()
    elapsed = time.time() - t0
    print(f"\n三个任务全部完成，耗时 {elapsed:.1f} 秒（并行）")

    # 检查上下文隔离：每个 task_id 的上下文应该只有自己的消息
    print("\n--- 上下文隔离检查 ---")
    for t in tasks:
        ctx = context_scope.get(t.task_id)
        roles = [m["role"] for m in ctx]
        print(f"  {t.task_id}: {len(ctx)} 条消息，角色序列 {roles}（无其他任务内容 = 隔离成功）")

    # 汇总任务结果交由 LLM 整理
    # 原写法：final_agent = Agent(); summary = final_agent.chat(messages=[Message(...)])
    # 改写：dashscope.Generation.call（qwen-plus）
    combined_prompt = "以下是三个并行任务的输出，请统一生成一段内容总结：\n"
    for t in tasks:
        combined_prompt += f"\n【{t.task_id}】：{t.result}"

    print("\n调用qwen-plus生成汇总中……")
    response = dashscope.Generation.call(
        model="qwen-plus",
        messages=[{"role": "user", "content": combined_prompt}],
        temperature=0.3,
        max_tokens=512,
        result_format='message'
    )

    print("\n--- 汇总总结 ---")
    print(response.output.choices[0].message.content)
