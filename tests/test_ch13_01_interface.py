"""
test_ch13_01_interface.py —— chapter13 / 01 标准 Agent 接口层和数据结构

【TDD 定位】被测文件：chapter13/01_先定义标准的Agent接口层和数据结构.py
【测试策略】纯函数/结构契约 = 确定性断言；LLM 调用 = 真实调用（@pytest.mark.live）

【本篇要守住的契约】（来自源码逐行核对，非臆造）
  - Message 构造时即校验 role（fail fast），非法 role 抛 ValueError
  - Message.to_dict() 输出 {"role", "content"} 两字段
  - ConversationContext.session_id 默认 uuid4（长度 36）
  - ConversationContext.as_dict() 输出原生 messages 列表
  - ModelAdapter 未注册类型抛 ValueError（注册表驱动）
  - get_adapter() 适配器池：同类型返回同一实例（修复教材"每轮 new"）
  - ModelAdapter.call() 错误不泄漏 traceback（堆栈止于日志）
"""

import uuid
import pytest

pytestmark = pytest.mark.usefixtures("ch13_01")


# ============================================================
# 1. Message —— 构造期校验（fail fast）
# ============================================================

@pytest.mark.parametrize("role", ["user", "assistant", "system"])
def test_message_accepts_valid_roles(ch13_01, role):
    """白名单内的三种 role 均应构造成功"""
    msg = ch13_01.Message(role, "内容")
    assert msg.role == role
    assert msg.content == "内容"


@pytest.mark.parametrize("bad_role", ["robot", "USER", "", None, "human", "ai"])
def test_message_rejects_invalid_role_at_construction(ch13_01, bad_role):
    """非法 role 必须在【构造时】抛 ValueError —— 教材原版延迟到 to_langchain() 才报错

    这是本文件最重要的一条契约：坏数据不进容器（fail fast）。
    注意 "USER"（大写）也应被拒绝 —— 白名单是精确匹配。
    """
    with pytest.raises(ValueError) as exc:
        ch13_01.Message(bad_role, "内容")
    assert "role" in str(exc.value).lower() or "角色" in str(exc.value)


def test_message_to_dict_two_fields_only(ch13_01):
    """to_dict 必须且只能输出 role / content 两个字段"""
    d = ch13_01.Message("user", "你好").to_dict()
    assert d == {"role": "user", "content": "你好"}
    assert set(d.keys()) == {"role", "content"}


# ============================================================
# 2. ConversationContext —— 容器结构契约
# ============================================================

def test_context_session_id_is_uuid(ch13_01):
    """缺省 session_id 应为 uuid4（长度 36，含 4 个连字符）"""
    ctx = ch13_01.ConversationContext()
    assert len(ctx.session_id) == 36
    assert ctx.session_id.count("-") == 4
    uuid.UUID(ctx.session_id)          # 能被解析 = 合法 uuid


def test_context_accepts_explicit_session_id(ch13_01):
    """显式传入的 session_id 应被原样保留（不覆盖）"""
    ctx = ch13_01.ConversationContext(session_id="my-session-42")
    assert ctx.session_id == "my-session-42"


def test_context_two_instances_have_distinct_ids(ch13_01):
    """两个缺省上下文不应共享 session_id"""
    assert ch13_01.ConversationContext().session_id != ch13_01.ConversationContext().session_id


def test_context_add_message_returns_message_and_appends(ch13_01):
    """add_message 应返回新建 Message 且追加到 messages"""
    ctx = ch13_01.ConversationContext()
    msg = ctx.add_message("system", "你是助手")
    assert isinstance(msg, ch13_01.Message)
    assert len(ctx.messages) == 1


def test_context_add_message_propagates_validation(ch13_01):
    """add_message 的校验委托给 Message —— 非法 role 同样抛 ValueError"""
    ctx = ch13_01.ConversationContext()
    with pytest.raises(ValueError):
        ctx.add_message("robot", "坏角色")
    # 关键：校验失败后不应留下脏数据
    assert len(ctx.messages) == 0


def test_context_as_dict_order_preserved(ch13_01):
    """as_dict 输出顺序必须与添加顺序一致（多轮对话语义依赖顺序）"""
    ctx = ch13_01.ConversationContext()
    ctx.add_message("system", "系统提示")
    ctx.add_message("user", "第一问")
    ctx.add_message("assistant", "第一答")
    data = ctx.as_dict()
    assert [m["role"] for m in data] == ["system", "user", "assistant"]
    assert data[0] == {"role": "system", "content": "系统提示"}


def test_context_empty_as_dict(ch13_01):
    """空上下文 as_dict 应返回空列表（而非 None）"""
    assert ch13_01.ConversationContext().as_dict() == []


# ============================================================
# 3. ModelAdapter —— 注册表驱动 + 实例池
# ============================================================

def test_adapter_rejects_unregistered_type(ch13_01):
    """未注册模型类型必须抛 ValueError（注册表是唯一入口）"""
    for bad in ("gpt-5", "", "qwen3", "QWEN"):
        with pytest.raises(ValueError):
            ch13_01.ModelAdapter(bad)


def test_adapter_reads_registry_fields(ch13_01):
    """适配器字段应从 MODEL_REGISTRY 读出，不硬编码"""
    a = ch13_01.ModelAdapter("qwen")
    spec = ch13_01.MODEL_REGISTRY["qwen"]
    assert a.model_type == "qwen"
    assert a.model_name == spec["model"]
    assert a.protocol == spec["protocol"]


def test_adapter_construction_is_side_effect_free(ch13_01):
    """构造适配器不应发起网络调用（教材原版构造即加载大模型是反模式）"""
    for t in ch13_01.MODEL_REGISTRY:
        ch13_01.ModelAdapter(t)        # 不抛异常 = 未触网


def test_adapter_pool_returns_same_instance(ch13_01):
    """get_adapter 同类型必须返回同一实例（教材"每轮 new"问题的修复验证）"""
    a1 = ch13_01.get_adapter("qwen")
    a2 = ch13_01.get_adapter("qwen")
    assert a1 is a2, "适配器池未生效 —— 同类型返回了不同实例"


def test_adapter_pool_distinct_types(ch13_01):
    """不同类型的适配器必须是不同实例"""
    assert ch13_01.get_adapter("qwen") is not ch13_01.get_adapter("deepseek")


# ============================================================
# 4. call() 契约 —— 错误不泄漏堆栈（真实 API）
# ============================================================

@pytest.mark.live
def test_call_success_contract(ch13_01):
    """真实调用：成功时返回 {success, model, response}，且不含 traceback 键"""
    ctx = ch13_01.ConversationContext()
    ctx.add_message("system", "你是一个专业的AI助手")
    ctx.add_message("user", "请用一句话解释什么是注意力机制")
    result = ch13_01.get_adapter("qwen").call(ctx)
    assert result["success"] is True, result.get("error")
    assert result["model"] == "qwen-plus"
    assert isinstance(result["response"], str) and result["response"].strip()
    assert "traceback" not in result, "堆栈泄漏 —— 违反教材⑥的修复承诺"


@pytest.mark.live
def test_cross_model_shared_context(ch13_01):
    """跨适配器共享上下文：第二问的'它'应能指代第一问的话题"""
    ctx = ch13_01.ConversationContext()
    ctx.add_message("system", "你是一个专业的AI助手")
    ctx.add_message("user", "请用一句话解释什么是注意力机制")
    r1 = ch13_01.get_adapter("qwen").call(ctx)
    assert r1["success"], r1.get("error")
    ctx.add_message("assistant", r1["response"])
    ctx.add_message("user", "它和多头注意力有什么关系？")
    r2 = ch13_01.get_adapter("deepseek").call(ctx)
    assert r2["success"], r2.get("error")
    assert any(kw in r2["response"] for kw in ("注意力", "多头")), \
        f"上下文未跨适配器共享: {r2['response'][:80]}"


@pytest.mark.live
def test_call_returns_error_dict_on_failure(ch13_01):
    """失败路径：call 不应抛异常，而应返回 {success: False, error}"""
    import dashscope
    original = dashscope.api_key
    try:
        dashscope.api_key = "sk-invalid-key-for-test"
        # 重新构造适配器（池中实例不受影响，这里直接 new）
        adapter = ch13_01.ModelAdapter("qwen")
        ctx = ch13_01.ConversationContext()
        ctx.add_message("user", "测试")
        result = adapter.call(ctx)
        assert result["success"] is False
        assert "error" in result
        assert "traceback" not in result
    finally:
        dashscope.api_key = original
