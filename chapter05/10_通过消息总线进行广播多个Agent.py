# 10_通过消息总线进行广播多个Agent.py（原样保留）
# 通过消息总线实现多个Agent之间的通信，模拟大规模Agent网络中的消息总线。
# 每个Agent负责处理任务的一部分，最后将结果汇总到一个中心Agent（AgentD）。
#
# 本篇三个新知识点：
#   1) 消息总线升级：AgentHub 在 09 篇 A2AProtocol 基础上新增 broadcast（一对多广播）
#   2) 并行分支图：agentA 后分叉两条边（→B、→C 并行执行），再汇聚到 agentD（扇出-汇聚模式）
#   3) 随机分工：random.choice 模拟分布式系统的任务分配不确定性
#
# 【教材预期输出勘误（重要）】
#   教材第 4-8 行预期输出中的最后一条：
#     {'AgentD_results': ['AgentD完成:...', 'AgentD完成:...', 'AgentD完成:...']}
#   与实际代码不符——agent_d_node 返回的键是 AgentD_conclusion，值是" | ".join 拼的字符串，
#   不是名为 AgentD_results 的列表。实测输出见本文件尾部。
#   另外 AgentB/AgentC 的分工是 random.choice 随机决定，教材展示的只是一种可能，
#   每次运行都不同（可能出现任务重复、任务漏做、极端情况全空）——这正是随机模拟的本意。
#
# 原写法：class State(Dict): pass
# 原写法的问题：与 01-09 篇相同——langgraph 1.x 靠 State 类的字段注解构建状态 schema，
#   Dict 子类没有字段注解，实测 graph.invoke() 返回 None（静默失败，系列第十次）。
# 原写法代码（注释保留）：
# from langgraph.graph import StateGraph, END
# from typing import Dict, List
# import time
# import random
# import json
#
# class State(Dict):
#     pass

# 改写：State 改用 TypedDict（五个字段注解）。
# 【必须包含 query 字段——09 篇的实测教训】漏声明节点会读的入口键，
#   LangGraph 1.x 会静默裁剪该输入键（不报错），agent_a_node 拿到空 query，
#   拆出的任务变成"-子任务1"（前缀丢失）。AgentHub、四个节点、图构建、invoke 全部原样保留。
from langgraph.graph import StateGraph, END
from typing import Dict, List, TypedDict
import time
import random
import json

# 定义状态（改写：TypedDict + 五个字段注解，含入口键 query）
class State(TypedDict):
    query: str
    AgentA_tasks: List[str]
    AgentB_results: List[str]
    AgentC_results: List[str]
    AgentD_conclusion: str

# 定义扩展性通信中心，大规模Agent网络中的消息总线（原样保留）
# 与 09 篇 A2AProtocol 的差异：新增 broadcast——一条消息同时投递给多个 Agent
class AgentHub:
    def __init__(self):
        self.messages = []

    def send(self, sender: str, receiver: str, content: Dict):
        message = {
            "sender": sender,
            "receiver": receiver,
            "timestamp": time.time(),
            "content": content
        }
        self.messages.append(message)

    # 广播：循环调用单播，等效于"给每个订阅者各寄一份"（原样保留）
    def broadcast(self, sender: str, content: Dict, agents: List[str]):
        for agent in agents:
            self.send(sender, agent, content)

    def receive(self, agent: str):
        inbox = [msg for msg in self.messages if msg["receiver"] == agent]
        return inbox

hub = AgentHub()

# 节点1：AgentA负责科研问题分解并广播任务（原样保留）
def agent_a_node(state: State) -> State:
    query = state.get("query", "")
    sub_tasks = [f"{query}-子任务{i}" for i in range(1, 4)]
    hub.broadcast("AgentA", {"tasks": sub_tasks}, ["AgentB", "AgentC"])
    return {"AgentA_tasks": sub_tasks}

# 节点2：AgentB接收部分任务并处理（原样保留）
# 教学点：B 和 C 收到的是同一份广播（tasks 列表相同），
#   各自用 random.choice 独立随机挑选——所以可能出现重复做同一任务、或都没人做某任务
def agent_b_node(state: State) -> State:
    inbox = hub.receive("AgentB")
    if inbox:
        tasks = inbox[-1]["content"]["tasks"]
        results = [f"AgentB完成:{t}" for t in tasks if random.choice([True, False])]
        hub.send("AgentB", "AgentD", {"results": results})
        return {"AgentB_results": results}
    return {"AgentB_results": []}

# 节点3：AgentC接收部分任务并处理（原样保留）
def agent_c_node(state: State) -> State:
    inbox = hub.receive("AgentC")
    if inbox:
        tasks = inbox[-1]["content"]["tasks"]
        results = [f"AgentC完成:{t}" for t in tasks if random.choice([True, False])]
        hub.send("AgentC", "AgentD", {"results": results})
        return {"AgentC_results": results}
    return {"AgentC_results": []}

# 节点4：AgentD汇总结果并输出最终结论（原样保留）
# 教学点：扇入汇聚——遍历收件箱全部消息（B 和 C 各一条），extend 拼成总结果。
#   注意返回键是 AgentD_conclusion（字符串），教材预期输出的 AgentD_results 键是笔误
def agent_d_node(state: State) -> State:
    inbox = hub.receive("AgentD")
    aggregated = []
    for msg in inbox:
        aggregated.extend(msg["content"]["results"])
    conclusion = " | ".join(aggregated) if aggregated else "未获得有效结果"
    return {"AgentD_conclusion": conclusion}

# 构建任务图（原样保留——本篇是系列第一个并行分支图）
# agentA 之后两条边分叉：agentB 与 agentC 在同一个 superstep 中并行执行；
# agentB→agentD 与 agentC→agentD 汇聚：agentD 等两个分支都完成后才执行（屏障语义）
builder = StateGraph(State)
builder.add_node("agentA", agent_a_node)
builder.add_node("agentB", agent_b_node)
builder.add_node("agentC", agent_c_node)
builder.add_node("agentD", agent_d_node)

builder.set_entry_point("agentA")
builder.add_edge("agentA", "agentB")
builder.add_edge("agentA", "agentC")
builder.add_edge("agentB", "agentD")
builder.add_edge("agentC", "agentD")
builder.add_edge("agentD", END)

graph = builder.compile()

# 执行任务流（原样保留）
result = graph.invoke({"query": "科研协作任务"})
print(result)

# 输出所有通信消息（原样保留）
print(json.dumps(hub.messages, ensure_ascii=False, indent=2))


# 实测输出（B/C 随机分工，每次运行不同；timestamp 为实时值）：
# {'query': '科研协作任务',
#  'AgentA_tasks': ['科研协作任务-子任务1', '科研协作任务-子任务2', '科研协作任务-子任务3'],
#  'AgentB_results': ['AgentB完成:科研协作任务-子任务1', 'AgentB完成:科研协作任务-子任务3'],
#  'AgentC_results': ['AgentC完成:科研协作任务-子任务2', 'AgentC完成:科研协作任务-子任务3'],
#  'AgentD_conclusion': 'AgentB完成:科研协作任务-子任务1 | AgentB完成:科研协作任务-子任务3 | AgentC完成:科研协作任务-子任务2 | AgentC完成:科研协作任务-子任务3'}
# 注意两点（与教材预期的差异）：
#   1) 最后的键是 AgentD_conclusion（字符串拼接），教材写的 AgentD_results 列表不存在
#   2) 子任务3 被 B 和 C 都做了（重复），教材展示的"恰好一人一个"只是随机的一种可能
# hub.messages 共 4 条：A 广播给 B/C 各 1 条，B/C 汇报给 D 各 1 条
