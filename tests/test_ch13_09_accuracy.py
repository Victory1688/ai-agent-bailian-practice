"""
test_ch13_09_accuracy.py —— chapter13 / 09 Test 工具调用正确率测试框架

【TDD 定位】被测文件：chapter13/09_Test工具调用正确率测试框架.py
【测试策略】三个比对函数 + 测试集结构 = 纯函数，全量断言（这是教材"死逻辑"的修复验证）；
            真实正确率测量 = @pytest.mark.live @pytest.mark.slow

【本篇要守住的契约】（来自源码逐行核对，非臆造）
  - TEST_CASES 每条含 id/input/expected_tools/expected_params/expected_result_pat
  - _extract_actual_tools 从 steps 提取工具名序列
  - _check_tool_name：序列完全一致才 True；预期非空但实际空 → False
  - _check_params：expected_params=None 跳过；缺字段或值不符 → False
  - _check_result_pattern：expected_result_pat=None 跳过；re.search 匹配
  - run_tool_test 返回结构化 metrics（含 tool_name_rate/param_rate/return_rate/overall）
  - 教材原始 bug 修复：不再用 "工具名 in 自然语言回复" 判定（正确率永远 0%）

【本文件是整个 TDD 体系的关键】——教材 13-09 的测试逻辑本身是坏的，
这里用 TDD 把"测试框架的测试"也补上，防止修复退化。
"""

import pytest

pytestmark = pytest.mark.usefixtures("ch13_09")


# ============================================================
# 1. 测试集结构契约
# ============================================================

def test_test_cases_structure(ch13_09):
    """每条用例必须含五项字段（三项契约各有对位点）"""
    assert isinstance(ch13_09.TEST_CASES, list) and len(ch13_09.TEST_CASES) >= 5
    for case in ch13_09.TEST_CASES:
        assert set(case.keys()) == {"id", "input", "expected_tools",
                                    "expected_params", "expected_result_pat"}
        assert isinstance(case["expected_tools"], list)


def test_test_case_ids_unique(ch13_09):
    """用例 id 必须唯一（结果可追溯）"""
    ids = [c["id"] for c in ch13_09.TEST_CASES]
    assert len(ids) == len(set(ids))


def test_expected_tools_are_registered(ch13_09):
    """用例期望的工具名必须在被测系统的工具注册表中"""
    names = {s["function"]["name"] for s in ch13_09.TOOLS_SPEC}
    for case in ch13_09.TEST_CASES:
        for t in case["expected_tools"]:
            assert t in names, f"{case['id']} 期望未注册工具 {t}"


# ============================================================
# 2. _extract_actual_tools
# ============================================================

def test_extract_actual_tools_empty(ch13_09):
    """空 steps → 空列表（LLM 直答场景）"""
    assert ch13_09._extract_actual_tools([]) == []


def test_extract_actual_tools_sequence(ch13_09):
    """按顺序提取工具名"""
    steps = [{"tool": "get_temperature"}, {"tool": "multiply"}]
    assert ch13_09._extract_actual_tools(steps) == ["get_temperature", "multiply"]


# ============================================================
# 3. _check_tool_name —— 教材核心 bug 的修复验证
# ============================================================

def test_check_tool_name_exact_match(ch13_09):
    """序列完全一致 → True"""
    assert ch13_09._check_tool_name(["multiply"], ["multiply"]) is True
    assert ch13_09._check_tool_name(["a", "b"], ["a", "b"]) is True


def test_check_tool_name_both_empty(ch13_09):
    """预期空 + 实际空 → True（LLM 直答也符合预期时）"""
    assert ch13_09._check_tool_name([], []) is True


def test_check_tool_name_expected_but_direct_answer(ch13_09):
    """期望调工具但 LLM 直答 → False（这是教材无法检测的场景）"""
    assert ch13_09._check_tool_name(["multiply"], []) is False


def test_check_tool_name_wrong_tool(ch13_09):
    """调错工具 → False"""
    assert ch13_09._check_tool_name(["multiply"], ["get_temperature"]) is False


def test_check_tool_name_order_matters(ch13_09):
    """顺序不同 → False（多工具场景顺序敏感）"""
    assert ch13_09._check_tool_name(["a", "b"], ["b", "a"]) is False


def test_check_tool_name_extra_call(ch13_09):
    """多调了工具 → False（严格序列比对）"""
    assert ch13_09._check_tool_name(["multiply"], ["multiply", "multiply"]) is False


# ============================================================
# 4. _check_params
# ============================================================

def test_check_params_skip_when_none(ch13_09):
    """expected_params=None → 跳过（返回 True）"""
    assert ch13_09._check_params([], None) is True


def test_check_params_match(ch13_09):
    """参数字段与值均匹配 → True"""
    steps = [{"args": {"city": "北京"}}]
    assert ch13_09._check_params(steps, {"city": "北京"}) is True


def test_check_params_missing_key(ch13_09):
    """缺少必需字段 → False"""
    steps = [{"args": {"wrong": "x"}}]
    assert ch13_09._check_params(steps, {"city": "北京"}) is False


def test_check_params_wrong_value(ch13_09):
    """值不符 → False"""
    steps = [{"args": {"city": "上海"}}]
    assert ch13_09._check_params(steps, {"city": "北京"}) is False


def test_check_params_empty_steps_with_expectation(ch13_09):
    """期望参数但无工具调用 → False"""
    assert ch13_09._check_params([], {"city": "北京"}) is False


def test_check_params_subset_match(ch13_09):
    """只校验期望字段（实际参数可有额外字段）"""
    steps = [{"args": {"city": "北京", "extra": "允许"}}]
    assert ch13_09._check_params(steps, {"city": "北京"}) is True


# ============================================================
# 5. _check_result_pattern
# ============================================================

def test_check_result_pattern_skip_when_none(ch13_09):
    """expected_result_pat=None → 跳过"""
    assert ch13_09._check_result_pattern([], None) is True


def test_check_result_pattern_match(ch13_09):
    """正则命中 → True"""
    steps = [{"result": "北京当前温度为26°C"}]
    assert ch13_09._check_result_pattern(steps, r"北京.*温度") is True


def test_check_result_pattern_no_match(ch13_09):
    """正则未命中 → False"""
    steps = [{"result": "上海当前温度为26°C"}]
    assert ch13_09._check_result_pattern(steps, r"北京.*温度") is False


def test_check_result_pattern_any_step_matches(ch13_09):
    """多步中任一步命中即 True"""
    steps = [{"result": "无关"}, {"result": "北京温度26"}]
    assert ch13_09._check_result_pattern(steps, r"北京.*温度") is True


def test_check_result_pattern_empty_steps(ch13_09):
    """期望匹配但无工具调用 → False"""
    assert ch13_09._check_result_pattern([], r"北京") is False


# ============================================================
# 6. metrics 契约
# ============================================================

def test_run_tool_test_metrics_shape(ch13_09):
    """run_tool_test 返回结构化 metrics（含七字段）"""
    metrics = ch13_09.run_tool_test("qwen-plus")
    assert set(metrics.keys()) == {"model", "total_cases", "tool_name_rate",
                                   "param_rate", "return_rate", "details", "overall"}
    assert metrics["total_cases"] == len(ch13_09.TEST_CASES)
    assert len(metrics["details"]) == len(ch13_09.TEST_CASES)


def test_metrics_rates_in_range(ch13_09):
    """三项指标与综合值均应在 [0, 1]"""
    m = ch13_09.run_tool_test("qwen-plus")
    for key in ("tool_name_rate", "param_rate", "return_rate", "overall"):
        assert 0.0 <= m[key] <= 1.0


def test_metrics_detail_fields(ch13_09):
    """每条明细应含三项判定布尔值（可分项追溯）"""
    m = ch13_09.run_tool_test("qwen-plus")
    for d in m["details"]:
        assert isinstance(d["tool_ok"], bool)
        assert isinstance(d["param_ok"], bool)
        assert isinstance(d["return_ok"], bool)


def test_registry_restored_after_test(ch13_09):
    """测试完成后 MODEL_REGISTRY 必须还原（否则污染后续测试）"""
    before = ch13_09.MODEL_REGISTRY["primary"]["model"]
    ch13_09.run_tool_test("qwen-turbo")
    assert ch13_09.MODEL_REGISTRY["primary"]["model"] == before


def test_rates_not_all_zero(ch13_09):
    """修复验证：正确率不应恒为 0（教材 bug 的终极证据）

    教材原逻辑用 "expected_tool in 自然语言回复" 判定，工具名永不出现
    在回复里，正确率永远 0%。改写后从 steps 轨迹结构化比对，应 > 0。
    """
    m = ch13_09.run_tool_test("qwen-plus")
    assert m["overall"] > 0, "正确率恒为 0 —— 教材死逻辑未被修复"
