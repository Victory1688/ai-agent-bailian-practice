"""
test_ch13_10_metrics.py —— chapter13 / 10 Test 多用户并发测试与系统压测

【TDD 定位】被测文件：chapter13/10_Test多用户并发测试与系统压测.py
【测试策略】_percentile / compute_metrics / _detect_cross_talk = 纯函数，全量断言；
            并发压测真实调用 = @pytest.mark.live @pytest.mark.slow

【本篇要守住的契约】（来自源码逐行核对，非臆造）
  - _percentile 线性插值（与 numpy.percentile 默认语义一致）
  - compute_metrics 输出 9 个指标字段；error_rate = failed/total
  - _detect_cross_talk：天气问题→需 get_temperature；数学问题→需 multiply
  - run_single_request 返回结构化 dict，success 为 bool（非字符串匹配）
  - RANDOM_SEED 固定 → 任务分配可复现
"""

import pytest

pytestmark = pytest.mark.usefixtures("ch13_10")


# ============================================================
# 1. _percentile —— 线性插值（纯数学）
# ============================================================

def test_percentile_median(ch13_10):
    """P50 中位数：奇数个取中间，偶数个取两中间值平均"""
    assert ch13_10._percentile([1, 2, 3], 0.5) == 2
    assert ch13_10._percentile([1, 2, 3, 4], 0.5) == 2.5


def test_percentile_endpoints(ch13_10):
    """P0 = 最小值，P100 = 最大值"""
    vals = [10, 20, 30, 40, 50]
    assert ch13_10._percentile(vals, 0.0) == 10
    assert ch13_10._percentile(vals, 1.0) == 50


def test_percentile_single_element(ch13_10):
    """单元素列表任何分位都返回该元素"""
    for p in (0.0, 0.5, 0.95, 1.0):
        assert ch13_10._percentile([42], p) == 42


def test_percentile_interpolation(ch13_10):
    """插值：两元素间按小数部分加权"""
    # pos = 0.95 * (2-1) = 0.95 → 在 vals[0] 与 vals[1] 间插值
    assert ch13_10._percentile([0, 100], 0.95) == pytest.approx(95.0)


def test_percentile_monotonic(ch13_10):
    """分位越大，值不应减小（单调性）"""
    vals = list(range(100))
    assert ch13_10._percentile(vals, 0.5) <= ch13_10._percentile(vals, 0.95)


# ============================================================
# 2. compute_metrics —— 指标计算
# ============================================================

def test_metrics_all_success(ch13_10):
    """全成功：错误率 0，成功数 = 总数"""
    results = [{"success": True, "duration": d} for d in (1.0, 2.0, 3.0)]
    m = ch13_10.compute_metrics(results, total_time=3.0)
    assert m["total"] == 3
    assert m["success_count"] == 3
    assert m["failed_count"] == 0
    assert m["error_rate"] == 0.0


def test_metrics_with_failures(ch13_10):
    """含失败：error_rate = failed/total"""
    results = [{"success": True, "duration": 1.0},
               {"success": False, "duration": 2.0},
               {"success": False, "duration": 3.0}]
    m = ch13_10.compute_metrics(results, total_time=4.0)
    assert m["success_count"] == 1
    assert m["failed_count"] == 2
    assert m["error_rate"] == pytest.approx(2 / 3)


def test_metrics_output_fields(ch13_10):
    """指标字典必须含全部 9 个字段"""
    results = [{"success": True, "duration": 1.5}]
    m = ch13_10.compute_metrics(results, total_time=2.0)
    assert set(m.keys()) == {"total", "success_count", "failed_count", "error_rate",
                             "avg_time", "p50_time", "p95_time", "max_time", "qps"}


def test_metrics_qps(ch13_10):
    """QPS = 请求数 / 总耗时"""
    results = [{"success": True, "duration": 1.0} for _ in range(10)]
    m = ch13_10.compute_metrics(results, total_time=5.0)
    assert m["qps"] == pytest.approx(2.0)


def test_metrics_avg_and_max(ch13_10):
    """平均耗时与最大耗时应正确"""
    results = [{"success": True, "duration": d} for d in (1.0, 2.0, 6.0)]
    m = ch13_10.compute_metrics(results, total_time=3.0)
    assert m["avg_time"] == pytest.approx(3.0)
    assert m["max_time"] == 6.0


def test_metrics_p95_le_max(ch13_10):
    """P95 不应超过最大值（统计合理性）"""
    results = [{"success": True, "duration": float(d)} for d in range(1, 101)]
    m = ch13_10.compute_metrics(results, total_time=10.0)
    assert m["p95_time"] <= m["max_time"]


# ============================================================
# 3. _detect_cross_talk —— 串话检测（教材共享实例 bug 的探测器）
# ============================================================

def test_cross_talk_no_suspects_when_correct(ch13_10):
    """工具调用与输入语义一致 → 无串话"""
    results = [
        {"user_id": 1, "success": True, "input": "北京天气", "tool_hits": ["get_temperature"]},
        {"user_id": 2, "success": True, "input": "计算12乘13", "tool_hits": ["multiply"]},
    ]
    assert ch13_10._detect_cross_talk(results) == []


def test_cross_talk_detects_weather_mismatch(ch13_10):
    """天气问题却调了 multiply → 判定为串话"""
    results = [{"user_id": 1, "success": True, "input": "北京天气怎么样",
                "tool_hits": ["multiply"]}]
    assert 1 in ch13_10._detect_cross_talk(results)


def test_cross_talk_detects_math_mismatch(ch13_10):
    """数学问题却调了 get_temperature → 判定为串话"""
    results = [{"user_id": 5, "success": True, "input": "9乘以7是多少",
                "tool_hits": ["get_temperature"]}]
    assert 5 in ch13_10._detect_cross_talk(results)


def test_cross_talk_skips_failed_requests(ch13_10):
    """失败请求无有效轨迹，不参与串话判定"""
    results = [{"user_id": 1, "success": False, "input": "北京天气", "tool_hits": []}]
    assert ch13_10._detect_cross_talk(results) == []


def test_cross_talk_empty_input_no_false_positive(ch13_10):
    """无关键词的输入不应产生误报"""
    results = [{"user_id": 1, "success": True, "input": "你好", "tool_hits": []}]
    assert ch13_10._detect_cross_talk(results) == []


# ============================================================
# 4. 常量与可复现性
# ============================================================

def test_random_seed_fixed(ch13_10):
    """随机种子必须固定（压测可复现）"""
    assert isinstance(ch13_10.RANDOM_SEED, int)


def test_self_test_users_bounded(ch13_10):
    """self-test 并发数应受控（真实 LLM 调用成本）"""
    assert 1 <= ch13_10.SELF_TEST_USERS <= 10


# ============================================================
# 5. 单请求契约（真实调用）
# ============================================================

@pytest.mark.live
def test_single_request_structure(ch13_10):
    """run_single_request 返回结构化 dict，success 为 bool"""
    r = ch13_10.run_single_request(0, "请查询北京的天气")
    assert set(r.keys()) == {"user_id", "input", "success", "reply", "duration", "tool_hits"}
    assert isinstance(r["success"], bool)
    assert isinstance(r["duration"], float)
    assert isinstance(r["tool_hits"], list)
    assert len(r["reply"]) <= 80


@pytest.mark.live
@pytest.mark.slow
def test_concurrent_test_small(ch13_10):
    """小并发压测（3 用户）返回完整报告结构，无串话"""
    report = ch13_10.run_concurrent_test(concurrent_users=3)
    assert set(report.keys()) == {"metrics", "results", "cross_talk_suspects"}
    assert report["metrics"]["total"] == 3
    assert isinstance(report["cross_talk_suspects"], list)


@pytest.mark.live
@pytest.mark.slow
def test_concurrent_test_reproducible(ch13_10):
    """同种子两次压测的任务分配应完全一致（可复现）"""
    r1 = ch13_10.run_concurrent_test(concurrent_users=2, seed=123)
    r2 = ch13_10.run_concurrent_test(concurrent_users=2, seed=123)
    assert [r["input"] for r in r1["results"]] == [r["input"] for r in r2["results"]]


def test_format_report_returns_string(ch13_10):
    """format_report 应输出多行文本报告（纯格式化，可离线测）"""
    fake_report = {
        "metrics": {"total": 2, "success_count": 2, "failed_count": 0,
                    "error_rate": 0.0, "avg_time": 1.0, "p50_time": 1.0,
                    "p95_time": 1.5, "max_time": 2.0, "qps": 2.0},
        "results": [{"user_id": 0, "duration": 1.0, "tool_hits": ["multiply"], "reply": "56"}],
        "cross_talk_suspects": [],
    }
    text = ch13_10.format_report(fake_report)
    assert isinstance(text, str)
    assert "压测报告" in text
    assert "串话" in text
