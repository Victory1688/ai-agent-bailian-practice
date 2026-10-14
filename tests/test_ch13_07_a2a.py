"""
test_ch13_07_a2a.py —— chapter13 / 07 A2A 消息协议的模块注入

【TDD 定位】被测文件：chapter13/07_A2A消息协议的模块注入.py
【测试策略】AgentCard / A2AMessage / A2AServer 协议层 = 纯 dict，全量断言；
            真实 Agent 执行 = @pytest.mark.live

【本篇要守住的契约】（来自源码逐行核对，非臆造）
  - A2A 错误码：METHOD_NOT_FOUND -32601 / INVALID_PARAMS -32602 /
    INTERNAL_ERROR -32603 / TASK_NOT_FOUND -32001（A2A 特有）
  - AgentCard.as_dict 含 name/description/url/version/protocolVersion/skills
  - A2AMessage.to_a2a_message 输出 role + messageId + parts（TextPart + 可选 DataPart）
  - 通知（notifications/*）返回 None
  - message/send 产生 Task；tasks/get 按 task_id 查询；不存在 → TASK_NOT_FOUND
  - A2ARouter 按 skill_tag 发现 Agent
"""

import pytest

pytestmark = pytest.mark.usefixtures("ch13_07")


@pytest.fixture
def make_card(ch13_07):
    """构造测试用 AgentCard 的工厂"""
    def _make(name="test-agent", skills=None):
        skills = skills or [{"id": "s1", "name": "问答", "description": "回答问题",
                             "tags": ["qa"]}]
        return ch13_07.AgentCard(name, "测试 Agent", skills)
    return _make


@pytest.fixture
def echo_server(ch13_07, make_card):
    """构造一个执行函数为 echo 的 A2AServer"""
    return ch13_07.A2AServer(make_card(), lambda payload, meta: f"ECHO:{payload}")


# ============================================================
# 1. 协议常量
# ============================================================

def test_a2a_error_codes(ch13_07):
    """A2A 复用 JSON-RPC 错误码 + 特有 TASK_NOT_FOUND"""
    assert ch13_07.METHOD_NOT_FOUND == -32601
    assert ch13_07.INVALID_PARAMS == -32602
    assert ch13_07.INTERNAL_ERROR == -32603
    assert ch13_07.TASK_NOT_FOUND == -32001


def test_protocol_version_constant(ch13_07):
    """必须声明 A2A 协议版本"""
    assert isinstance(ch13_07.A2A_PROTOCOL_VERSION, str)
    assert ch13_07.A2A_PROTOCOL_VERSION


# ============================================================
# 2. AgentCard
# ============================================================

def test_agent_card_as_dict_fields(ch13_07, make_card):
    """卡片导出必须含六个规范字段"""
    card = make_card("my-agent")
    d = card.as_dict()
    assert set(d.keys()) == {"name", "description", "url", "version",
                             "protocolVersion", "skills"}
    assert d["name"] == "my-agent"
    assert d["protocolVersion"] == ch13_07.A2A_PROTOCOL_VERSION


def test_agent_card_skills_normalized(ch13_07, make_card):
    """skills 必须归一化出 id/name/description/tags 四字段"""
    card = make_card(skills=[{"id": "s1", "name": "n", "description": "d", "tags": ["a"]}])
    skill = card.as_dict()["skills"][0]
    assert set(skill.keys()) == {"id", "name", "description", "tags"}
    assert skill["tags"] == ["a"]


def test_agent_card_tags_copied_not_shared(ch13_07, make_card):
    """标签列表应是副本（防止外部修改污染卡片内部状态）"""
    tags = ["original"]
    card = make_card(skills=[{"id": "s1", "name": "n", "description": "d", "tags": tags}])
    tags.append("mutated")
    assert "mutated" not in card.skills[0]["tags"]


# ============================================================
# 3. A2AMessage
# ============================================================

def test_message_to_a2a_message_text_only(ch13_07):
    """无 metadata：parts 只含 TextPart"""
    msg = ch13_07.A2AMessage("alice", "bob", "你好")
    out = msg.to_a2a_message()
    assert out["role"] == "user"
    assert "messageId" in out
    assert len(out["parts"]) == 1
    assert out["parts"][0] == {"kind": "text", "text": "你好"}


def test_message_to_a2a_message_with_metadata(ch13_07):
    """有 metadata：parts 追加 DataPart"""
    msg = ch13_07.A2AMessage("alice", "bob", "执行", metadata={"task_type": "tool"})
    out = msg.to_a2a_message()
    assert len(out["parts"]) == 2
    assert out["parts"][1]["kind"] == "data"
    assert out["parts"][1]["data"]["task_type"] == "tool"
    assert out["metadata"] == {"task_type": "tool"}


def test_message_id_is_uuid(ch13_07):
    """messageId 应为 uuid（长度 36）"""
    msg = ch13_07.A2AMessage("a", "b", "x")
    assert len(msg.message_id) == 36


def test_message_two_instances_distinct_ids(ch13_07):
    """两条消息不应共享 messageId"""
    assert ch13_07.A2AMessage("a", "b", "x").message_id != \
        ch13_07.A2AMessage("a", "b", "x").message_id


def test_message_to_dict_router_view(ch13_07):
    """to_dict 保留教材网关路由视图（sender/receiver）"""
    msg = ch13_07.A2AMessage("alice", "bob", "payload")
    d = msg.to_dict()
    assert d["sender"] == "alice" and d["receiver"] == "bob"
    assert d["payload"] == "payload"


# ============================================================
# 4. A2AServer 协议层（纯 dict）
# ============================================================

def test_server_get_agent_card(ch13_07, echo_server):
    """Agent Card 发现入口返回卡片字典"""
    card = echo_server.get_agent_card()
    assert "name" in card and "skills" in card


def test_server_notification_returns_none(ch13_07, echo_server):
    """通知不产生响应"""
    assert echo_server.handle({"jsonrpc": "2.0",
                               "method": "notifications/cancel"}) is None


def test_server_unknown_method(ch13_07, echo_server):
    """未知方法 → METHOD_NOT_FOUND"""
    resp = echo_server.handle({"jsonrpc": "2.0", "id": 1, "method": "bad/method"})
    assert resp["error"]["code"] == ch13_07.METHOD_NOT_FOUND


def test_message_send_creates_task(ch13_07, echo_server):
    """message/send 应执行技能并返回 Task 结构"""
    resp = echo_server.handle({
        "jsonrpc": "2.0", "id": 1, "method": "message/send",
        "params": {"message": {"role": "user",
                               "parts": [{"kind": "text", "text": "hello"}]}}})
    result = resp["result"]
    assert "id" in result                      # task id
    assert "status" in result or "artifact" in result or "artifacts" in result


def test_message_send_executes_skill(ch13_07, echo_server):
    """执行函数应被真实调用（echo 内容应出现在返回中）"""
    resp = echo_server.handle({
        "jsonrpc": "2.0", "id": 1, "method": "message/send",
        "params": {"message": {"role": "user",
                               "parts": [{"kind": "text", "text": "PING"}]}}})
    assert "PING" in str(resp["result"])


def test_tasks_get_unknown_task(ch13_07, echo_server):
    """查询不存在的 task → TASK_NOT_FOUND（A2A 特有错误码）"""
    resp = echo_server.handle({"jsonrpc": "2.0", "id": 1, "method": "tasks/get",
                               "params": {"id": "no-such-task"}})
    assert resp["error"]["code"] == ch13_07.TASK_NOT_FOUND


def test_task_id_queryable_after_send(ch13_07, echo_server):
    """message/send 产生的 task 应能被 tasks/get 查到"""
    send = echo_server.handle({
        "jsonrpc": "2.0", "id": 1, "method": "message/send",
        "params": {"message": {"role": "user", "parts": [{"kind": "text", "text": "hi"}]}}})
    task_id = send["result"]["id"]
    got = echo_server.handle({"jsonrpc": "2.0", "id": 2, "method": "tasks/get",
                              "params": {"id": task_id}})
    assert "result" in got
    assert got["result"]["id"] == task_id


# ============================================================
# 5. A2ARouter —— 能力发现
# ============================================================

def test_router_register_and_find(ch13_07, make_card):
    """注册后按 skill_tag 应能发现 Agent"""
    router = ch13_07.A2ARouter()
    srv = ch13_07.A2AServer(
        make_card("qa-agent", skills=[{"id": "s", "name": "问答",
                                       "description": "d", "tags": ["qa", "chat"]}]),
        lambda p, m: "ok")
    router.register_agent(srv)
    found = router.find_agent("qa")
    assert found is not None


def test_router_find_missing_tag(ch13_07):
    """不存在的标签应返回 None（而非抛异常）"""
    assert ch13_07.A2ARouter().find_agent("no-such-tag") is None


def test_build_agents_returns_servers(ch13_07):
    """build_agents 应返回 A2AServer 列表"""
    agents = ch13_07.build_agents()
    assert isinstance(agents, list) and len(agents) >= 1
    for a in agents:
        assert isinstance(a, ch13_07.A2AServer)
