# 【例9-7】 状态同步与锁控制策略
# 核心问题
#在并发环境中，若多个智能体同时对共享状态进行读写操作，极易引发竞态条件、数据覆盖或逻辑错误，破坏系统的稳定性。
#解决方案：同步与互斥
#•状态同步：对关键共享资源的读写逻辑进行严格的序列化与受控管理。
#•锁控制：引入互斥锁(Mutex)或读写锁(RWLock)，将关键代码标记为"临界区"，强制保证在任意时刻只有一个线程能进入执行。
#
# 改写前的问题：
#   1) qwen_agent.Agent/Message——虚构框架（char02 起已多次确认不存在于真实环境）
#   2) LoggingAgent.run() 内每次新建 Agent() 实例再 chat()（虚构 API）
#   3) 主控的 summary_agent = Agent() 同样是虚构实例化
#   4) write_log 里的 time.sleep(0.5) 模拟写入延迟（教材刻意为之，保留原样——
#      它让"锁内临界区耗时"变得肉眼可见，3 个线程串行写入 = 至少 1.5 秒）
# 备注：本篇原代码无 redis 调用，无需按 cache.json 方案替换
# 改写策略：
#   - SharedLog 的 Lock 临界区保护 + LoggingAgent 线程化并发 + 主流程汇总
#     原样保留（本篇核心教学资产：互斥锁保护共享状态）
#   - Agent().chat() → dashscope.Generation.call（qwen-plus），Message → dict

# 原写法（注释保留）：虚构框架 import
# from qwen_agent.agent import Agent
# from qwen_agent.context import Message
# from qwen_agent.tools import Tool

import os
import time
import threading
from typing import List
import dashscope

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# ========= 共享状态类（原样保留——本篇灵魂） =========
class SharedLog:
    """共享日志：多线程写入同一个列表，Lock 保证写入不串不丢"""
    def __init__(self):
        self.logs: List[str] = []
        self.lock = threading.Lock()

    def write_log(self, agent_name: str, message: str):
        with self.lock:                # 临界区开始：同一时刻只有一个线程能进来
            entry = f"[{agent_name}]：{message}"
            print(f"→ 写入日志：{entry}")
            self.logs.append(entry)
            time.sleep(0.5)  # 模拟写入延迟（原样保留：放大临界区耗时，观察串行效果）
        # 临界区结束：with 块退出时自动释放锁

    def read_logs(self) -> str:
        return "\n".join(self.logs)

# ========= 子Agent定义（改写：Agent().chat → dashscope.Generation.call） =========
class LoggingAgent(threading.Thread):
    """日志Agent线程：各自独立调 LLM，完成后往共享日志写一条"""
    def __init__(self, name: str, log: SharedLog, query: str):
        super().__init__()
        self.name = name
        self.shared_log = log
        self.query = query
        self.response = ""

    def run(self):
        print(f"→ {self.name}开始处理任务")
        # 原写法：agent = Agent(); msg = Message(role="user", content=self.query)
        #         result = agent.chat(messages=[msg]); self.response = result.content
        # 改写：dashscope.Generation.call（qwen-plus），每个线程独立调
        response = dashscope.Generation.call(
            model="qwen-plus",
            messages=[{"role": "user", "content": self.query}],
            temperature=0.3,
            max_tokens=512,
            result_format='message'
        )
        self.response = response.output.choices[0].message.content
        self.shared_log.write_log(self.name, self.response)
        print(f"→ {self.name}完成写入")

# ========= 主控系统（改写：Agent().chat → dashscope.Generation.call） =========
if __name__ == "__main__":
    print("=== 启动状态同步与锁控制模拟系统 ===")

    shared_log = SharedLog()

    # 启动多个Agent模拟并发写入
    queries = [
        "请分析中国当前的宏观经济政策",
        "请概述当前全球通货膨胀形势",
        "请简要预测人工智能在2025年的发展趋势"
    ]
    agents = []
    for i, q in enumerate(queries):
        agent = LoggingAgent(f"Agent_{i+1}", shared_log, q)
        agents.append(agent)

    for agent in agents:
        agent.start()
    for agent in agents:
        agent.join()

    # 总结共享日志内容
    print("\n→ 所有Agent写入完成，准备总结：")
    print(shared_log.read_logs())

    summary_prompt = "以下是三个Agent的分析日志，请总结关键内容：\n" + shared_log.read_logs()
    # 原写法：summary_agent = Agent()
    #         final_result = summary_agent.chat(messages=[Message(role="user", content=summary_prompt)])
    # 改写：dashscope.Generation.call（qwen-plus）
    print("\n调用qwen-plus生成总结中……")
    final_response = dashscope.Generation.call(
        model="qwen-plus",
        messages=[{"role": "user", "content": summary_prompt}],
        temperature=0.3,
        max_tokens=512,
        result_format='message'
    )

    print("\n--- Qwen3.0输出总结 ---")
    print(final_response.output.choices[0].message.content)
