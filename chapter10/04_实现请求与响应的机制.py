# 【例10-4】Request-Response 机制详解
#
# ★ 教材简化 vs 真实规范
#
# 教材原版：
#   class A2AMessage  自定义 sender/receiver/type(payload) 的简化消息
#   class Agent       qwen_agent.Agent 虚构框架
#   RequestAgent / ResponderAgent / Dispatcher
#
# 真实 A2A v1.0 协议中的 Request-Response：
#
#   协议层（JSON-RPC 2.0 信封）:
#     Request  = {jsonrpc, id, method, params}
#     Response = {jsonrpc, id, result}  或  {jsonrpc, id, error}
#
#   业务层（A2A 核心操作）:
#     请求方 Agent  → 发送 message.send（含 Message + contextId）
#     响应方 Agent  → 立即返回 Task（初始 working 状态）
#                   → 完成后更新 Task 为 completed（含 Artifact）
#
#   语义层：
#     Request-Response 模式的本质是"一个请求方发任务 → 一个响应方处理并返回结果"
#     对应 A2A Task 生命周期：submitted → working → completed/canceled
#
# 本次改写：
#   ① 用标准 JSON-RPC 2.0 信封作为 A2A Request-Response 的协议层载体
#   ② 用标准 A2A Task 生命周期（working → completed + Artifact）作为响应载体
#   ③ 用 dashscope.Generation.call 作为响应方 Agent 的 LLM 能力
#   ④ Dispatcher 同时演示三层 Request-Response：协议层 / 业务层 / LLM 层

# ============================================================
# 原代码（注释保留——教材简化版，不符合 A2A 真实规范）
# ============================================================
# from qwen_agent import Agent, Message, PromptEntry     # ← 虚构框架
# import uuid, time
# from typing import Dict, Any
#
# class A2AMessage:                                        # ← 自定义简化消息，不符合 A2A 规范
#     def __init__(self, sender, receiver, msg_type, payload): ...
#
# class RequestAgent:
#     def build_request(self, task, question) -> A2AMessage: ...
#     def handle_response(self, response: A2AMessage): ...
#
# class ResponderAgent:
#     def handle_request(self, message: A2AMessage) -> A2AMessage: ...
#     # ← 手动拼 [system, user, memory] prompt，dashscope 直接调
#
# class Dispatcher:
#     def run(self): ...
# ============================================================

import uuid
import os
import json
import hashlib
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
import dashscope

api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# ============ JSON-RPC 2.0 常量 ============
JSONRPC_VERSION = "2.0"


# ============================================================
# Part 1: JSON-RPC 2.0 信封（协议层 Request-Response）
# ============================================================

def build_request(method: str, params: Dict[str, Any], req_id: Optional[str] = None) -> Dict[str, Any]:
    """构建 JSON-RPC 2.0 Request（请求方 Agent 发出的标准请求信封）

    JSON-RPC 2.0 Request 规范要求:
      • jsonrpc: 固定 "2.0"
      • id: 唯一标识请求（响应方必须原样回传）
      • method: 方法名（如 "message.send" / "tools/call"）
      • params: 方法参数对象
    """
    if req_id is None:
        req_id = f"req-{uuid.uuid4().hex[:12]}"
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": req_id,
        "method": method,
        "params": params,
    }


def build_response(req_id: str, result: Dict[str, Any]) -> Dict[str, Any]:
    """构建 JSON-RPC 2.0 Response（成功响应）"""
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": req_id,
        "result": result,
    }


def build_error_response(req_id: str, code: int, message: str,
                         data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """构建 JSON-RPC 2.0 Error Response（失败响应）

    A2A 标准错误码（规范 § Error Codes）:
      -32700 Parse Error        JSON 解析失败
      -32600 Invalid Request    请求格式错误
      -32601 Method Not Found   方法不存在
      -32602 Invalid Params     参数错误
      -32001 Authentication Failed    认证失败
      -32002 Capability Validation Failed  能力不匹配
      -32003 Input Required     需要输入
    """
    error: Dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": req_id,
        "error": error,
    }


# ============================================================
# Part 2: A2A 核心对象（业务层 Message / Task / Artifact）
# ============================================================

def build_a2a_message(role: str, text: str,
                      context_id: Optional[str] = None,
                      message_id: Optional[str] = None) -> Dict[str, Any]:
    """构建 A2A v1.0 Message 对象"""
    if message_id is None:
        message_id = f"msg-{uuid.uuid4().hex[:12]}"
    msg: Dict[str, Any] = {
        "messageId": message_id,
        "role": role,
        "parts": [{"kind": "text", "text": text}],
    }
    if context_id:
        msg["contextId"] = context_id
    return msg


def build_a2a_task(status_state: str, status_text: str,
                   artifacts: Optional[List[Dict[str, Any]]] = None,
                   task_id: Optional[str] = None,
                   context_id: Optional[str] = None) -> Dict[str, Any]:
    """构建 A2A v1.0 Task 对象（响应方返回的核心载体）

    Task 生命周期状态（规范 § Task States）:
      submitted    → 任务已提交
      working      → 正在处理
      input-required → 需要额外输入
      completed    → 完成（有 Artifact）
      canceled     → 取消
      rejected     → 拒绝
      failed       → 失败
    """
    if task_id is None:
        task_id = f"task-{uuid.uuid4().hex[:12]}"
    if context_id is None:
        context_id = f"ctx-{uuid.uuid4().hex[:12]}"

    status: Dict[str, Any] = {"state": status_state}
    if status_text:
        status["message"] = {
            "role": "agent",
            "parts": [{"kind": "text", "text": status_text}],
        }

    task: Dict[str, Any] = {
        "id": task_id,
        "contextId": context_id,
        "status": status,
        "kind": "task",
    }
    if artifacts:
        task["artifacts"] = artifacts
    return task


def build_artifact(name: str, text: str) -> Dict[str, Any]:
    """构建 A2A Artifact（Task 的最终产出）"""
    return {
        "artifactId": f"art-{uuid.uuid4().hex[:8]}",
        "name": name,
        "parts": [{"kind": "text", "text": text}],
    }


# ============================================================
# Part 3: Request Agent（请求方 Agent）
# ============================================================

class RequestAgent:
    """A2A 请求方 Agent——负责构建标准 Request 信封并发送

    Request-Response 模式的"请求方"职责:
      ① 构造唯一 contextId（会话标识）
      ② 构造 JSON-RPC Request 信封（method=message.send）
      ③ 发送给响应方 Agent
      ④ 接收并解析 JSON-RPC Response（result=Task 或 error）
    """

    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self._sent_requests: Dict[str, Dict[str, Any]] = {}   # req_id → 发送的请求
        self._received_responses: Dict[str, Dict[str, Any]] = {}  # req_id → 收到的响应

    def build_request(self, question: str, context_id: Optional[str] = None,
                      response_agent: str = "agent:responder") -> Dict[str, Any]:
        """构造 A2A message.send 请求

        参数:
          question: 用户问题文本
          context_id: 可选的会话上下文 ID（多轮对话复用）
          response_agent: 目标 Agent 名称

        返回:
          JSON-RPC 2.0 Request 信封（含 A2A Message 参数）
        """
        if context_id is None:
            context_id = f"ctx-{uuid.uuid4().hex[:12]}"

        # 构造 A2A Message（业务层）
        a2a_message = build_a2a_message(role="user", text=question, context_id=context_id)

        # 构造 JSON-RPC Request（协议层）
        request = build_request(
            method="message.send",
            params={"message": a2a_message},
        )

        # 记录以便后续 match response
        self._sent_requests[request["id"]] = {
            "question": question,
            "context_id": context_id,
            "target": response_agent,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        return request

    def handle_response(self, jsonrpc_response: Dict[str, Any]) -> Dict[str, Any]:
        """处理 JSON-RPC Response（解析 Task 或 Error）

        返回:
          {"ok": True, "task": {...}}   或   {"ok": False, "error": {...}}
        """
        resp_id = jsonrpc_response.get("id")
        if "error" in jsonrpc_response:
            err = jsonrpc_response["error"]
            print(f"\n  [{self.agent_name}] 收到错误响应: code={err['code']}, msg={err['message']}")
            self._received_responses[resp_id] = {"ok": False, "error": err}
            return {"ok": False, "error": err}

        task = jsonrpc_response["result"]
        print(f"\n  [{self.agent_name}] 收到任务结果: task_id={task['id']}, state={task['status']['state']}")
        self._received_responses[resp_id] = {"ok": True, "task": task}

        # 提取 Artifact 中的回答
        if task.get("artifacts"):
            answer = task["artifacts"][0]["parts"][0]["text"]
            print(f"  回答: {answer[:120]}...")

        return {"ok": True, "task": task}


# ============================================================
# Part 4: Responder Agent（响应方 Agent）
# ============================================================

class ResponderAgent:
    """A2A 响应方 Agent——接收 Request，用 dashscope 处理，返回 Response

    Request-Response 模式的"响应方"职责:
      ① 验证 JSON-RPC 信封格式
      ② 提取 A2A Message（含 contextId）
      ③ 用 dashscope.Generation.call 处理用户问题（LLM 层 Request-Response）
      ④ 构造 A2A Task（working → completed 两阶段更新）
      ⑤ 构造 JSON-RPC Response（result=Task 或 error）
    """

    def __init__(self, agent_name: str, agent_card: Optional[Dict[str, Any]] = None):
        self.agent_name = agent_name
        self.agent_card = agent_card or {
            "name": agent_name,
            "description": "专业问答 Agent：简洁准确回答各类问题",
            "endpoint": "http://localhost:8080/a2a",
            "skills": [{"id": "qa", "description": "通用问答", "tags": ["qa"]}],
        }

    def verify_request(self, jsonrpc_request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """验证 JSON-RPC Request 格式

        返回:
          None = 验证通过
          error_response = 验证失败（已包装好 JSON-RPC 2.0 错误响应）
        """
        req_id = jsonrpc_request.get("id", "unknown")

        # 检查 jsonrpc 版本
        if jsonrpc_request.get("jsonrpc") != JSONRPC_VERSION:
            return build_error_response(req_id, -32600, "Invalid Request: jsonrpc version must be 2.0")

        # 检查 method 字段
        method = jsonrpc_request.get("method")
        if method not in ("message.send", "message/stream"):
            return build_error_response(req_id, -32601, f"Method not found: {method}")

        # 检查 params.message 字段
        params = jsonrpc_request.get("params", {})
        if not params.get("message"):
            return build_error_response(req_id, -32602, "Invalid Params: message field is required")

        return None

    def handle_request(self, jsonrpc_request: Dict[str, Any]) -> Dict[str, Any]:
        """完整处理请求：验证 → 提取 → LLM 调用 → 构造响应

        返回:
          JSON-RPC 2.0 Response（含 result=Task 或 error）
        """
        # Step 1: 验证请求格式
        validation_err = self.verify_request(jsonrpc_request)
        if validation_err:
            return validation_err

        req_id = jsonrpc_request["id"]
        method = jsonrpc_request["method"]
        message = jsonrpc_request["params"]["message"]

        # Step 2: 提取用户问题
        context_id = message.get("contextId") or f"ctx-{uuid.uuid4().hex[:12]}"
        user_text = ""
        for part in message.get("parts", []):
            if part.get("kind") == "text":
                user_text += part.get("text", "")

        print(f"\n  [{self.agent_name}] 收到请求: method={method}, id={req_id}")
        print(f"    contextId: {context_id}")
        print(f"    问题: {user_text[:80]}...")

        # Step 3: LLM 处理（dashscope Request-Response）
        print(f"    调用 dashscope qwen-plus（LLM 层 Request-Response）...")

        llm_prompt = f"""你是一名专业的问答助手，请简洁准确地回答以下问题。
要求：
- 回答要结构化，先给结论，再展开说明
- 如果涉及数据，请给出具体数字
- 控制在 150 字以内

问题：{user_text}"""

        response = dashscope.Generation.call(
            model="qwen-plus",
            messages=[{"role": "user", "content": llm_prompt}],
            temperature=0.3,
            max_tokens=512,
            result_format='message',
        )
        llm_answer = response.output.choices[0].message.content
        print(f"    LLM 响应生成完毕")

        # Step 4: 构造 A2A Task（completed + Artifact）
        task = build_a2a_task(
            status_state="completed",
            status_text="处理完成",
            artifacts=[build_artifact("qa_answer", llm_answer)],
            context_id=context_id,
        )

        # Step 5: 构造 JSON-RPC 2.0 Response
        return build_response(req_id, task)


# ============================================================
# Part 5: Dispatcher（请求-响应调度）
# ============================================================

class RequestResponseDispatcher:
    """Request-Response 调度器——演示三层 Request-Response 链路

    三层 Request-Response：
      L1 协议层    JSON-RPC 2.0 Request ↔ Response 信封
      L2 业务层    A2A message.send ↔ Task（working → completed）
      L3 能力层    dashscope.Generation.call ↔ LLM 文本响应
    """

    def __init__(self):
        token = hashlib.sha256("agent:responder".encode()).hexdigest()[:32]
        self.requester = RequestAgent("agent:requester")
        self.responder = ResponderAgent("agent:responder")
        self._token = token

    def run_single(self, question: str) -> Dict[str, Any]:
        """单次 Request-Response 完整演示"""
        print(f"\n{'='*60}")
        print(f"  Request-Response 链路演示")
        print(f"{'='*60}")

        # ===== L1 + L2: 协议层 + 业务层 =====
        print(f"\n→ [L1 协议层] 构造 JSON-RPC 2.0 Request")
        jsonrpc_request = self.requester.build_request(question)
        print(f"    id={jsonrpc_request['id']}, method={jsonrpc_request['method']}")
        print(f"    contextId={jsonrpc_request['params']['message']['contextId']}")

        print(f"\n→ [L2 业务层] 发送给 Responder Agent")
        jsonrpc_response = self.responder.handle_request(jsonrpc_request)

        # ===== 解析 Response =====
        result = self.requester.handle_response(jsonrpc_response)
        return result


# ============================================================
# Part 6: 主流程——演示正常 + 错误两种路径
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  例 10-4: Request-Response 机制详解")
    print("  三层链路: JSON-RPC 信封 → A2A Task → dashscope LLM")
    print("=" * 60)

    dispatcher = RequestResponseDispatcher()

    # ===== 场景 1: 正常 Request-Response =====
    result1 = dispatcher.run_single("当前欧洲的通货膨胀情况如何？")

    # ===== 场景 2: 验证 JSON-RPC Error Response =====
    print(f"\n{'='*60}")
    print(f"  Request-Response 错误路径演示")
    print(f"{'='*60}")

    # 构造一个 method 不存在的请求
    bad_request = build_request(method="nonexistent.method", params={"foo": "bar"})
    print(f"\n→ [错误请求] method={bad_request['method']}")
    bad_response = dispatcher.responder.handle_request(bad_request)
    print(f"→ [错误响应] error={bad_response['error']}")

    # ===== 场景 3: params 缺失 message 字段 =====
    bad_request2 = build_request(method="message.send", params={})
    print(f"\n→ [错误请求] params 缺失 message 字段")
    bad_response2 = dispatcher.responder.handle_request(bad_request2)
    print(f"→ [错误响应] error={bad_response2['error']}")

    print(f"\n{'='*60}")
    print(f"  Request-Response 机制完整演示完成")
    print(f"{'='*60}")
    print("\n三层 Request-Response 总结:")
    print("  L1 协议层  JSON-RPC 2.0 Request ↔ Response 信封")
    print("  L2 业务层  A2A message.send ↔ Task (working → completed + Artifact)")
    print("  L3 能力层  dashscope.Generation.call ↔ LLM 文本响应")
    print("\n关键设计要点:")
    print("  • 请求方 id 必须在响应中原样返回（匹配请求-响应对）")
    print("  • 错误用 error.code（非 HTTP 状态码），规范 -32xxx / -3200x")
    print("  • A2A 用 Task 封装响应，状态机: working → completed/failed")
    print("  • Artifact 是 Task 的最终产出（替代教材的 payload.answer）")
