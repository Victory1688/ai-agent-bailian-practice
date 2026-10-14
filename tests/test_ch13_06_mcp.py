"""
test_ch13_06_mcp.py —— chapter13 / 06 MCP 协议的上下文路由器

【TDD 定位】被测文件：chapter13/06_MCP协议的上下文路由器.py
【测试策略】JSON-RPC 协议层 = 纯 dict 进出，完美适合 TDD（零成本穷举）；
            涉及 LLM 的工具（ask_knowledge/chitchat）= @pytest.mark.live

【本篇要守住的契约】（来自源码逐行核对，非臆造）
  - JSON-RPC 2.0 错误码：-32700/-32601/-32602/-32603
  - MCP_PROTOCOL_VERSION = "2025-06-18"
  - 通知（notifications/*）返回 None，不产生响应
  - 未知方法 → METHOD_NOT_FOUND；协议版本不兼容 → INVALID_PARAMS
  - tools/call 缺必填参数 → INVALID_PARAMS；工具业务失败 → isError=True（不算协议错误）
  - 协议错误（JsonRpcError）与工具错误（isError）严格区分
"""

import pytest

pytestmark = pytest.mark.usefixtures("ch13_06")


# ============================================================
# 1. 协议常量
# ============================================================

def test_protocol_version(ch13_06):
    """必须声明真实 MCP 协议版本 2025-06-18"""
    assert ch13_06.MCP_PROTOCOL_VERSION == "2025-06-18"


def test_jsonrpc_error_codes(ch13_06):
    """JSON-RPC 2.0 标准错误码必须精确（MCP 复用其语义）"""
    assert ch13_06.PARSE_ERROR == -32700
    assert ch13_06.METHOD_NOT_FOUND == -32601
    assert ch13_06.INVALID_PARAMS == -32602
    assert ch13_06.INTERNAL_ERROR == -32603


def test_intent_routes_complete(ch13_06):
    """意图路由表必须覆盖三个意图，且指向已声明的工具"""
    assert set(ch13_06.INTENT_ROUTES.keys()) == {"qa", "tool", "dialog"}
    for intent, (server, tool, key) in ch13_06.INTENT_ROUTES.items():
        assert tool in ch13_06.TOOL_SPECS, f"{intent} 路由到未声明工具 {tool}"


def test_tool_specs_have_execute(ch13_06):
    """每个工具声明必须含 description/inputSchema/execute 三要素"""
    for name, spec in ch13_06.TOOL_SPECS.items():
        assert "description" in spec
        assert "inputSchema" in spec
        assert callable(spec["execute"])


# ============================================================
# 2. McServer 构造校验
# ============================================================

def test_server_rejects_undeclared_tool(ch13_06):
    """挂载未声明的工具名必须 ValueError（fail fast）"""
    with pytest.raises(ValueError):
        ch13_06.McServer("bad-server", ["no_such_tool"])


def test_server_accepts_declared_tools(ch13_06):
    """挂载已声明工具正常"""
    srv = ch13_06.McServer("knowledge-server", ["ask_knowledge"])
    assert srv.name == "knowledge-server"
    assert srv.tools == ["ask_knowledge"]


# ============================================================
# 3. JSON-RPC 协议层（纯 dict，全量断言）
# ============================================================

def test_notification_returns_none(ch13_06):
    """通知不产生响应（JSON-RPC 2.0 规范）"""
    srv = ch13_06.McServer("s", ["run_script"])
    assert srv.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_unknown_method_error(ch13_06):
    """未知方法 → METHOD_NOT_FOUND"""
    srv = ch13_06.McServer("s", ["run_script"])
    resp = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "no/such"})
    assert resp["error"]["code"] == ch13_06.METHOD_NOT_FOUND
    assert resp["id"] == 1


def test_initialize_handshake(ch13_06):
    """initialize 返回协议版本 + capabilities + serverInfo"""
    srv = ch13_06.McServer("knowledge-server", ["ask_knowledge"])
    resp = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {"protocolVersion": "2025-06-18"}})
    result = resp["result"]
    assert result["protocolVersion"] == "2025-06-18"
    assert "capabilities" in result
    assert result["serverInfo"]["name"] == "knowledge-server"


def test_initialize_version_mismatch(ch13_06):
    """协议版本不兼容 → INVALID_PARAMS"""
    srv = ch13_06.McServer("s", ["run_script"])
    resp = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {"protocolVersion": "1999-01-01"}})
    assert resp["error"]["code"] == ch13_06.INVALID_PARAMS


def test_initialize_empty_version_accepted(ch13_06):
    """未指定版本时不应报错（宽容握手）"""
    srv = ch13_06.McServer("s", ["run_script"])
    resp = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert "result" in resp


def test_tools_list_shape(ch13_06):
    """tools/list 返回 tools 数组，每项含 name/description/inputSchema"""
    srv = ch13_06.McServer("knowledge-server", ["ask_knowledge"])
    resp = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    tools = resp["result"]["tools"]
    assert len(tools) == 1
    assert tools[0]["name"] == "ask_knowledge"
    assert "inputSchema" in tools[0]


def test_response_envelope_format(ch13_06):
    """所有响应必须是 {"jsonrpc": "2.0", "id", ...} 信封"""
    srv = ch13_06.McServer("s", ["run_script"])
    for req in [{"jsonrpc": "2.0", "id": 7, "method": "tools/list", "params": {}},
                {"jsonrpc": "2.0", "id": 7, "method": "bad/method"}]:
        resp = srv.handle(req)
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 7


# ============================================================
# 4. tools/call —— 协议错误 vs 工具错误（核心语义区分）
# ============================================================

def test_tools_call_unknown_tool_in_server(ch13_06):
    """调用不在本 server 能力列表的工具 → INVALID_PARAMS（协议错误）"""
    srv = ch13_06.McServer("knowledge-server", ["ask_knowledge"])
    resp = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": "run_script", "arguments": {"script": "x"}}})
    assert resp["error"]["code"] == ch13_06.INVALID_PARAMS


def test_tools_call_missing_required_param(ch13_06):
    """缺必填参数 → INVALID_PARAMS（协议错误）"""
    srv = ch13_06.McServer("ops-server", ["run_script"])
    resp = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": "run_script", "arguments": {}}})
    assert resp["error"]["code"] == ch13_06.INVALID_PARAMS
    assert "script" in resp["error"]["message"]


def test_tools_call_success_shape(ch13_06):
    """成功调用返回 {content:[{type,text}], isError:False}"""
    srv = ch13_06.McServer("ops-server", ["run_script"])
    resp = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": "run_script", "arguments": {"script": "日报"}}})
    result = resp["result"]
    assert result["isError"] is False
    assert result["content"][0]["type"] == "text"
    assert "日报" in result["content"][0]["text"]


def test_tools_call_business_error_is_iserror_not_code(ch13_06):
    """工具业务失败用 isError=True 标记，不占用 JSON-RPC 错误码（关键设计）"""
    srv = ch13_06.McServer("ops-server", ["run_script"])
    # 空脚本名触发 run_script 的 ValueError → 应转为 isError=True 而非 error.code
    resp = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": "run_script", "arguments": {"script": "   "}}})
    assert "result" in resp, "工具业务错误不应变成协议错误"
    assert resp["result"]["isError"] is True


# ============================================================
# 5. 纯函数工具（无 LLM）
# ============================================================

def test_run_script_normal(ch13_06):
    """run_script 正常执行（纯模拟，无 LLM）"""
    out = ch13_06.run_script("统计脚本")
    assert "统计脚本" in out and "执行完成" in out


def test_run_script_empty_raises(ch13_06):
    """空脚本名抛 ValueError（供 isError 路径测试）"""
    with pytest.raises(ValueError):
        ch13_06.run_script("   ")


# ============================================================
# 6. 真实 LLM 工具
# ============================================================

@pytest.mark.live
def test_ask_knowledge_real(ch13_06):
    """知识问答工具真实调用（qwen-plus）"""
    out = ch13_06.ask_knowledge("什么是机器学习？请一句话回答")
    assert isinstance(out, str) and out.strip()


@pytest.mark.live
def test_chitchat_real(ch13_06):
    """闲聊工具真实调用（qwen-turbo）"""
    out = ch13_06.chitchat("你好")
    assert isinstance(out, str) and out.strip()
