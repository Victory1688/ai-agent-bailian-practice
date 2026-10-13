# 第13章 项目案例：从零实现一个复合智能体系统
# 【例13-6】MCP 协议的上下文路由器
#
# ★ 教材简化 vs 真实 MCP 规范（Anthropic 2024-11 发布，2025-06-18 修订）
#
# 教材原版问题（已注释保留）：
#   ① 【最严重】标题叫 MCP，但与真实 MCP 协议毫无关系——真实 MCP 是
#      JSON-RPC 2.0 信封 + initialize 生命周期握手 + tools/resources/prompts
#      三大原语 + 标准错误码（-32700/-32601/-32602）的跨进程开放标准；
#      教材的 "MCPMessage" 只是给消息加了 call_type 字段，"MCPContext"
#      是普通会话历史——借壳命名，学生学习后会带着错误认知进入生产
#   ② Qwen2Chat / DeepSeekChat 虚构类 + langchain.schema 过时 import
#      （同 13-01，import 即崩）
#   ③ get_last_intent 倒序扫描全部历史——旧消息的关键词会劫持当前意图
#      （最后一条 user 说"今天天气不错"，倒序却命中更早的"执行"→ 误路由）；
#      且关键词表硬编码在方法体内
#   ④ 意图 → 模型的 if/elif 映射硬编码在 route() 里（13-04 同款平行映射）
#   ⑤ 路由器职责越界：名为路由器却亲自调模型生成回答——路由（决定发给谁）
#      与执行（目标方干活）混在一起
#   ⑥ call_type 字段记录了但全程无人消费——摆设字段
#   ⑦ 错误字符串混流：route 返回 "[ERROR] ..." 字符串，调用方无法程序化判断
#   ⑧ 无 self-test
#
# 本次改写（按真实 MCP 2025-06-18 规范重构，char12-07 已验证模式）：
#   ① McServer：JSON-RPC 2.0 单入口 handle()，支持 initialize 生命周期
#      （protocolVersion 2025-06-18 + capabilities + serverInfo）、tools/list、
#      tools/call 三方法；notifications/initialized 无响应；标准错误码
#      -32601（方法不存在）/-32602（参数不合法）；工具级错误按 MCP 规范
#      用 isError 标记，不占用协议错误码
#   ② 传输层解耦：handle(dict) 进程内传递（教学边界），生产换 stdio/HTTP
#      零改动——MCP 是协议不是传输方式
#   ③ 路由语义复位：MCPRouter 是 MCP 客户端，按意图路由到不同 MCP Server
#      （knowledge / ops / chat），每个 server 通过 tools/call 提供能力；
#      初始化时完成规范要求的 initialize 握手
#   ④ get_last_intent 修正：只认最后一条 user 消息（旧意图不再劫持），
#      关键词表提为注册表常量
#   ⑤ 意图 → (server, tool, 参数键) 路由表注册表化（消灭 if/elif 平行映射）
#   ⑥ route 返回结构化 {"success", "intent", "server", "response"}
#   ⑦ self-test 5 项：生命周期握手 / 协议错误码 / 意图修正对照（教材 bug
#      实证）/ 真实路由生成 / tool+dialog 路由与结构化契约

# ============================================================
# 原代码（注释保留——教材简化版，借壳 MCP + 意图劫持 + 职责越界）
# ============================================================
# # 【例13-6】
# # -*- coding:utf-8 -*-
# # MCP上下文路由配置与调用系统
# # 支持任务类型识别，上下文状态挂载，智能体目标分发与模型动态调用，
# # 可嵌入多智能体协同调度链中，保障上下文的连续性与执行路径的准确性。
#
# import uuid
# from typing import List, Dict
# from langchain_community.chat_models import Qwen2Chat, DeepSeekChat   # ← 虚构类
# from langchain.schema import HumanMessage, AIMessage, SystemMessage   # ← 过时 import
#
# # 一、定义MCP消息协议结构
# class MCPMessage:
#     def __init__(self, role: str, content: str, call_type: str = "prompt"):
#         self.role = role          # user, assistant, system
#         self.content = content
#         self.call_type = call_type    # prompt, tool_call, response（全程无人消费）
#
#     def to_langchain(self):       # ← 翻译层：本项目统一 dashscope 原生格式，无需中转
#         if self.role == "user":
#             return HumanMessage(content=self.content)
#         elif self.role == "assistant":
#             return AIMessage(content=self.content)
#         elif self.role == "system":
#             return SystemMessage(content=self.content)
#         else:
#             raise ValueError("非法角色")
#
# # 二、MCP上下文封装器
# class MCPContext:
#     def __init__(self, session_id=None):
#         self.session_id = session_id or str(uuid.uuid4())
#         self.history: List[MCPMessage] = []
#
#     def add(self, role: str, content: str, call_type="prompt"):
#         self.history.append(MCPMessage(role, content, call_type))
#
#     def get_langchain_messages(self):
#         return [msg.to_langchain() for msg in self.history]
#
#     def get_last_intent(self) -> str:
#         for msg in reversed(self.history):        # ← 倒序扫全史：旧意图劫持当前路由
#             if msg.role == "user" and "查询" in msg.content:
#                 return "qa"
#             elif msg.role == "user" and "执行" in msg.content:
#                 return "tool"
#         return "dialog"
#
# # 三、上下文路由器
# class MCPRouter:
#     def __init__(self):
#         self.qwen = Qwen2Chat(model="Qwen/Qwen1.5-7B-Chat")       # ← 虚构
#         self.deepseek = DeepSeekChat(model="deepseek-ai/deepseek-llm-chat")
#
#     def route(self, context: MCPContext) -> str:
#         intent = context.get_last_intent()
#         print(f"[路由] 当前识别意图类型：{intent}")
#         if intent == "qa":
#             model = self.qwen            # ← 意图→模型 if/elif 硬编码
#         elif intent == "tool":
#             model = self.deepseek
#         else:
#             model = self.qwen
#         try:
#             messages = context.get_langchain_messages()   # ← 全史重放，无差别转发
#             response = model(messages)
#             return response.content.strip()
#         except Exception as e:
#             return f"[ERROR] 模型调用失败：{str(e)}"      # ← 错误混流
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
MCP_PROTOCOL_VERSION = "2025-06-18"   # 真实 MCP 最新修订版协议版本号

# JSON-RPC 2.0 标准协议错误码（MCP 复用 JSON-RPC 的错误语义）
PARSE_ERROR = -32700
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# 意图关键词表（教材硬编码在方法内，改写提为注册表常量）
INTENT_KEYWORDS = {
    "qa": ("查询", "问答", "介绍"),
    "tool": ("执行", "运行"),
    "dialog": (),
}

# 意图 → (目标 server, 目标工具, 参数键) 路由表（消灭教材 if/elif 平行映射）
INTENT_ROUTES = {
    "qa": ("knowledge-server", "ask_knowledge", "query"),
    "tool": ("ops-server", "run_script", "script"),
    "dialog": ("chat-server", "chitchat", "message"),
}


# ============================================================
# 组件 1：工具实现 —— 三个 MCP Server 各自暴露的能力
# ============================================================

def ask_knowledge(query: str) -> str:
    """知识问答工具（knowledge-server）：qwen-plus 生成回答

    参数: query — 用户知识类问题
    返回: 回答文本
    异常: RuntimeError — 模型接口非 200（由 MCP 层转 isError）
    """
    resp = dashscope.Generation.call(
        model="qwen-plus",
        messages=[{"role": "user", "content": query}],
        max_tokens=MAX_TOKENS, result_format="message")
    if resp.status_code != 200:
        raise RuntimeError(f"{resp.code} {resp.message}")
    return resp.output.choices[0].message.content.strip()


def run_script(script: str) -> str:
    """脚本执行工具（ops-server）：教材"执行统计脚本"语义（模拟）"""
    name = script.strip()
    if not name:
        raise ValueError("脚本名为空，无法执行")
    return f"脚本《{name}》执行完成：统计任务输出 3 条结果（模拟）"


def chitchat(message: str) -> str:
    """闲聊工具（chat-server）：qwen-turbo 生成（教材"闲聊用另一模型"语义）"""
    resp = dashscope.Generation.call(
        model="qwen-turbo",
        messages=[{"role": "user", "content": message}],
        max_tokens=MAX_TOKENS, result_format="message")
    if resp.status_code != 200:
        raise RuntimeError(f"{resp.code} {resp.message}")
    return resp.output.choices[0].message.content.strip()


# 工具声明表：name → {description, inputSchema, execute}
# inputSchema 即 MCP tools/list 返回的 JSON Schema（与 OpenAI 兼容格式一致）
TOOL_SPECS = {
    "ask_knowledge": {
        "description": "回答知识类问题",
        "inputSchema": {"type": "object",
                        "properties": {"query": {"type": "string", "description": "知识类问题"}},
                        "required": ["query"]},
        "execute": ask_knowledge,
    },
    "run_script": {
        "description": "执行指定名称的脚本任务",
        "inputSchema": {"type": "object",
                        "properties": {"script": {"type": "string", "description": "脚本名称"}},
                        "required": ["script"]},
        "execute": run_script,
    },
    "chitchat": {
        "description": "与用户进行日常闲聊",
        "inputSchema": {"type": "object",
                        "properties": {"message": {"type": "string", "description": "闲聊消息"}},
                        "required": ["message"]},
        "execute": chitchat,
    },
}


# ============================================================
# 组件 2：McServer —— 符合真实 MCP 规范的最小服务端（JSON-RPC 2.0 单入口）
# ============================================================

class JsonRpcError(Exception):
    """JSON-RPC 协议级错误（与工具级 isError 错误严格区分）"""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class McServer:
    """MCP 服务端最小实现：initialize 生命周期 + tools 原语 + 标准错误码

    传输层解耦：handle(dict) 进程内传递（教学边界），生产换 stdio/HTTP 零改动
    ——MCP 是协议不是传输方式
    """

    def __init__(self, name: str, tool_names: list):
        """初始化服务端

        参数: name — serverInfo.serverInfo 名称; tool_names — 本 server 暴露的工具名列表
        异常: ValueError — 工具名未在 TOOL_SPECS 声明
        """
        for t in tool_names:
            if t not in TOOL_SPECS:
                raise ValueError(f"工具 {t} 未在 TOOL_SPECS 声明")
        self.name = name
        self.tools = tool_names
        self._initialized = False

    def handle(self, request: dict):
        """JSON-RPC 2.0 单入口：请求 dict 进，响应 dict 出（通知返回 None）

        参数: request — 完整 JSON-RPC 请求（含 jsonrpc/id/method/params）
        返回: 响应 dict（{"jsonrpc", "id", "result"} 或 {"jsonrpc", "id", "error"}）；
              通知（无 id）返回 None
        """
        method = request.get("method", "")
        req_id = request.get("id")
        if method.startswith("notifications/"):
            return None   # MCP 规范：通知不产生响应
        try:
            handler = {"initialize": self._initialize,
                       "tools/list": self._tools_list,
                       "tools/call": self._tools_call}.get(method)
            if handler is None:
                raise JsonRpcError(METHOD_NOT_FOUND, f"方法不存在：{method}")
            result = handler(request.get("params") or {})
            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        except JsonRpcError as e:
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": e.code, "message": e.message}}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": INTERNAL_ERROR, "message": str(e)}}

    def _initialize(self, params: dict) -> dict:
        """生命周期握手（MCP 规范要求：客户端调用任何方法前必须 initialize）"""
        client_proto = params.get("protocolVersion", "")
        if client_proto and client_proto != MCP_PROTOCOL_VERSION:
            raise JsonRpcError(INVALID_PARAMS,
                               f"协议版本不兼容：{client_proto}（服务端支持 {MCP_PROTOCOL_VERSION}）")
        self._initialized = True
        return {"protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": self.name, "version": "1.0.0"}}

    def _tools_list(self, params: dict) -> dict:
        """列出本 server 暴露的工具（MCP tools 原语）"""
        return {"tools": [{"name": t, "description": TOOL_SPECS[t]["description"],
                           "inputSchema": TOOL_SPECS[t]["inputSchema"]}
                          for t in self.tools]}

    def _tools_call(self, params: dict) -> dict:
        """执行工具调用（MCP tools 原语）

        协议错误（方法/参数问题）抛 JsonRpcError 用标准错误码；
        工具执行错误（业务性失败）按 MCP 规范用 isError 标记，不占用错误码
        """
        name = params.get("name")
        args = params.get("arguments") or {}
        if name not in self.tools:
            raise JsonRpcError(INVALID_PARAMS, f"工具 {name} 不在本 server 能力列表")
        required = TOOL_SPECS[name]["inputSchema"].get("required", [])
        for key in required:
            if key not in args:
                raise JsonRpcError(INVALID_PARAMS, f"缺少必填参数：{key}")
        try:
            text = str(TOOL_SPECS[name]["execute"](**args))
            return {"content": [{"type": "text", "text": text}], "isError": False}
        except Exception as e:
            logger.warning(f"[MCP] 工具 {name} 执行失败: {e}")
            return {"content": [{"type": "text", "text": f"工具执行失败：{e}"}],
                    "isError": True}


def build_servers() -> dict:
    """装配三个意图域的 MCP Server（教材 qa/tool/dialog 三意图 → 三个能力服务）"""
    return {
        "knowledge-server": McServer("knowledge-server", ["ask_knowledge"]),
        "ops-server": McServer("ops-server", ["run_script"]),
        "chat-server": McServer("chat-server", ["chitchat"]),
    }


# ============================================================
# 组件 3：MCPContext —— 会话上下文（意图识别 bug 修正版）
# ============================================================

class MCPContext:
    """会话上下文：消息历史 + 意图识别（只认最后一条 user 消息）"""

    def __init__(self, session_id: str = None):
        """初始化上下文

        参数: session_id — 会话标识；缺省自动生成 uuid
        """
        self.session_id = session_id or str(uuid.uuid4())
        self.history: list = []

    def add(self, role: str, content: str, call_type: str = "prompt"):
        """追加一条消息（call_type 标注消息类型，供下游按需消费）"""
        self.history.append({"role": role, "content": content, "call_type": call_type})

    def get_last_intent(self) -> str:
        """识别当前意图（教材 bug 修复：只看最后一条 user 消息）

        教材版倒序扫描全部历史，旧消息关键词会劫持当前意图——例如最后一条
        说"今天天气不错"、更早说过"执行脚本"，教材会误路由到 tool。

        返回: "qa" / "tool" / "dialog"（最后一条不含已知关键词即闲聊）
        """
        for msg in reversed(self.history):
            if msg["role"] != "user":
                continue
            text = msg["content"]
            for intent, keywords in INTENT_KEYWORDS.items():
                if any(k in text for k in keywords):
                    return intent
            return "dialog"
        return "dialog"

    def get_last_user_message(self) -> str:
        """取最后一条 user 消息（路由器只转发当前问题，不重放全史）"""
        for msg in reversed(self.history):
            if msg["role"] == "user":
                return msg["content"]
        return ""


# ============================================================
# 组件 4：MCPRouter —— MCP 客户端路由器（路由与执行分离）
# ============================================================

class MCPRouter:
    """上下文路由器：MCP 客户端角色，按意图把请求路由到目标 MCP Server

    职责复位：路由器只决定"发给谁"并完成协议调用，执行由目标 server 的
    工具完成——教材"路由器亲自调模型"的职责越界在此修正
    """

    def __init__(self):
        """装配 servers 并完成 MCP 规范要求的 initialize 生命周期握手"""
        self.servers = build_servers()
        self._next_id = 0
        for name, server in self.servers.items():
            result = self._request(server, "initialize", {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "context-router", "version": "1.0.0"},
            })
            assert result["protocolVersion"] == MCP_PROTOCOL_VERSION, result
            logger.info(f"[握手] {name} 初始化完成（protocolVersion={result['protocolVersion']}）")
            self._notify(server, "notifications/initialized")

    def _request(self, server: McServer, method: str, params: dict = None) -> dict:
        """发送 JSON-RPC 请求并解析结果

        参数: server — 目标 MCP Server; method — 方法名; params — 请求参数
        返回: result 部分
        异常: RuntimeError — 响应携带 error（协议层失败）
        """
        self._next_id += 1
        request = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            request["params"] = params
        response = server.handle(request)
        if response is None or "error" in response:
            err = (response or {}).get("error", {})
            raise RuntimeError(f"MCP 调用失败: {err.get('code')} {err.get('message')}")
        return response["result"]

    def _notify(self, server: McServer, method: str):
        """发送通知（无 id，无响应——MCP 规范）"""
        server.handle({"jsonrpc": "2.0", "method": method})

    def route(self, context: MCPContext) -> dict:
        """按意图路由：识别意图 → 选目标 server → tools/call → 结构化返回

        参数: context — 会话上下文
        返回: {"success", "intent", "server", "response"} 结构化契约
              （修复教材错误字符串混流，调用方可程序化判断）
        """
        try:
            intent = context.get_last_intent()
            server_name, tool_name, arg_key = INTENT_ROUTES[intent]
            payload = context.get_last_user_message()
            logger.info(f"[路由] 意图={intent} → {server_name}.{tool_name}")
            result = self._request(self.servers[server_name], "tools/call",
                                   {"name": tool_name, "arguments": {arg_key: payload}})
            text = result["content"][0]["text"]
            is_error = result.get("isError", False)
            return {"success": not is_error, "intent": intent,
                    "server": server_name, "response": text}
        except Exception as e:
            logger.error(f"[路由] 路由失败: {e}")
            return {"success": False, "intent": None, "server": None,
                    "response": "", "error": str(e)}


# ============================================================
# self-test（5 项）
# ============================================================

def run_self_test() -> bool:
    """验证生命周期握手 / 协议错误码 / 意图修正 / 真实路由 / 结构化契约"""
    ok = True
    router = MCPRouter()

    print("\n" + "=" * 60)
    print("  char13-06 MCP 协议的上下文路由器 —— Self Test")
    print("=" * 60)

    # Test 1: MCP 生命周期握手与协议错误码
    print("\n--- Test 1: initialize 生命周期与协议错误码 ---")
    try:
        server = build_servers()["knowledge-server"]
        resp = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                              "params": {"protocolVersion": MCP_PROTOCOL_VERSION,
                                         "capabilities": {}, "clientInfo": {"name": "t"}}})
        assert resp["result"]["protocolVersion"] == "2025-06-18", resp
        assert resp["result"]["serverInfo"]["name"] == "knowledge-server", resp
        assert server.handle({"jsonrpc": "2.0",
                              "method": "notifications/initialized"}) is None, "通知不应有响应"
        resp = server.handle({"jsonrpc": "2.0", "id": 2, "method": "no/such/method"})
        assert resp["error"]["code"] == -32601, resp
        print(f"  [通过] 握手返回 protocolVersion=2025-06-18；通知无响应；未知方法 → -32601")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 2: tools/list 与参数校验（协议错误 vs 工具错误）
    print("\n--- Test 2: tools/list 与 -32602 参数校验 ---")
    try:
        server = build_servers()["ops-server"]
        resp = server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
        names = [t["name"] for t in resp["result"]["tools"]]
        assert names == ["run_script"] and "inputSchema" in resp["result"]["tools"][0], resp
        resp = server.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                              "params": {"name": "run_script", "arguments": {}}})
        assert resp["error"]["code"] == -32602 and "缺少必填参数" in resp["error"]["message"], resp
        resp = server.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                              "params": {"name": "unknown", "arguments": {}}})
        assert resp["error"]["code"] == -32602, resp
        print(f"  [通过] tools/list 返回 schema；缺参 / 未知工具均 → -32602")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 3: 意图识别修正（教材 bug 实证对照）
    print("\n--- Test 3: 意图识别——旧意图不再劫持 ---")
    try:
        ctx = MCPContext()
        ctx.add("user", "请帮我查询一下2023年中国GDP")
        ctx.add("assistant", "好的，正在查询...")
        ctx.add("user", "此外，还请帮我执行一个统计脚本")
        assert ctx.get_last_intent() == "tool", "教材 demo 场景应路由 tool"
        ctx2 = MCPContext()
        ctx2.add("user", "请执行备份脚本")
        ctx2.add("user", "今天天气真不错啊")   # 最后一条不含关键词
        assert ctx2.get_last_intent() == "dialog", \
            "最后一条 user 决定意图（教材倒序扫描会误命中旧'执行'返回 tool）"
        print("  [通过] 教材场景 tool 正确；闲聊结尾 → dialog（教材版会误路由 tool）")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 4: 真实路由（qa → knowledge-server → qwen-plus）
    print("\n--- Test 4: 真实路由问答（qwen-plus）---")
    try:
        ctx = MCPContext()
        ctx.add("system", "你是一个知识丰富的智能助手")
        ctx.add("user", "请帮我查询一下2023年中国GDP是多少")
        result = router.route(ctx)
        assert result["success"] and result["response"], result
        assert result["server"] == "knowledge-server" and result["intent"] == "qa", result
        print(f"  [通过] {result['response'][:50]}...")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 5: tool / dialog 路由与结构化契约
    print("\n--- Test 5: tool+dialog 路由与契约 ---")
    try:
        ctx = MCPContext()
        ctx.add("user", "此外，还请帮我执行一个统计脚本")
        result = router.route(ctx)
        assert result["success"] and result["server"] == "ops-server", result
        assert "统计" in result["response"], result
        ctx2 = MCPContext()
        ctx2.add("user", "今天天气真不错啊，随便聊聊")
        result2 = router.route(ctx2)
        assert result2["success"] and result2["server"] == "chat-server", result2
        assert result2["response"], result2
        print(f"  [通过] tool → {result['response'][:36]}...；dialog → {result2['response'][:24]}...")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    return ok


def run_demo():
    """手动体验入口：教材同款场景（先查询后执行 → 路由到 ops-server）"""
    context = MCPContext()
    context.add("system", "你是一个知识丰富的智能助手")
    context.add("user", "请帮我查询一下2023年中国GDP是多少")
    context.add("assistant", "好的，我正在查询相关数据...")
    context.add("user", "此外，还请帮我执行一个统计脚本")

    router = MCPRouter()
    result = router.route(context)
    print(f"[路由] 意图={result['intent']} → {result['server']}")
    print("[执行结果] ", result["response"] if result["success"] else result.get("error"))


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
