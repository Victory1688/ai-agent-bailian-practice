# ========== A2A的多Agent通信协议传递 ==========
# 设计说明（教材尾部注释，原样保留）：
# 1. 自定义`A2AProtocol`类模拟多 Agent 通信协议，内置消息发送、消息接收，每条消息包含发送方、接收方、时间戳、内容；
# 2. 3 个 Agent 节点串行执行：
#    - AgentA：模拟检索数据，通过 A2A 发送消息给 AgentB
#    - AgentB：读取 A2A 消息，做文本分析，再转发消息给 AgentC
#    - AgentC：读取 AgentB 发来的分析内容，生成最终结论
# 3. LangGraph 负责编排节点顺序与状态追踪，A2A 负责 Agent 之间消息传递。
#
# 【重要辨析——教材"A2A"名的诚实说明】
#   真实世界的 A2A（Agent2Agent Protocol）是 Google 于 2025 年提出的开放协议（后捐给 Linux 基金会）：
#   Agent Card（能力发现）/ Task / Message 标准对象、JSON-RPC over HTTP 传输，
#   与 MCP 是"姊妹协议"——MCP 管 Agent 连接工具，A2A 管 Agent 与 Agent 之间协作。
#   教材的 A2AProtocol 只是**同进程内的消息列表存取类**——它与 A2A 协议毫无关系（08 篇的"MCP"同理）。
#   本篇真正教的概念是"消息传递范式"：Agent 之间不共享变量，靠"发消息/收消息"协作——
#   这个范式在分布式多 Agent（不同进程/机器）才是刚需，同进程教学演示只是它的婴儿版。

# 原写法：class State(Dict): pass
# 原写法的问题：与 01-08 篇相同——langgraph 1.x 靠 State 类的字段注解构建状态 schema，
#   Dict 子类没有字段注解，实测 graph.invoke() 返回 None（静默失败，系列第九次）。
# 原写法代码（注释保留）：
# from langgraph.graph import StateGraph, END
# from typing import Dict
# import json
# import time
#
# class State(Dict):
#     pass

# 改写：State 改用 TypedDict（三个字段注解）。A2AProtocol、三个节点、图构建、
#   invoke 与原版逐行一致（全部是纯本地代码，无大模型调用）。
from langgraph.graph import StateGraph, END
from typing import Dict, TypedDict
import json
import time

# 定义状态（改写：TypedDict + 字段注解）
# 【实测教学点】字段必须包含节点会读到的所有键：初版改写只声明了三个结果字段、漏了 query，
#   结果 LangGraph 1.x 把不在 schema 里的输入键静默裁剪——两次 invoke 全链路"未找到相关数据"。
#   这比 01-08 篇的"返回 None"更隐蔽：图正常跑完，数据悄悄丢在入口。
class State(TypedDict):
    query: str
    agentA_result: str
    agentB_analysis: str
    agentC_conclusion: str

# 定义A2A通信协议的基本实现（原样保留——同进程消息总线的教学模拟）
class A2AProtocol:
    def __init__(self):
        self.messages = []  # 存储通信信息

    # Agent发送消息（原样保留：每条消息含发送方/接收方/时间戳/内容）
    def send(self, sender: str, receiver: str, content: Dict):
        message = {
            "sender": sender,
            "receiver": receiver,
            "timestamp": time.time(),
            "content": content
        }
        self.messages.append(message)

    # Agent接收消息（原样保留：按收件人过滤出"收件箱"）
    def receive(self, agent: str):
        inbox = [msg for msg in self.messages if msg["receiver"] == agent]
        return inbox

# 初始化A2A协议（原样保留——模块级实例，所有节点共享同一个对象）
a2a = A2AProtocol()

# 节点1：AgentA执行检索并发送消息（原样保留）
def agent_a_node(state: State) -> State:
    query = state.get("query", "")
    db = {"langgraph": "LangGraph是一种任务图编排框架", "agent": "Agent系统依赖通信协议"}
    result = db.get(query.lower(), "未找到相关数据")
    a2a.send("AgentA", "AgentB", {"retrieved": result})
    return {"agentA_result": result}

# 节点2：AgentB接收消息并进行分析（原样保留）
# 教学点：inbox[-1] 取最新一条——同一收件人有多条消息时的取舍策略
def agent_b_node(state: State) -> State:
    inbox = a2a.receive("AgentB")
    if inbox:
        data = inbox[-1]["content"].get("retrieved", "")
        analysis = f"分析结果: {data} -> 提取核心概念"
        a2a.send("AgentB", "AgentC", {"analysis": analysis})
        return {"agentB_analysis": analysis}
    return {"agentB_analysis": "未收到消息"}

# 节点3：AgentC生成结论并返回（原样保留）
def agent_c_node(state: State) -> State:
    inbox = a2a.receive("AgentC")
    if inbox:
        analysis = inbox[-1]["content"].get("analysis", "")
        conclusion = f"最终结论基于:{analysis}"
        return {"agentC_conclusion": conclusion}
    return {"agentC_conclusion": "未生成结论"}

# 构建任务图（原样保留）
builder = StateGraph(State)
builder.add_node("agentA", agent_a_node)
builder.add_node("agentB", agent_b_node)
builder.add_node("agentC", agent_c_node)

builder.set_entry_point("agentA")
builder.add_edge("agentA", "agentB")
builder.add_edge("agentB", "agentC")
builder.add_edge("agentC", END)

graph = builder.compile()

# 执行任务流（原样保留）
result = graph.invoke({"query": "LangGraph"})
print(result)

# 补充验证：第二次 invoke（教材未含，用于实证"消息日志跨 invoke 累积"）
# 08 篇的 context_store 是字典——同名 key 被覆盖；本篇的 messages 是列表——append 累积。
# 第二次 invoke 后 messages 有 4 条（两次运行各 2 条）——通信记录全部留痕。
result2 = graph.invoke({"query": "Agent"})
print(result2)

# 输出所有通信消息（原样保留）
print(json.dumps(a2a.messages, ensure_ascii=False, indent=2))


# 实测输出（timestamp 为实时值，每次运行不同）：
# 第一次 invoke：
# {'agentA_result': 'LangGraph是一种任务图编排框架',
#  'agentB_analysis': '分析结果: LangGraph是一种任务图编排框架 -> 提取核心概念',
#  'agentC_conclusion': '最终结论基于:分析结果: LangGraph是一种任务图编排框架 -> 提取核心概念'}
# 第二次 invoke：
# {'agentA_result': 'Agent系统依赖通信协议',
#  'agentB_analysis': '分析结果: Agent系统依赖通信协议 -> 提取核心概念',
#  'agentC_conclusion': '最终结论基于:分析结果: Agent系统依赖通信协议 -> 提取核心概念'}
# messages（两次 invoke 后共 4 条，累积留痕）：
# [
#   {"sender": "AgentA", "receiver": "AgentB", "timestamp": ..., "content": {"retrieved": "LangGraph是一种任务图编排框架"}},
#   {"sender": "AgentB", "receiver": "AgentC", "timestamp": ..., "content": {"analysis": "分析结果: ... -> 提取核心概念"}},
#   {"sender": "AgentA", "receiver": "AgentB", "timestamp": ..., "content": {"retrieved": "Agent系统依赖通信协议"}},
#   {"sender": "AgentB", "receiver": "AgentC", "timestamp": ..., "content": {"analysis": "分析结果: Agent系统依赖通信协议 -> 提取核心概念"}}
# ]
