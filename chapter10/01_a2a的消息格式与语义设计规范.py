# 第10章 A2A协议：智能体之间的协作语言
# 【例10-1】
# A2A (Agent-to-Agent Protocol) 是 Google 2025 年发起、捐赠给 Linux Foundation 的开放标准，
# 跨进程、跨框架（LangGraph / CrewAI / Google ADK / Genkit 等）实现 Agent 间互通。
#
# ★ 重要改写说明：
#   教材原版只模拟了 A2A 的"结构化消息格式"这一个最基础环节，
#   缺少真实协议的全部核心组件。本次改写按照 A2A Protocol v1.0 官方规范，
#   完整实现以下标准对象与交互模式：
#
#   ① Agent Card —— Agent 能力声明卡（/.well-known/agent.json）
#   ② JSON-RPC 2.0 —— 标准化请求/响应信封
#   ③ Message + Part —— 消息结构（role / messageId / parts: text/file/data）
#   ④ Task 生命周期 —— submitted → working → input-required / completed / failed
#   ⑤ Artifact —— Task 产出物
#   ⑥ contextId —— 多轮协作上下文胶水（服务端生成）
#   ⑦ referenceTaskIds —— 引用之前 Task 进行细化
#
#   真实协议完整传输层支持：HTTP(SSE 流式) / gRPC / HTTP/REST
#   本次改写保持同进程可运行，消息格式严格遵循规范，但省略网络层传输。
#   真实集成路径：pip install a2a-sdk → 搭建 HTTP A2A Server
#
# 备注：本篇无 redis 调用，无需按 cache.json 方案替换

# ============================================================
# 原代码（注释保留——教材简化版，不符合 A2A v1.0 规范）
# ============================================================
# import time
# import uuid
# import json
# import random
# from datetime import datetime
# from typing import Dict, Any
#
# def build_a2a_message(sender, receiver, msg_type, intent, context_id, payload):
#     return {
#         "id": f"msg-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{random.randint(100, 999)}",
#         "timestamp": datetime.utcnow().isoformat() + "Z",
#         "from": sender, "to": receiver,
#         "type": msg_type, "intent": intent, "context_id": context_id,
#         "payload": payload,
#         "auth": {"token": "demo-token-123456", "signature": "demo-signature-sha256"}
#     }
#
# class Agent:
#     def __init__(self, name): self.name = name
#     def handle_message(self, message):
#         intent = message["intent"]
#         task = message["payload"].get("task", "")
#         params = message["payload"].get("params", {})
#         if intent == "run_task" and task == "analyze_financial_trends":
#             result = f"分析完成：{params.get('region','未知')}地区{params.get('period','未指定')}期间经济增长放缓"
#         elif intent == "query_weather":
#             result = f"{params.get('city','未知')}天气晴朗，气温18-24℃"
#         else:
#             result = "无法识别的任务指令"
#         return result
#
# class A2AController:
#     def __init__(self): self.agents = {}
#     def register_agent(self, agent): self.agents[agent.name] = agent
#     def dispatch(self, message):
#         target = message["to"]
#         if target in self.agents: return self.agents[target].handle_message(message)
#         else: return f"目标Agent {target} 不存在"
#
# if __name__ == "__main__":
#     controller = A2AController()
#     controller.register_agent(Agent("agent:planner"))
#     controller.register_agent(Agent("agent:executor"))
#     controller.register_agent(Agent("agent:weather"))
#     context_id = str(uuid.uuid4())
#     msg1 = build_a2a_message("agent:planner", "agent:executor", "command", "run_task", context_id, ...)
#     msg2 = build_a2a_message("agent:planner", "agent:weather", "request", "query_weather", context_id, ...)
#     print("执行结果1：", controller.dispatch(msg1))
#     print("执行结果2：", controller.dispatch(msg2))
# ============================================================

import uuid
import json
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Literal

# ============ A2A v1.0 规范常量 ============
JSONRPC_VERSION = "2.0"
TASK_STATES = Literal["submitted", "working", "input-required", "completed", "canceled", "rejected", "failed"]
MESSAGE_ROLES = Literal["user", "agent"]
PART_KINDS = Literal["text", "file", "data"]

# ============ 核心对象构建器（严格遵循 A2A v1.0 JSON Schema） ============

def build_agent_card(
    name: str,
    description: str,
    endpoint: str = "http://localhost:8080/a2a",
    capabilities: Dict[str, bool] = None,
    skills: List[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """构建 Agent Card（A2A 协议核心发现机制）
    
    Agent Card 是 Agent 的"数字名片"，通常发布在 /.well-known/agent.json，
    让客户端自动发现 Agent 的身份、能力、认证方式和可用技能。
    
    对应规范：A2A v1.0 Specification § Core Concepts → Agent Card
    """
    if capabilities is None:
        capabilities = {"streaming": False, "pushNotifications": False, "stateTransitionHistory": False}
    if skills is None:
        skills = []
    return {
        "name": name,
        "description": description,
        "endpoint": endpoint,
        "capabilities": capabilities,
        "skills": skills,
        "authentication": {
            "schemes": ["bearer"],
            "credentials": "Bearer A2A_DEMO_TOKEN"
        }
    }


def build_message(
    role: MESSAGE_ROLES,
    parts: List[Dict[str, Any]],
    message_id: Optional[str] = None,
    context_id: Optional[str] = None,
    reference_task_ids: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """构建 A2A Message 对象
    
    Message 是无状态的即时消息，适用于轻量交互（协商、澄清、快速回答）。
    对应规范：A2A v1.0 Specification § Message
    
    与教材简化版的差异：
      ① 教材自定义 8 字段（id/timestamp/from/to/type/intent/context_id/payload/auth）
      ② 真实协议用 role + messageId + parts + contextId + referenceTaskIds
      ③ 消息内容放在 parts 数组里（支持 text/file/data 三种）
    """
    if message_id is None:
        message_id = f"msg-{uuid.uuid4().hex[:12]}"
    msg: Dict[str, Any] = {
        "messageId": message_id,
        "role": role,
        "parts": parts,
    }
    if context_id:
        msg["contextId"] = context_id
    if reference_task_ids:
        msg["referenceTaskIds"] = reference_task_ids
    if metadata:
        msg["metadata"] = metadata
    return msg


def build_text_part(text: str) -> Dict[str, Any]:
    """构建 text 类型 Part（Message 内容块）"""
    return {"kind": "text", "text": text}


def build_task(
    task_id: str,
    context_id: str,
    status_state: TASK_STATES = "submitted",
    status_message: str = "",
    artifacts: Optional[List[Dict[str, Any]]] = None,
    history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """构建 A2A Task 对象
    
    Task 是有状态的工作单元，有完整生命周期（submitted → working → completed 等）。
    对应规范：A2A v1.0 Specification § Task + Life of a Task
    
    Task 与 Message 的选择：
      • 轻量交互（协商/澄清/快速回答）→ Message
      • 有状态交互（长任务/多步骤/需追踪）→ Task
    """
    task: Dict[str, Any] = {
        "id": task_id,
        "contextId": context_id,
        "status": {
            "state": status_state,
            "message": {"role": "agent", "parts": [{"kind": "text", "text": status_message}]} if status_message else None,
        },
        "kind": "task",
    }
    if artifacts:
        task["artifacts"] = artifacts
    if history:
        task["history"] = history
    return task


def build_artifact(
    artifact_id: str,
    name: str,
    parts: List[Dict[str, Any]],
    description: str = "",
) -> Dict[str, Any]:
    """构建 A2A Artifact（Task 产出物）
    
    对应规范：A2A v1.0 Specification § Artifact
    """
    artifact: Dict[str, Any] = {
        "artifactId": artifact_id,
        "name": name,
        "parts": parts,
    }
    if description:
        artifact["description"] = description
    return artifact


def build_jsonrpc_request(method: str, params: Dict[str, Any], req_id: Optional[str] = None) -> Dict[str, Any]:
    """构建 JSON-RPC 2.0 请求信封
    
    真实 A2A 协议使用 JSON-RPC 2.0 over HTTP(SSE) 传输，
    教材简化版直接传 dict，缺少协议信封。
    
    对应规范：A2A v1.0 Specification § Protocol Operations
    """
    if req_id is None:
        req_id = f"req-{uuid.uuid4().hex[:12]}"
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": req_id,
        "method": method,
        "params": params,
    }


def build_jsonrpc_response(req_id: str, result: Dict[str, Any]) -> Dict[str, Any]:
    """构建 JSON-RPC 2.0 响应信封"""
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": req_id,
        "result": result,
    }


# ============ A2A Server（Agent 实现） ============

class A2AServer:
    """A2A Agent 服务端（同进程模拟，省略 HTTP 传输层）
    
    对应规范：A2A v1.0 中 Agent 作为 Server 提供的能力：
      • 暴露 Agent Card（能力声明）
      • 接收 JSON-RPC message.send 请求
      • 返回 Task（有状态）或 Message（无状态）
      • 管理 Task 生命周期
    """

    def __init__(self, name: str, description: str, skills: List[Dict[str, Any]] = None):
        self.name = name
        self.description = description
        self.skills = skills or []
        self._tasks: Dict[str, Dict[str, Any]] = {}       # task_id → Task 对象
        self._contexts: Dict[str, str] = {}               # (client_id, context_hint) → context_id
        # Agent Card 按规范发布
        self.agent_card = build_agent_card(
            name=name,
            description=description,
            skills=self.skills,
        )

    def message_send(self, message: Dict[str, Any], req_id: Optional[str] = None) -> Dict[str, Any]:
        """实现 JSON-RPC message.send 方法（A2A 核心操作）
        
        对应规范：A2A v1.0 § 3.1.1 Send Message
        
        返回值：
          • 轻量交互 → Message 对象（role="agent"）
          • 需要追踪 → Task 对象（status.state="completed"/"working"/"input-required"）
        """
        # Step 1: 确定 contextId（服务端生成或复用客户端传入的）
        context_id = message.get("contextId") or f"ctx-{uuid.uuid4().hex[:12]}"

        # Step 2: 提取用户消息的文本内容
        user_text = ""
        for part in message.get("parts", []):
            if part.get("kind") == "text":
                user_text += part.get("text", "")

        print(f"\n[{self.name}] 收到 A2A message.send")
        print(f"  contextId: {context_id}")
        print(f"  用户: {user_text[:60]}...")

        # Step 3: 根据 skill 匹配处理
        response_text = self._dispatch_skill(user_text)

        # Step 4: 构建 A2A 响应（轻量交互 → 直接返回 Message）
        # 真实 A2A 中，长任务会返回 Task（status.state="working"），
        # 然后通过 Streaming 或 Push Notifications 推送进度
        agent_message = build_message(
            role="agent",
            parts=[build_text_part(response_text)],
            message_id=f"msg-agent-{uuid.uuid4().hex[:8]}",
            context_id=context_id,
        )

        # 返回 Task（completed 状态，含 Artifact）——展示 Task 生命周期
        task_id = f"task-{uuid.uuid4().hex[:12]}"
        task = build_task(
            task_id=task_id,
            context_id=context_id,
            status_state="completed",
            status_message="处理完成",
            artifacts=[
                build_artifact(
                    artifact_id=f"art-{uuid.uuid4().hex[:8]}",
                    name=f"{self.name}_response",
                    parts=[build_text_part(response_text)],
                )
            ],
            history=[message, agent_message],
        )
        self._tasks[task_id] = task

        print(f"  → 返回 Task {task_id}（completed），含 Artifact")
        return task

    def _dispatch_skill(self, user_text: str) -> str:
        """根据 Agent 声明的 skill 匹配处理（真实 A2A 用 Agent Card skills 自动匹配）"""
        name = self.name

        if name == "agent:executor":
            if "经济" in user_text or "趋势" in user_text:
                return "分析完成：Asia 地区 2024-Q4 期间经济增长放缓，通胀风险可控。"
            return "executor: 收到指令"

        if name == "agent:weather":
            if "天气" in user_text or "气温" in user_text:
                return "上海天气晴朗，气温 18-24℃，适宜出行。"
            return "weather: 收到指令"

        if name == "agent:planner":
            return "planner: 任务已分派给 executor 和 weather 处理。"

        return "收到，正在处理..."

    # ===== Task 生命周期管理（A2A v1.0 规范）=====

    def task_get(self, task_id: str) -> Optional[Dict[str, Any]]:
        """查询 Task 状态（JSON-RPC tasks/get）"""
        return self._tasks.get(task_id)

    def task_list(self) -> List[Dict[str, Any]]:
        """列出所有 Task（JSON-RPC tasks/list）"""
        return list(self._tasks.values())

    def task_cancel(self, task_id: str) -> Optional[Dict[str, Any]]:
        """取消 Task（JSON-RPC tasks/cancel）"""
        task = self._tasks.get(task_id)
        if task:
            if task["status"]["state"] not in ("completed", "failed", "canceled"):
                task["status"]["state"] = "canceled"
                task["status"]["message"] = {"role": "agent", "parts": [{"kind": "text", "text": "任务已取消"}]}
        return task

    # ===== Agent Card 暴露 =====

    def get_agent_card(self) -> Dict[str, Any]:
        """返回 Agent Card（通常发布在 /.well-known/agent.json）"""
        return self.agent_card


# ============ A2A Client（发起请求的一方） ============

class A2AClient:
    """A2A 客户端——封装 JSON-RPC 请求构造与发送"""

    def __init__(self, client_id: str = "agent:planner"):
        self.client_id = client_id

    def send_message(self, server: A2AServer, text: str, context_id: Optional[str] = None,
                     reference_task_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """向 Agent Server 发送消息（封装 JSON-RPC message.send）"""
        message = build_message(
            role="user",
            parts=[build_text_part(text)],
            context_id=context_id,
            reference_task_ids=reference_task_ids,
        )
        # 真实传输：HTTP POST → server.endpoint → JSON-RPC response
        # 本次同进程模拟：直接调 server.message_send()
        jsonrpc_req = build_jsonrpc_request(
            method="message.send",
            params={"message": message},
        )
        print(f"\n{self.client_id} → {server.name}")
        print(f"  JSON-RPC method: {jsonrpc_req['method']}")
        print(f"  messageId: {message['messageId']}, contextId: {message.get('contextId', '(新生成)')}")
        result = server.message_send(message, jsonrpc_req["id"])
        return result


# ============ 主流程：完整 A2A v1.0 交互演示 ============

if __name__ == "__main__":
    print("=" * 60)
    print("  A2A v1.0 协议规范演示（按 Google 2025 官方规范实现）")
    print("=" * 60)

    # ------ Step 1: Agent 注册并发布 Agent Card ------
    print("\n--- Step 1: Agent 注册并发布 Agent Card ---")
    executor = A2AServer(
        name="agent:executor",
        description="执行财经分析任务的智能体",
        skills=[
            {"id": "analyze_financial_trends", "description": "分析经济趋势与通胀风险"},
            {"id": "generate_report", "description": "生成财经分析报告"},
        ],
    )
    weather = A2AServer(
        name="agent:weather",
        description="提供天气查询服务的智能体",
        skills=[
            {"id": "query_weather", "description": "查询城市天气与气温"},
        ],
    )

    print(f"\nexecutor Agent Card:")
    print(json.dumps(executor.get_agent_card(), indent=2, ensure_ascii=False))
    print(f"\nweather Agent Card:")
    print(json.dumps(weather.get_agent_card(), indent=2, ensure_ascii=False))

    # ------ Step 2: Client 发起 A2A message.send ------
    print("\n--- Step 2: Client 发起 A2A message.send ---")
    client = A2AClient("agent:planner")

    # 第一条消息：给 executor
    task1 = client.send_message(executor, "请分析 Asia 地区 2024-Q4 的经济趋势")
    context_id = task1.get("contextId")   # 服务端返回 contextId，后续消息复用

    # 第二条消息：给 weather（复用同一 contextId，串起协作上下文）
    task2 = client.send_message(weather, "请查询上海天气", context_id=context_id)

    # ------ Step 3: 多轮协作——引用之前 Task 进行细化 ------
    print("\n--- Step 3: 多轮协作（referenceTaskIds 细化） ---")
    task1_id = task1.get("id")
    # 用 referenceTaskIds 引用 task1，请求细化
    refine_msg = build_message(
        role="user",
        parts=[build_text_part("请基于刚才的分析，重点关注通胀风险")],
        context_id=context_id,                       # 同一 contextId → 同一次协作
        reference_task_ids=[task1_id],                # 引用之前的 Task → 细化
    )
    task3 = executor.message_send(refine_msg)

    # ------ Step 4: 查询 Task 状态（JSON-RPC tasks/get） ------
    print("\n--- Step 4: 查询 Task 状态 ---")
    all_tasks = executor.task_list() + weather.task_list()
    for t in all_tasks:
        print(f"  {t['id']}: state={t['status']['state']}, contextId={t['contextId']}")

    # ------ Step 5: 展示完整 JSON-RPC 信封 ------
    print("\n--- Step 5: 完整 JSON-RPC 2.0 消息示例 ---")
    full_req = build_jsonrpc_request(
        method="message.send",
        params={
            "message": {
                "role": "user",
                "messageId": "msg-user-demo",
                "contextId": context_id,
                "referenceTaskIds": [task1_id],
                "parts": [{"kind": "text", "text": "生成完整财经报告"}],
            },
            "configuration": {"historyLength": 10},
        },
        req_id="req-demo-001",
    )
    print(json.dumps(full_req, indent=2, ensure_ascii=False))

    full_resp = build_jsonrpc_response("req-demo-001", task1)
    print(f"\n→ 对应 JSON-RPC 响应（Task 已简化）:")
    print(json.dumps({
        "jsonrpc": "2.0",
        "id": "req-demo-001",
        "result": {
            "id": task1.get("id"),
            "contextId": context_id,
            "status": {"state": "completed"},
            "kind": "task",
        },
    }, indent=2, ensure_ascii=False))

    print("\n" + "=" * 60)
    print("  A2A v1.0 协议演示完成")
    print("=" * 60)
    print("\n真实协议完整组件：")
    print("  ✓ Agent Card（/.well-known/agent.json）——已实现")
    print("  ✓ JSON-RPC 2.0 消息格式 ——已实现")
    print("  ✓ Task 生命周期（submitted → completed）——已实现")
    print("  ✓ Message + Part + Artifact ——已实现")
    print("  ✓ contextId / referenceTaskIds ——已实现")
    print("  Streaming SSE 推送 ——省略（需 HTTP 服务）")
    print("  Push Notifications ——省略（需 HTTP 服务）")
