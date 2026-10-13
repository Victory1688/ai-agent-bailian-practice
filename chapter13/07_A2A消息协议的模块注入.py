# 第13章 项目案例：从零实现一个复合智能体系统
# 【例13-7】A2A 消息协议的模块注入
#
# ★ 教材简化 vs 真实 A2A 规范（Google 2025 发布，Agent-to-Agent Protocol）
#
# 教材原版问题（已注释保留）：
#   ① 【最严重】标题叫 A2A，但与真实协议毫无关系——真实 A2A 是
#      Agent-to-Agent 跨进程开放标准：Agent Card 自描述（/.well-known/
#      agent.json，含 skills 能力声明）+ JSON-RPC 2.0 信封 + Task 任务
#      生命周期（submitted/working/completed/failed + artifacts）+ 标准错误
#      码；教材的 A2AMessage 只是自造的 sender/receiver/payload/metadata
#      四字段结构——借壳命名（同 13-06 的 MCP 借壳）
#   ② Qwen2Chat / DeepSeekChat 虚构类 + langchain.schema 过时 import
#      （同 13-01，import 即崩）
#   ③ default_handler 定义了但从未注册进 handlers —— 死代码；且 receive_message
#      对未注册 task_type 返回"[不支持的任务类型]"字符串，两者矛盾
#   ④ 无任务抽象：handler 返回裸字符串，成功/失败无法区分，任务状态不可跟踪
#   ⑤ 无能力发现：调用方必须预先硬编码 receiver 的 agent 名字——真实 A2A
#      的核心价值恰是 Agent Card 自描述 + skill 标签匹配
#   ⑥ 错误字符串混流："[ERROR] 目标Agent不存在" 与正常响应混在同一返回通道
#   ⑦ metadata 无结构约束（task_type/tool 全是魔法字符串，无 schema）
#   ⑧ 无 self-test
#
# 本次改写（按真实 A2A 规范重构，char12-02 已验证模式）：
#   ① AgentCard：A2A 自描述卡片（name/description/url/version/protocolVersion/
#      skills[id, name, description, tags]），对应规范 /.well-known/agent.json
#   ② A2AServer：JSON-RPC 2.0 单入口 handle()，message/send 创建并推进
#      Task 生命周期（working → completed/failed），artifacts 承载结果；
#      tasks/get 查询任务；标准错误码 -32601/-32602 + A2A 特有 -32001
#      TaskNotFound；传输层解耦（进程内传递，生产换 HTTP 零改动）
#   ③ 消息结构规范化：A2AMessage 内部导出规范的 role + parts 结构
#      （TextPart 承载正文，DataPart 承载 metadata——教材 task_type/tool
#      魔法字段有了标准容器）
#   ④ 能力发现：A2ARouter.find_agent(skill_tag) 按 skill 标签匹配目标
#      Agent（替代硬编码 receiver 字符串）；register_agent 模块注入语义保留
#   ⑤ dispatch 返回结构化契约 {"success", "taskId", "state", "response"}
#   ⑥ 教材 ToolAgent/AnswerAgent 的业务语义原样保留（模拟工具执行 /
#      qwen-plus 真实问答；default_handler 的 LLM 兜底语义并入 qa 技能）
#   ⑦ self-test 5 项：Agent Card 与 skill 发现 / Task 生命周期 /
#      真实 qa 生成 / 失败路径与 tasks/get / 协议错误码

# ============================================================
# 原代码（注释保留——教材简化版，借壳 A2A + 死代码 + 无能力发现）
# ============================================================
# # 【例13-7】
# # -*- coding:utf-8 -*-
# # A2A消息协议实现：Agent间模块消息传递与注入
# # 支持多智能体之间的任务传递，状态同步与协同调用，结构标准，消息透明；
# # 调度灵活，适配Qwen与DeepSeek的符合任务执行流程。
#
# import uuid
# from typing import Dict, Callable, Any
# from langchain_community.chat_models import Qwen2Chat, DeepSeekChat  # ← 虚构类
# from langchain.schema import HumanMessage, AIMessage                 # ← 过时 import
#
# # 一、A2A标准消息结构（自造结构，非真实 A2A 规范）
# class A2AMessage:
#     def __init__(self, sender: str, receiver: str, payload: str, metadata: Dict[str, Any] = None):
#         self.message_id = str(uuid.uuid4())
#         self.sender = sender
#         self.receiver = receiver
#         self.payload = payload
#         self.metadata = metadata or {}
#
#     def to_dict(self):
#         return {"id": self.message_id, "sender": self.sender, "receiver": self.receiver,
#                 "payload": self.payload, "metadata": self.metadata}
#
# # 二、定义Agent基类
# class Agent:
#     def __init__(self, name: str, model_type="qwen"):
#         self.name = name
#         self.handlers: Dict[str, Callable[[A2AMessage], str]] = {}
#         self.model = self._load_model(model_type)
#
#     def _load_model(self, model_type):
#         if model_type == "qwen":
#             return Qwen2Chat(model="Qwen/Qwen1.5-7B-Chat")       # ← 虚构
#         elif model_type == "deepseek":
#             return DeepSeekChat(model="deepseek-ai/deepseek-llm-chat")
#         else:
#             raise ValueError("未知模型类型")
#
#     def register_handler(self, task_type: str, handler: Callable[[A2AMessage], str]):
#         self.handlers[task_type] = handler
#
#     def receive_message(self, message: A2AMessage):
#         task = message.metadata.get("task_type", "default")
#         handler = self.handlers.get(task)
#         if not handler:
#             return f"[{self.name}] 不支持的任务类型：{task}"    # ← 错误混流
#         return handler(message)
#
#     def default_handler(self, message: A2AMessage):
#         # ← 死代码：从未 register_handler("default", ...)，永远不会被调用
#         prompt = f"请根据以下内容生成回应：{message.payload}"
#         return self.model([HumanMessage(content=prompt)]).content.strip()
#
# # 三、示例Agent：ToolAgent、AnswerAgent
# class ToolAgent(Agent):
#     def __init__(self):
#         super().__init__("ToolAgent", model_type="deepseek")
#         self.register_handler("tool_call", self.handle_tool)
#
#     def handle_tool(self, msg: A2AMessage):
#         tool_name = msg.metadata.get("tool", "未知工具")
#         return f"[{self.name}] 已调用工具：{tool_name}，执行内容为：{msg.payload}"
#
# class AnswerAgent(Agent):
#     def __init__(self):
#         super().__init__("AnswerAgent", model_type="qwen")
#         self.register_handler("qa", self.handle_qa)
#
#     def handle_qa(self, msg: A2AMessage):
#         prompt = f"请回答问题：{msg.payload}"
#         return self.model([HumanMessage(content=prompt)]).content.strip()
#
# # 四、A2A调度中心
# class A2ARouter:
#     def __init__(self):
#         self.agents = {}
#
#     def register_agent(self, agent: Agent):
#         self.agents[agent.name] = agent
#
#     def dispatch(self, msg: A2AMessage) -> str:
#         receiver = msg.receiver
#         if receiver not in self.agents:
#             return f"[ERROR] 目标Agent不存在：{receiver}"        # ← 错误混流
#         return self.agents[receiver].receive_message(msg)
# ============================================================

import os
import sys
import uuid
import logging
import dashscope

# ===== dashscope 统一配置（前 10 章模式）=====
dashscope.api_key = os.environ.get("DASHSCOPE_API_KEY")

# ===== 日志：控制台输出 =====
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

# ===== 常量 =====
MAX_TOKENS = 256
A2A_PROTOCOL_VERSION = "1.0"   # 真实 A2A 规范版本（Google 2025 发布）

# JSON-RPC 2.0 标准错误码（A2A 复用 JSON-RPC 错误语义）+ A2A 特有错误码
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
TASK_NOT_FOUND = -32001        # A2A 规范定义的 Task 级错误码


# ============================================================
# 组件 1：AgentCard —— A2A 自描述卡片（能力发现的数据基础）
# ============================================================

class AgentCard:
    """Agent 自描述卡片：对应真实 A2A 的 /.well-known/agent.json

    调用方不需要预先知道 Agent 内部实现，只读卡片即可发现其 skills
    ——这是 A2A 区别于教材"硬编码 receiver 字符串"的核心机制
    """

    def __init__(self, name: str, description: str, skills: list,
                 url: str = "inproc://agent", version: str = "1.0.0"):
        """构造卡片

        参数: name — Agent 名称; description — 一句话职责描述;
              skills — 技能列表 [{id, name, description, tags}];
              url — 服务地址（生产为 https URL，教学为进程内标识）; version — 卡片版本
        """
        self.name = name
        self.description = description
        self.skills = [{"id": s["id"], "name": s["name"],
                        "description": s["description"], "tags": list(s["tags"])}
                       for s in skills]
        self.url = url
        self.version = version

    def as_dict(self) -> dict:
        """导出为规范的卡片字典（生产中即 agent.json 的内容）"""
        return {"name": self.name, "description": self.description,
                "url": self.url, "version": self.version,
                "protocolVersion": A2A_PROTOCOL_VERSION, "skills": self.skills}


# ============================================================
# 组件 2：A2AMessage —— 规范化消息结构（TextPart + DataPart）
# ============================================================

class A2AMessage:
    """A2A 消息：保留教材 sender/receiver 路由语义，内部导出规范 parts 结构

    真实 A2A 中消息正文由 parts 列表承载：TextPart 放文本，
    DataPart 放结构化数据（教材的 task_type/tool 魔法字段有了标准容器）
    """

    def __init__(self, sender: str, receiver: str, payload: str, metadata: dict = None):
        """构造消息

        参数: sender — 发送方名称; receiver — 接收方名称（路由目标）;
              payload — 正文文本; metadata — 结构化元数据（task_type/tool 等）
        """
        self.message_id = str(uuid.uuid4())
        self.sender = sender
        self.receiver = receiver
        self.payload = payload
        self.metadata = metadata or {}

    def to_a2a_message(self) -> dict:
        """导出为 A2A 规范的 message 结构（role + parts，随 message/send 发送）"""
        parts = [{"kind": "text", "text": self.payload}]
        if self.metadata:
            parts.append({"kind": "data", "data": dict(self.metadata)})
        return {"role": "user", "messageId": self.message_id,
                "parts": parts, "metadata": dict(self.metadata)}

    def to_dict(self) -> dict:
        """教材方法保留：网关内部的路由视图"""
        return {"id": self.message_id, "sender": self.sender, "receiver": self.receiver,
                "payload": self.payload, "metadata": self.metadata}


# ============================================================
# 组件 3：A2AServer —— Agent 的协议外壳（JSON-RPC 2.0 + Task 生命周期）
# ============================================================

class JsonRpcError(Exception):
    """JSON-RPC 协议级错误（Task 级失败不走这里，走 status.state=failed）"""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class A2AServer:
    """A2A 服务端最小实现：Agent Card 自描述 + message/send + Task 生命周期

    每个 Agent 模块被 A2AServer 包裹后即成为标准 A2A 端点：
    对外只暴露卡片（发现）与 JSON-RPC 方法（调用），内部实现是黑盒
    ——这正是 A2A "opaque agents"（不透明协作）的设计哲学
    """

    def __init__(self, card: AgentCard, execute):
        """装配 Agent

        参数: card — 自描述卡片; execute — 技能执行函数 (payload, metadata) -> str
        """
        self.card = card
        self.execute = execute
        self._tasks: dict = {}   # TaskStore：task_id → 任务对象（状态可查询）

    def get_agent_card(self) -> dict:
        """能力发现入口（生产中经 HTTP GET /.well-known/agent.json 获取）"""
        return self.card.as_dict()

    def handle(self, request: dict):
        """JSON-RPC 2.0 单入口：请求 dict 进，响应 dict 出（通知返回 None）

        参数: request — 完整 JSON-RPC 请求
        返回: {"jsonrpc", "id", "result"} 或 {"jsonrpc", "id", "error"}
        """
        method = request.get("method", "")
        req_id = request.get("id")
        if method.startswith("notifications/"):
            return None   # 通知不产生响应
        try:
            if method == "message/send":
                result = self._message_send(request.get("params") or {})
            elif method == "tasks/get":
                result = self._tasks_get(request.get("params") or {})
            else:
                raise JsonRpcError(METHOD_NOT_FOUND, f"方法不存在：{method}")
            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        except JsonRpcError as e:
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": e.code, "message": e.message}}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": INTERNAL_ERROR, "message": str(e)}}

    def _message_send(self, params: dict) -> dict:
        """message/send：创建并推进一个 Task 至终态（completed / failed）

        Task 是 A2A 的核心抽象：任务有状态机（working → completed/failed），
        结果放 artifacts——教材"返回裸字符串、成功失败无法区分"在此修正
        """
        message = params.get("message")
        if not isinstance(message, dict) or not message.get("parts"):
            raise JsonRpcError(INVALID_PARAMS, "message.parts 不能为空")
        task_id = params.get("taskId") or message.get("taskId") or str(uuid.uuid4())
        # 提取 TextPart 正文与 DataPart 元数据（教材 metadata 语义由 DataPart 承载）
        payload = "".join(p["text"] for p in message["parts"]
                          if p.get("kind") == "text")
        metadata = dict(message.get("metadata") or {})
        for p in message["parts"]:
            if p.get("kind") == "data":
                metadata.update(p.get("data") or {})
        task = {"id": task_id, "status": {"state": "working"}, "artifacts": []}
        self._tasks[task_id] = task
        try:
            text = str(self.execute(payload, metadata))
            task["status"] = {"state": "completed"}
            task["artifacts"] = [{"name": "response",
                                  "parts": [{"kind": "text", "text": text}]}]
        except Exception as e:
            # 技能执行失败是任务级失败（业务性），不是协议错误——规范语义
            logger.warning(f"[A2A] 任务 {task_id} 执行失败: {e}")
            task["status"] = {"state": "failed", "message": str(e)}
        return task

    def _tasks_get(self, params: dict) -> dict:
        """tasks/get：按 id 查询任务状态（教材完全没有的能力）"""
        task_id = params.get("id")
        if task_id not in self._tasks:
            raise JsonRpcError(TASK_NOT_FOUND, f"任务不存在：{task_id}")
        return self._tasks[task_id]


def build_agents() -> list:
    """装配教材同款两个 Agent 模块（业务语义原样保留，协议外壳标准化）"""
    # ToolAgent：模拟工具执行（教材 handle_tool 语义，不依赖 LLM）
    def tool_execute(payload: str, metadata: dict) -> str:
        tool = metadata.get("tool", "未知工具")
        return f"[ToolAgent] 已调用工具：{tool}，执行内容为：{payload}"

    # AnswerAgent：qwen-plus 问答（教材 handle_qa + default_handler 的
    # LLM 兜底语义并入本技能——死代码问题在此修正）
    def qa_execute(payload: str, metadata: dict) -> str:
        resp = dashscope.Generation.call(
            model="qwen-plus",
            messages=[{"role": "user", "content": f"请回答问题：{payload}"}],
            max_tokens=MAX_TOKENS, result_format="message")
        if resp.status_code != 200:
            raise RuntimeError(f"{resp.code} {resp.message}")
        return resp.output.choices[0].message.content.strip()

    tool_card = AgentCard(
        name="ToolAgent", description="工具调用代理：模拟执行外部工具任务",
        skills=[{"id": "tool_call", "name": "工具调用", "description": "按名称调用并执行工具",
                 "tags": ["tool", "tool_call", "执行"]}])
    qa_card = AgentCard(
        name="AnswerAgent", description="问答代理：基于 qwen-plus 回答知识类问题",
        skills=[{"id": "qa", "name": "知识问答", "description": "回答知识类问题",
                 "tags": ["qa", "查询", "问答"]}])
    return [A2AServer(tool_card, tool_execute), A2AServer(qa_card, qa_execute)]


# ============================================================
# 组件 4：A2ARouter —— 网关（模块注入 + 能力发现 + 结构化派发）
# ============================================================

class A2ARouter:
    """A2A 网关：注入多个 Agent 模块（教材语义保留），提供能力发现与任务派发

    教材"模块注入"（register_agent）语义保留；新增 find_agent 能力发现
    ——调用方按 skill 标签找目标，不再硬编码 receiver 字符串
    """

    def __init__(self):
        """初始化网关（Agent 注册表 + JSON-RPC 自增请求 id）"""
        self.agents: dict = {}
        self._next_id = 0

    def register_agent(self, agent: A2AServer):
        """注入 Agent 模块（教材方法语义保留）"""
        self.agents[agent.card.name] = agent

    def get_agent_card(self, name: str):
        """取指定 Agent 的自描述卡片（未注册返回 None）"""
        agent = self.agents.get(name)
        return agent.get_agent_card() if agent else None

    def find_agent(self, skill_tag: str):
        """按 skill 标签发现 Agent（A2A 能力发现语义，替代硬编码名字）

        参数: skill_tag — 技能标签（如 "qa" / "tool"）
        返回: 首个匹配的 Agent 名称；无匹配返回 None
        """
        for name, agent in self.agents.items():
            if any(skill_tag in s["tags"] for s in agent.card.skills):
                return name
        return None

    def dispatch(self, msg: A2AMessage) -> dict:
        """派发消息（JSON-RPC message/send）→ 结构化 Task 结果

        参数: msg — A2A 消息（receiver 决定目标 Agent）
        返回: {"success", "taskId", "state", "response"}；
              未注册目标返回 {"success": False, "error"}（修复教材错误混流）
        """
        server = self.agents.get(msg.receiver)
        if server is None:
            # 教材语义保留：目标不存在返回错误——但走结构化通道，不混流
            return {"success": False, "taskId": None, "state": "unknown",
                    "response": "", "error": f"目标Agent不存在：{msg.receiver}"}
        self._next_id += 1
        request = {"jsonrpc": "2.0", "id": self._next_id, "method": "message/send",
                   "params": {"message": msg.to_a2a_message()}}
        logger.info(f"[A2A] {msg.sender} → {msg.receiver}（message/send）")
        response = server.handle(request)
        if "error" in response:
            err = response["error"]
            return {"success": False, "taskId": None, "state": "error",
                    "response": "", "error": f"{err['code']} {err['message']}"}
        task = response["result"]
        state = task["status"]["state"]
        text = ""
        if state == "completed":
            text = "".join(p["text"] for a in task.get("artifacts", [])
                           for p in a.get("parts", []))
        else:
            text = task["status"].get("message", "")
        return {"success": state == "completed", "taskId": task["id"],
                "state": state, "response": text}


# ============================================================
# self-test（5 项）
# ============================================================

def run_self_test() -> bool:
    """验证 Agent Card 发现 / Task 生命周期 / 真实问答 / 失败路径 / 协议错误码"""
    ok = True
    router = A2ARouter()
    for agent in build_agents():
        router.register_agent(agent)

    print("\n" + "=" * 60)
    print("  char13-07 A2A 消息协议的模块注入 —— Self Test")
    print("=" * 60)

    # Test 1: Agent Card 自描述与 skill 发现
    print("\n--- Test 1: Agent Card 与能力发现 ---")
    try:
        card = router.get_agent_card("AnswerAgent")
        assert card and card["protocolVersion"] == "1.0", card
        assert any(s["id"] == "qa" for s in card["skills"]), card
        assert router.find_agent("qa") == "AnswerAgent", "按 qa 标签应发现 AnswerAgent"
        assert router.find_agent("tool") == "ToolAgent", "按 tool 标签应发现 ToolAgent"
        assert router.find_agent("nope") is None, "无匹配标签应返回 None"
        print(f"  [通过] 卡片含 protocolVersion/skills；标签发现：qa→AnswerAgent、tool→ToolAgent")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 2: message/send Task 生命周期（tool_call，无 LLM）
    print("\n--- Test 2: Task 生命周期（tool_call）---")
    try:
        msg = A2AMessage(sender="MainAgent", receiver="ToolAgent",
                         payload="请将CSV文件中的数据进行分析",
                         metadata={"task_type": "tool_call", "tool": "DataAnalyzer"})
        result = router.dispatch(msg)
        assert result["success"] and result["state"] == "completed", result
        assert result["taskId"], result
        assert "已调用工具：DataAnalyzer" in result["response"], result
        assert "请将CSV文件中的数据进行分析" in result["response"], result
        print(f"  [通过] {result['response']}")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 3: 真实 qa（qwen-plus）
    print("\n--- Test 3: 真实问答路由（qwen-plus）---")
    try:
        msg = A2AMessage(sender="MainAgent", receiver="AnswerAgent",
                         payload="什么是Transformer架构？", metadata={"task_type": "qa"})
        result = router.dispatch(msg)
        assert result["success"] and result["state"] == "completed", result
        assert result["response"], result
        print(f"  [通过] {result['response'][:50]}...")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 4: 失败路径与 tasks/get（Task 级失败 ≠ 协议错误）
    print("\n--- Test 4: 任务失败与 tasks/get ---")
    try:
        def fail_execute(payload, metadata):
            raise RuntimeError("模拟工具故障")

        fail_card = AgentCard(name="FailAgent", description="测试用",
                              skills=[{"id": "boom", "name": "故障", "description": "", "tags": ["boom"]}])
        fail_server = A2AServer(fail_card, fail_execute)
        resp = fail_server.handle({"jsonrpc": "2.0", "id": 9, "method": "message/send",
                                   "params": {"message": {"role": "user", "messageId": "m1",
                                                          "parts": [{"kind": "text", "text": "触发故障"}]}}})
        task = resp["result"]
        assert task["status"]["state"] == "failed", task
        assert "模拟工具故障" in task["status"]["message"], task
        # tasks/get：已存在的任务可查询；不存在的返回 -32001
        resp = fail_server.handle({"jsonrpc": "2.0", "id": 10, "method": "tasks/get",
                                   "params": {"id": task["id"]}})
        assert resp["result"]["status"]["state"] == "failed", resp
        resp = fail_server.handle({"jsonrpc": "2.0", "id": 11, "method": "tasks/get",
                                   "params": {"id": "no-such-task"}})
        assert resp["error"]["code"] == -32001, resp
        print("  [通过] 技能失败 → state=failed（非协议错误）；tasks/get 可查询；未知任务 → -32001")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 5: 协议错误码与未注册目标
    print("\n--- Test 5: 协议错误码 ---")
    try:
        server = router.agents["AnswerAgent"]
        resp = server.handle({"jsonrpc": "2.0", "id": 12, "method": "no/such/method"})
        assert resp["error"]["code"] == -32601, resp
        resp = server.handle({"jsonrpc": "2.0", "id": 13, "method": "message/send",
                              "params": {"message": {"role": "user", "parts": []}}})
        assert resp["error"]["code"] == -32602, resp
        result = router.dispatch(A2AMessage(sender="X", receiver="Ghost", payload="hi"))
        assert result["success"] is False and "目标Agent不存在" in result["error"], result
        print("  [通过] 未知方法 → -32601；parts 为空 → -32602；未注册目标 → 结构化错误（不混流）")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    return ok


def run_demo():
    """手动体验入口：教材同款两条消息（tool_call + qa）"""
    router = A2ARouter()
    for agent in build_agents():
        router.register_agent(agent)

    msg1 = A2AMessage(sender="MainAgent", receiver="ToolAgent",
                      payload="请将CSV文件中的数据进行分析",
                      metadata={"task_type": "tool_call", "tool": "DataAnalyzer"})
    msg2 = A2AMessage(sender="MainAgent", receiver="AnswerAgent",
                      payload="什么是Transformer架构？", metadata={"task_type": "qa"})

    print("消息1响应：", router.dispatch(msg1))
    print("消息2响应：", router.dispatch(msg2))


def main():
    """入口：跑 self-test；--demo 进入手动体验"""
    ok = run_self_test()
    print("\n" + "=" * 60)
    print("  全部 5 项 self-test 通过" if ok else "  存在失败项")
    print("=" * 60)
    if "--demo" in sys.argv:
        run_demo()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
