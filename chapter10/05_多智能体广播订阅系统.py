# 【例10-5】多智能体广播订阅系统
#
# ★ 教材简化 vs 真实 A2A 规范
#
# 教材原版：
#   class PubSubMessage(topic, content)                    # 自定义消息
#   class SubscriberAgent(topic_filter, Agent.on_message)   # qwen_agent 虚构框架
#   class PubSubSystem(register, publish)                  # 简单 topic 订阅
#
# 真实 A2A v1.0 协议中的 Pub/Sub（发布-订阅）机制：
#
#   ① 协议层 — JSON-RPC 2.0 Notification（单向广播）
#      Notification = {jsonrpc, method, params}   ← 没有 id，不需要响应！
#      这是所有"广播"的协议层载体。
#      对比 Request：{jsonrpc, id, method, params} ← 有 id，期望 Response
#
#   ② 业务层 — A2A subscribeToTask + SSE 流式订阅
#      subscribeToTask(taskId) → 订阅某个 Task 的全部状态变化
#      Server 通过 SSE（Server-Sent Events）推送 TaskStatusUpdateEvent:
#        submitted → working → input-required → completed/failed
#
#   ③ 断连恢复 — Push Notifications
#      SSE 断连后，Server 通过 Webhook 主动推送最新 Task 状态
#
#   教材的 topic 订阅 对应 A2A 的 taskId 订阅：
#     教材：subscribe("财经快讯") → 收到所有"财经"主题消息
#     A2A：subscribeToTask("task-abc") → 收到该 Task 的所有状态变化
#
# 本次改写：
#   ① 用 JSON-RPC 2.0 Notification 替代自定义 PubSubMessage（协议层）
#   ② 用 A2A subscribeToTask + SSE 事件对象替代 topic 订阅（业务层）
#   ③ 用 dashscope.Generation.call 替代虚构 qwen_agent（LLM 层）
#   ④ 同时演示 Request/Response（例 10-4）和 Notification（本篇）的协议层区别
#
# 备注：本篇无 redis 调用，无需按 cache.json 方案替换

# ============================================================
# 原代码（注释保留——教材简化版，不符合 A2A 真实规范）
# ============================================================
# from qwen_agent import Agent, Message, PromptEntry       # ← 虚构框架
# import uuid, time
# from typing import Dict, List, Callable
#
# class PubSubMessage(topic, content):                    # ← 自定义简化消息
#     def to_dict(self): ...
#
# class SubscriberAgent(name, topic_filter):              # ← qwen_agent 虚构框架
#     def on_message(self, message: PubSubMessage): ...
#
# class PubSubSystem:
#     def register(self, agent: SubscriberAgent): ...     # ← 简单 topic 订阅
#     def publish(self, message: PubSubMessage): ...
# ============================================================

import uuid
import os
import json
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Callable
import dashscope

api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# ============ JSON-RPC 2.0 常量 ============
JSONRPC_VERSION = "2.0"


# ============================================================
# Part 1: JSON-RPC 2.0 Notification（广播载体——区别于 Request）
# ============================================================

def build_request(method: str, params: Dict[str, Any], req_id: Optional[str] = None) -> Dict[str, Any]:
    """构建 JSON-RPC 2.0 Request（有 id，期望 Response）

    Request vs Notification 关键区别：
      Request:     {jsonrpc, id, method, params}   ← 有 id
      Notification:{jsonrpc, method, params}       ← 没有 id！不需要响应！
    """
    if req_id is None:
        req_id = f"req-{uuid.uuid4().hex[:12]}"
    return {"jsonrpc": JSONRPC_VERSION, "id": req_id, "method": method, "params": params}


def build_notification(method: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """构建 JSON-RPC 2.0 Notification（无 id，单向广播，不需要响应）

    JSON-RPC 2.0 规范明确定义：Notification 是一种 Request，但没有 id，
    因此接收方 MUST NOT 发送 Response。这就是"广播"的协议层语义。
    """
    return {"jsonrpc": JSONRPC_VERSION, "method": method, "params": params}


# ============================================================
# Part 2: A2A Pub/Sub 核心对象
# ============================================================

# Task 状态变化事件类型（A2A 规范 § Task Status Update）
class TaskEventType:
    SUBMITTED = "task.submitted"       # 任务已提交
    WORKING = "task.working"           # 正在处理
    INPUT_REQUIRED = "task.input_required"  # 需要输入
    COMPLETED = "task.completed"       # 完成
    FAILED = "task.failed"             # 失败
    CANCELED = "task.canceled"         # 取消


def build_task_status_event(task_id: str, status_state: str,
                            message_text: Optional[str] = None,
                            artifacts: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """构建 A2A TaskStatusUpdateEvent（SSE 流中推送的事件）

    这是 A2A SSE 流式订阅中最核心的事件类型，每次 Task 状态变化都推送。
    """
    event: Dict[str, Any] = {
        "taskId": task_id,
        "state": status_state,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if message_text:
        event["message"] = {"role": "agent", "parts": [{"kind": "text", "text": message_text}]}
    if artifacts:
        event["artifacts"] = artifacts
    return event


# ============================================================
# Part 3: A2ASubscriptionManager（订阅管理器——维护 taskId → subscribers）
# ============================================================

class A2ASubscriptionManager:
    """A2A 订阅管理器——维护"谁订阅了哪个 Task"的注册表

    A2A subscribeToTask 方法的核心服务端逻辑：
      subscribe(task_id, subscriber) → 加入注册表
      broadcast(task_id, notification) → 向该 Task 的所有订阅者广播 Notification
      unsubscribe(task_id, subscriber) → 移除注册表
    """

    def __init__(self):
        # task_id → List[SubscriberAgent]
        self._subscriptions: Dict[str, List["SubscriberAgent"]] = {}

    def subscribe(self, task_id: str, subscriber: "SubscriberAgent"):
        """订阅某个 Task 的状态变化（对应 A2A subscribeToTask RPC 方法）"""
        if task_id not in self._subscriptions:
            self._subscriptions[task_id] = []
        if subscriber not in self._subscriptions[task_id]:
            self._subscriptions[task_id].append(subscriber)
        print(f"  [订阅] {subscriber.name} → {task_id}")

    def unsubscribe(self, task_id: str, subscriber: "SubscriberAgent"):
        """取消订阅"""
        if task_id in self._subscriptions:
            self._subscriptions[task_id] = [
                s for s in self._subscriptions[task_id] if s != subscriber
            ]

    def get_subscribers(self, task_id: str) -> List["SubscriberAgent"]:
        """获取某个 Task 的所有订阅者"""
        return self._subscriptions.get(task_id, [])

    def broadcast(self, task_id: str, notification: Dict[str, Any]) -> List[str]:
        """向指定 taskId 的所有订阅者广播 JSON-RPC Notification

        返回每个订阅者的处理结果描述列表。
        """
        subscribers = self.get_subscribers(task_id)
        if not subscribers:
            print(f"  [广播] {task_id} → 无订阅者")
            return []

        method = notification.get("method", "unknown")
        subscribers_names = [s.name for s in subscribers]
        print(f"  [广播] {task_id} → {method}")
        print(f"  [订阅者] {', '.join(subscribers_names)}")

        results = []
        for sub in subscribers:
            try:
                result = sub.on_notification(notification)
                results.append(result)
            except Exception as e:
                results.append(f"{sub.name}: 处理异常 {e}")

        return results


# ============================================================
# Part 4: PublisherAgent（发布者 Agent——负责创建 Task + 广播状态变化）
# ============================================================

class PublisherAgent:
    """A2A 发布者 Agent——创建 Task 并广播状态变化 Notification

    Publisher 的职责：
      ① 创建一个新 Task（submitted 状态）
      ② 广播 task.submitted Notification
      ③ 处理 Task（dashscope）
      ④ 广播 task.working → task.completed（含 Artifact）Notification
    """

    def __init__(self, name: str, subscription_mgr: A2ASubscriptionManager):
        self.name = name
        self.mgr = subscription_mgr
        self._tasks: Dict[str, Dict[str, Any]] = {}

    def create_task(self, description: str) -> Dict[str, Any]:
        """创建新 Task 并广播 task.submitted Notification

        返回:
          {"task": {...}, "broadcast_results": [...]}
        """
        task_id = f"task-{uuid.uuid4().hex[:12]}"

        task = {
            "id": task_id,
            "contextId": f"ctx-{uuid.uuid4().hex[:12]}",
            "description": description,
            "status": {"state": "submitted"},
            "kind": "task",
        }
        self._tasks[task_id] = task

        # 广播 task.submitted Notification
        event = build_task_status_event(task_id, TaskEventType.SUBMITTED,
                                        message_text=f"Task 已创建: {description}")
        notification = build_notification("task.status", {"event": event})
        broadcast_results = self.mgr.broadcast(task_id, notification)

        return {"task": task, "broadcast_results": broadcast_results}

    def process_task(self, task_id: str, llm_prompt: str) -> Dict[str, Any]:
        """处理 Task 并广播 working → completed 状态变化

        完整流程（含 3 次广播）：
          submitted → working（广播一次）→ completed（广播一次，含 Artifact）
        """
        task = self._tasks.get(task_id)
        if not task:
            return {"error": f"Task {task_id} not found"}

        broadcast_results: List[str] = []

        # === 广播 task.working ===
        task["status"] = {"state": "working"}
        event_working = build_task_status_event(task_id, TaskEventType.WORKING,
                                                message_text="Publisher 正在处理...")
        notif_working = build_notification("task.status", {"event": event_working})
        broadcast_results.extend(self.mgr.broadcast(task_id, notif_working))

        # === LLM 处理 ===
        print(f"\n  [{self.name}] 调用 dashscope qwen-plus 处理 Task...")
        response = dashscope.Generation.call(
            model="qwen-plus",
            messages=[{"role": "user", "content": llm_prompt}],
            temperature=0.3,
            max_tokens=512,
            result_format='message',
        )
        llm_answer = response.output.choices[0].message.content

        # === 广播 task.completed ===
        artifact = {
            "artifactId": f"art-{uuid.uuid4().hex[:8]}",
            "name": "analysis",
            "parts": [{"kind": "text", "text": llm_answer}],
        }
        task["status"] = {"state": "completed"}
        task["artifacts"] = [artifact]

        event_completed = build_task_status_event(
            task_id, TaskEventType.COMPLETED,
            message_text="处理完成",
            artifacts=[artifact],
        )
        notif_completed = build_notification("task.status", {"event": event_completed})
        broadcast_results.extend(self.mgr.broadcast(task_id, notif_completed))

        return {"task": task, "broadcast_results": broadcast_results}

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        return self._tasks.get(task_id)


# ============================================================
# Part 5: SubscriberAgent（订阅者 Agent——接收 Notification 并处理）
# ============================================================

class SubscriberAgent:
    """A2A 订阅者 Agent——接收 JSON-RPC Notification 并处理 Task 状态变化

    Subscriber 的职责：
      ① 接收 Publisher 广播的 JSON-RPC Notification（无 id，单向）
      ② 根据 Notification 里的 TaskStatusUpdateEvent 类型做不同处理
      ③ 对 task.completed 事件，可选择调 dashscope 做二次分析
    """

    def __init__(self, name: str, analyze_on_completed: bool = True):
        self.name = name
        self.analyze_on_completed = analyze_on_completed
        self._received_events: List[Dict[str, Any]] = []

    def subscribe_to_task(self, task_id: str, subscription_mgr: A2ASubscriptionManager):
        """调用 A2A subscribeToTask RPC（业务方法订阅）"""
        subscription_mgr.subscribe(task_id, self)

    def on_notification(self, notification: Dict[str, Any]) -> str:
        """处理 JSON-RPC Notification（协议层入口）

        A2A Notification 格式:
          {"jsonrpc": "2.0", "method": "task.status", "params": {"event": {...}}}

        关键：Notification 没有 id，不需要返回任何 Response！
        """
        method = notification.get("method", "unknown")
        params = notification.get("params", {})
        event = params.get("event", {})
        task_id = event.get("taskId", "?")
        state = event.get("state", "?")

        self._received_events.append(event)

        print(f"\n  [{self.name}] 收到 Notification: method={method}")
        print(f"    taskId={task_id}, state={state}")

        # 根据事件类型做不同处理
        if state == TaskEventType.SUBMITTED:
            msg = event.get("message", {}).get("parts", [{}])[0].get("text", "")
            return f"[{self.name}] 收到新任务: {msg}"

        elif state == TaskEventType.WORKING:
            msg = event.get("message", {}).get("parts", [{}])[0].get("text", "")
            return f"[{self.name}] 状态变化: {msg}"

        elif state == TaskEventType.COMPLETED:
            # 完成事件 —— 可选做二次 LLM 分析
            artifacts = event.get("artifacts", [])
            original_text = ""
            if artifacts:
                original_text = artifacts[0].get("parts", [{}])[0].get("text", "")

            if self.analyze_on_completed and original_text:
                print(f"    [{self.name}] 开始二次分析（dashscope 调用）...")
                llm_prompt = f"""请对以下内容做一句话摘要，控制在 30 字以内：

{original_text}"""
                response = dashscope.Generation.call(
                    model="qwen-plus",
                    messages=[{"role": "user", "content": llm_prompt}],
                    temperature=0.3,
                    max_tokens=128,
                    result_format='message',
                )
                summary = response.output.choices[0].message.content
                print(f"    [{self.name}] 二次分析完成")
                return f"[{self.name}] 二次分析: {summary}"
            else:
                text_preview = original_text[:80] + ("..." if len(original_text) > 80 else "")
                return f"[{self.name}] 任务完成，内容预览: {text_preview}"

        elif state == TaskEventType.FAILED:
            return f"[{self.name}] 任务失败"

        return f"[{self.name}] 未处理状态: {state}"


# ============================================================
# Part 6: 主流程——完整 A2A Pub/Sub 演示
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  例 10-5: A2A 广播与订阅系统（Pub/Sub）")
    print("  协议层: JSON-RPC Notification（无 id, 单向）")
    print("  业务层: A2A subscribeToTask + SSE TaskStatusUpdateEvent")
    print("=" * 60)

    # ===== Step 1: 创建订阅管理器 + 发布者 + 订阅者 =====
    print("\n--- Step 1: 初始化 ---")
    mgr = A2ASubscriptionManager()
    publisher = PublisherAgent("agent:publisher", mgr)

    # 两个订阅者：一个做二次 LLM 分析，一个只接收
    sub_analyzer = SubscriberAgent("agent:analyzer", analyze_on_completed=True)
    sub_reporter = SubscriberAgent("agent:reporter", analyze_on_completed=False)
    print(f"  订阅者 1: agent:analyzer（Task 完成后做 LLM 二次分析）")
    print(f"  订阅者 2: agent:reporter（只接收状态通知）")

    # 收集所有广播结果
    all_broadcast_results: List[str] = []

    # ===== Step 2: 创建 Task（submitted 状态 + 广播 submitted Notification）=====
    print("\n--- Step 2: Publisher 创建 Task（广播 submitted）---")
    create_result = publisher.create_task("分析 2024 年中国央行降准对股市的影响")
    task = create_result["task"]
    task_id = task["id"]
    all_broadcast_results.extend(create_result["broadcast_results"])

    # ===== Step 3: 订阅者订阅 Task（subscribeToTask 业务调用）=====
    print("\n--- Step 3: 订阅者订阅 Task（subscribeToTask）---")
    sub_analyzer.subscribe_to_task(task_id, mgr)
    sub_reporter.subscribe_to_task(task_id, mgr)

    # 订阅者加入后，手动再广播一次 submitted 让新订阅者收到
    print("\n--- Step 3.5: 重新广播 submitted（新订阅者已加入）---")
    resubmit_event = build_task_status_event(task_id, TaskEventType.SUBMITTED,
                                             message_text="Task 已创建: 分析 2024 年中国央行降准对股市的影响")
    notif = build_notification("task.status", {"event": resubmit_event})
    all_broadcast_results.extend(mgr.broadcast(task_id, notif))

    # ===== Step 4: Publisher 处理 Task（broadcast working → completed）=====
    print("\n--- Step 4: Publisher 处理 Task（两次广播）---")
    llm_prompt = """你是一名财经分析专家，请分析以下事件对中国股市的影响：

事件：2024 年中国央行宣布降准 50 个基点，释放长期流动性约 1.2 万亿人民币。

要求：
- 先给一句话核心观点
- 再分 3 点展开分析
- 控制在 200 字以内"""

    proc_result = publisher.process_task(task_id, llm_prompt)
    all_broadcast_results.extend(proc_result["broadcast_results"])

    # ===== Step 5: 展示最终结果 =====
    print(f"\n{'='*60}")
    print(f"  Task 最终状态")
    print(f"{'='*60}")
    final_task = publisher.get_task(task_id)
    print(f"  task_id: {final_task['id']}")
    print(f"  contextId: {final_task['contextId']}")
    print(f"  state: {final_task['status']['state']}")
    if final_task.get("artifacts"):
        print(f"\n  --- Artifact（Publisher 生成）---")
        print(final_task["artifacts"][0]["parts"][0]["text"])

    print(f"\n{'='*60}")
    print(f"  订阅者处理结果汇总（共 {len(all_broadcast_results)} 条）")
    print(f"{'='*60}")
    for r in all_broadcast_results:
        print(f"  {r}")

    print(f"\n{'='*60}")
    print(f"  A2A Pub/Sub 机制完整演示完成")
    print(f"{'='*60}")
    print("\n关键对比（协议层）:")
    print("  Request:     {jsonrpc, id, method, params}  → 期望 Response")
    print("  Notification:{jsonrpc, method, params}      → 不需要 Response")
    print("\n完整链路:")
    print("  Publisher.create_task() → 广播 submitted Notification")
    print("  Subscriber.subscribeToTask(taskId) → 加入注册表")
    print("  Publisher.process_task() → 广播 working → completed Notification")
    print("  Subscriber.on_notification() → 按事件类型处理")
