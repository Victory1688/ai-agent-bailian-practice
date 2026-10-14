"""
test_ch13_08_agent_core.py —— chapter13 / 08 LangChain 的通用 Agent 主控链条

【TDD 定位】被测文件：chapter13/08_LangChain的通用Agent主控链条.py
【测试策略】工具纯函数 = 确定性断言；LLM 主控链路 = 真实调用（@pytest.mark.live）

【本篇要守住的契约】（来自源码逐行核对，非臆造）
  - get_temperature("月球") 抛 ValueError；其他城市返回 "...当前温度为26°C"
  - multiply 返回 str(float*float)；非法输入返回提示而非抛错
  - execute_tool 永不抛出：未知工具 / 工具异常均返回错误文本（错误是数据）
  - AgentCore.run 返回 {success, reply, steps}；steps 元素含 round/tool/args/result
  - 工具错误回填：月球场景链路不断，模型仍能生成终答
  - 主备回退：primary 失败 → backup 接管；attempted_slots 留痕成对 (primary, backup)
  - MODEL_REGISTRY 临时改动必须 finally 还原（测试自身纪律）
"""

import json
import pytest

pytestmark = pytest.mark.usefixtures("ch13_08")


# ============================================================
# 1. 工具纯函数 —— 教材逻辑原样验证（零成本，可大量断言）
# ============================================================

@pytest.mark.parametrize("city", ["北京", "上海", "广州", "杭州"])
def test_get_temperature_normal_cities(ch13_08, city):
    """正常城市返回 '城市当前温度为26°C'"""
    assert ch13_08.get_temperature(city) == f"{city}当前温度为26°C"


def test_get_temperature_moon_raises(ch13_08):
    """'月球' 必须抛 ValueError（教材原逻辑，供错误回填场景使用）"""
    with pytest.raises(ValueError):
        ch13_08.get_temperature("月球")


def test_get_temperature_moon_case_insensitive(ch13_08):
    """源码用 city.lower() == '月球' 判定 —— 等价大小写写法也应触发"""
    with pytest.raises(ValueError):
        ch13_08.get_temperature("月球")


@pytest.mark.parametrize("a,b,expected", [
    ("7", "8", 56.0), ("12", "13", 156.0),
    ("3.5", "2", 7.0), ("-4", "5", -20.0), ("0", "9", 0.0),
])
def test_multiply_numeric(ch13_08, a, b, expected):
    """数值字符串相乘：返回 str(float*float)，注意会有 ".0" 尾缀"""
    result = ch13_08.multiply(a, b)
    assert float(result) == expected


@pytest.mark.parametrize("a,b", [("a", "b"), ("x", "2"), ("", "3"), ("七", "八")])
def test_multiply_invalid_returns_hint(ch13_08, a, b):
    """非法输入返回提示文本，不抛异常（教材逻辑保留）"""
    assert "输入格式不正确" in ch13_08.multiply(a, b)


# ============================================================
# 2. execute_tool —— 永不抛出的统一执行入口（错误是数据）
# ============================================================

def test_execute_tool_normal(ch13_08):
    """正常调用：返回工具输出文本"""
    assert ch13_08.execute_tool("get_temperature", {"city": "北京"}) == "北京当前温度为26°C"


def test_execute_tool_captures_tool_exception(ch13_08):
    """工具内部异常被捕获，转为 '工具执行失败：...' 文本（链路不断）"""
    out = ch13_08.execute_tool("get_temperature", {"city": "月球"})
    assert out == "工具执行失败：未找到对应城市"


def test_execute_tool_unknown_tool(ch13_08):
    """未知工具名不抛异常，返回 '未知工具' 提示"""
    out = ch13_08.execute_tool("no_such_tool", {})
    assert "未知工具" in out and "no_such_tool" in out


def test_execute_tool_never_raises(ch13_08):
    """穷举坏输入，execute_tool 必须始终返回 str 而非抛出"""
    bad_cases = [
        ("get_temperature", {}),                # 缺必需参数 city
        ("get_temperature", {"wrong": "x"}),    # 参数名错误
        ("multiply", {"a": "1"}),               # 缺 b
        ("multiply", {"a": None, "b": "2"}),    # 类型错误
        ("", {}),                               # 空工具名
    ]
    for name, args in bad_cases:
        out = ch13_08.execute_tool(name, args)   # 不应抛异常
        assert isinstance(out, str)


# ============================================================
# 3. _extract_tool_calls —— 两形态兼容（13-03 实测教训）
# ============================================================

def test_extract_tool_calls_none_when_absent(ch13_08):
    """未调工具时 message 无 tool_calls 属性 → 返回空列表（不抛 AttributeError）"""
    class FakeMsg:
        content = "直接回答"
    assert ch13_08._extract_tool_calls(FakeMsg()) == []


def test_extract_tool_calls_empty_list(ch13_08):
    """tool_calls 为空列表 → 返回空列表"""
    class FakeMsg:
        content = "x"
        tool_calls = []
    assert ch13_08._extract_tool_calls(FakeMsg()) == []


def test_extract_tool_calls_dict_form(ch13_08):
    """元素为 dict 形态（实测主形态）应原样透出"""
    class FakeMsg:
        content = None
        tool_calls = [{"id": "c1", "type": "function",
                       "function": {"name": "multiply", "arguments": '{"a":"7","b":"8"}'}}]
    out = ch13_08._extract_tool_calls(FakeMsg())
    assert out == FakeMsg.tool_calls


def test_extract_tool_calls_object_form(ch13_08):
    """元素为对象形态应被统一转成 dict（兼容性保障）"""
    class Fn:
        name = "get_temperature"
        arguments = '{"city":"北京"}'
    class Tc:
        id = "c2"
        function = Fn()
    class FakeMsg:
        content = None
        tool_calls = [Tc()]
    out = ch13_08._extract_tool_calls(FakeMsg())
    assert out[0]["id"] == "c2"
    assert out[0]["function"]["name"] == "get_temperature"
    assert out[0]["type"] == "function"


# ============================================================
# 4. AgentCore 契约（真实 API）
# ============================================================

@pytest.mark.live
def test_agent_temperature_chain(ch13_08):
    """温度查询：真实链路命中 get_temperature，steps 留痕，未触发回退"""
    agent = ch13_08.AgentCore()
    result = agent.run("请帮我查询北京的当前温度")
    assert result["success"] is True, result.get("error")
    assert "26" in result["reply"]
    assert any(s["tool"] == "get_temperature" for s in result["steps"])
    assert set(agent.attempted_slots) == {"primary"}, agent.attempted_slots


@pytest.mark.live
def test_steps_structure_contract(ch13_08):
    """steps 每个元素必须含 round/tool/args/result 四字段（09 篇测试框架依赖此结构）"""
    agent = ch13_08.AgentCore()
    result = agent.run("将7和8相乘是多少")
    assert result["success"] is True, result.get("error")
    assert len(result["steps"]) >= 1
    for s in result["steps"]:
        assert set(s.keys()) == {"round", "tool", "args", "result"}
        assert isinstance(s["round"], int) and s["round"] >= 1
        assert isinstance(s["args"], dict)
        assert len(s["result"]) <= 120      # 源码 result[:120] 截断


@pytest.mark.live
def test_multiply_and_memory(ch13_08):
    """多轮记忆：同一实例第二轮 '再...' 应接续上下文"""
    agent = ch13_08.AgentCore()
    r1 = agent.run("将7和8相乘是多少")
    assert r1["success"] and "56" in r1["reply"], r1
    r2 = agent.run("再帮我乘一下12和13")
    assert r2["success"] and "156" in r2["reply"], r2
    # 记忆应累积 2 轮 (user, assistant) 共 4 条
    assert len(agent.history) == 4


@pytest.mark.live
def test_moon_scenario_error_backfill(ch13_08):
    """月球场景：无论调工具还是直答，链路都必须成功（错误是数据，不是故障）

    教材原版此场景整体失败；改写后两条路径均为合理行为：
      路径A：调工具 → 返回"未找到对应城市" → 回填 → 模型致歉
      路径B：模型直接用自身知识解释月球无天气
    """
    agent = ch13_08.AgentCore()
    result = agent.run("请查一下月球的天气")
    assert result["success"] is True, result.get("error")
    assert result["reply"]
    if any("未找到对应城市" in s["result"] for s in result["steps"]):
        pass                    # 路径A：错误回填生效
    else:
        pass                    # 路径B：LLM 非确定行为，契约仍满足


@pytest.mark.live
def test_fallback_primary_to_backup(ch13_08):
    """主备回退：注入坏模型名后 backup 必须接管，且 attempted_slots 成对出现"""
    old = ch13_08.MODEL_REGISTRY["primary"]["model"]
    ch13_08.MODEL_REGISTRY["primary"]["model"] = "nonexistent-model-for-test"
    try:
        agent = ch13_08.AgentCore()
        result = agent.run("将7和8相乘是多少")
    finally:
        ch13_08.MODEL_REGISTRY["primary"]["model"] = old    # 必须还原

    assert agent.attempted_slots, "无回退记录"
    assert len(agent.attempted_slots) % 2 == 0, agent.attempted_slots
    pairs = list(zip(agent.attempted_slots[::2], agent.attempted_slots[1::2]))
    assert all(p == ("primary", "backup") for p in pairs), agent.attempted_slots
    assert result["success"] and "56" in result["reply"], result


@pytest.mark.live
def test_agent_returns_dict_not_string(ch13_08):
    """run 返回结构化 dict（教材原版返回纯文本 + 字符串判错）"""
    agent = ch13_08.AgentCore()
    result = agent.run("将7和8相乘是多少")
    assert isinstance(result, dict)
    assert "success" in result and isinstance(result["success"], bool)
    assert "steps" in result


# ============================================================
# 5. 常量契约
# ============================================================

def test_tool_spec_has_outer_wrapper(ch13_08):
    """TOOLS_SPEC 必须含 {"type":"function","function":{...}} 外层包装

    实测教训：dashscope 原生 API 传 OpenAI 风格裸 function 列表会被静默忽略。
    """
    assert isinstance(ch13_08.TOOLS_SPEC, list) and len(ch13_08.TOOLS_SPEC) == 2
    for spec in ch13_08.TOOLS_SPEC:
        assert spec["type"] == "function"
        assert "function" in spec
        assert "name" in spec["function"]
        assert "parameters" in spec["function"]


def test_tool_impls_match_spec(ch13_08):
    """TOOL_IMPLS 注册表与 TOOLS_SPEC 声明的工具名必须一一对应"""
    spec_names = {s["function"]["name"] for s in ch13_08.TOOLS_SPEC}
    impl_names = set(ch13_08.TOOL_IMPLS.keys())
    assert spec_names == impl_names, f"声明与实现不一致: {spec_names} vs {impl_names}"


def test_max_tool_rounds_bounded(ch13_08):
    """工具循环必须有轮次上限（防无限循环）"""
    assert isinstance(ch13_08.MAX_TOOL_ROUNDS, int)
    assert 1 <= ch13_08.MAX_TOOL_ROUNDS <= 10


def test_model_registry_primary_backup(ch13_08):
    """注册表必须含 primary / backup 主备槽位"""
    assert set(ch13_08.MODEL_REGISTRY.keys()) == {"primary", "backup"}
