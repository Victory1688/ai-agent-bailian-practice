"""
test_ch13_11_judge.py —— chapter13 / 11 Test 模型幻觉率与用户满意度评估

【TDD 定位】被测文件：chapter13/11_Test模型幻觉率与用户满意度评估.py
【测试策略】_clean_json / text_similarity = 纯函数，全量断言；
            LLM-as-a-Judge 真实评估 = @pytest.mark.live @pytest.mark.slow

【本篇要守住的契约】（来自源码逐行核对，非臆造）
  - _clean_json 三步清洗：剥围栏 → 首尾大括号定位 → 严格 json.loads
  - _clean_json 无 JSON 时抛 ValueError（不静默返回空）
  - judge_answer：裁判失败返回 faithful=None / score=None（None ≠ False 口径）
  - text_similarity 返回 0.0~1.0；相同为 1.0
  - run_evaluation：halluc_rate 只统计裁判成功的条目；judge_failures 单独计数
"""

import pytest

pytestmark = pytest.mark.usefixtures("ch13_11")


# ============================================================
# 1. _clean_json —— 裁判输出安全解析
# ============================================================

def test_clean_json_plain(ch13_11):
    """纯 JSON 直接解析"""
    assert ch13_11._clean_json('{"faithful": true, "score": 5}') == \
        {"faithful": True, "score": 5}


def test_clean_json_with_fence(ch13_11):
    """```json ... ``` 围栏必须剥离（裁判最容易带围栏）"""
    out = ch13_11._clean_json('```json\n{"faithful": false, "score": 2}\n```')
    assert out == {"faithful": False, "score": 2}


def test_clean_json_with_prose(ch13_11):
    """JSON 前后有说明文字时应能定位"""
    out = ch13_11._clean_json('判定结果如下：{"faithful": true, "score": 4} 完毕。')
    assert out["faithful"] is True and out["score"] == 4


def test_clean_json_nested(ch13_11):
    """嵌套对象应完整解析（用 rfind 定位最外层 }）"""
    out = ch13_11._clean_json('{"faithful": true, "detail": {"reason": "一致"}}')
    assert out["detail"]["reason"] == "一致"


@pytest.mark.parametrize("bad", ["没有 json", "这里是纯文本说明", "", "只有 { 没有右括号"])
def test_clean_json_raises_on_no_json(ch13_11, bad):
    """找不到完整 JSON 必须抛 ValueError（不静默返回空）"""
    with pytest.raises(ValueError):
        ch13_11._clean_json(bad)


def test_clean_json_empty_object_is_valid(ch13_11):
    """边界：'{}' 是合法 JSON（返回空字典，不抛错）"""
    assert ch13_11._clean_json("{}") == {}


def test_clean_json_never_evaluates(ch13_11):
    """安全底线：不执行任何代码（三步清洗只做 json.loads）"""
    with pytest.raises((ValueError, Exception)):
        ch13_11._clean_json("__import__('os').system('x')")


# ============================================================
# 2. text_similarity —— 辅助指标
# ============================================================

def test_similarity_identical(ch13_11):
    """完全相同文本相似度为 1.0"""
    assert ch13_11.text_similarity("人工智能", "人工智能") == pytest.approx(1.0)


def test_similarity_empty_both(ch13_11):
    """两个空串相似度为 1.0（difflib 语义）"""
    assert ch13_11.text_similarity("", "") == pytest.approx(1.0)


def test_similarity_partial(ch13_11):
    """部分重叠：相似度介于 0 与 1 之间"""
    s = ch13_11.text_similarity("今天天气很好", "今天天气不错")
    assert 0.0 < s < 1.0


def test_similarity_range(ch13_11):
    """返回值必须在 [0, 1] 区间"""
    for a, b in [("abc", "xyz"), ("a", "aaaa"), ("", "something")]:
        s = ch13_11.text_similarity(a, b)
        assert 0.0 <= s <= 1.0


def test_similarity_symmetric(ch13_11):
    """相似度对称"""
    assert ch13_11.text_similarity("abc", "abd") == pytest.approx(
        ch13_11.text_similarity("abd", "abc"))


# ============================================================
# 3. 常量与数据集
# ============================================================

def test_eval_set_structure(ch13_11):
    """评估集每条必须含 question 与 reference"""
    assert isinstance(ch13_11.EVAL_SET, list) and len(ch13_11.EVAL_SET) >= 1
    for item in ch13_11.EVAL_SET:
        assert "question" in item and "reference" in item


def test_judge_prompt_nonempty(ch13_11):
    """裁判提示词必须非空且含判定要求"""
    assert isinstance(ch13_11.JUDGE_PROMPT, str)
    assert len(ch13_11.JUDGE_PROMPT) > 20


def test_models_declared(ch13_11):
    """被测模型与裁判模型均应声明"""
    assert ch13_11.EVAL_MODEL and ch13_11.JUDGE_MODEL


# ============================================================
# 4. 评估链路（真实调用）
# ============================================================

@pytest.mark.live
def test_generate_answer_returns_text(ch13_11):
    """被测模型生成回答（失败返回空串，不抛异常）"""
    out = ch13_11.generate_answer("1+1等于几？请直接回答数字。")
    assert isinstance(out, str)


@pytest.mark.live
def test_judge_answer_contract(ch13_11):
    """裁判返回 {faithful, score, reason} 三字段"""
    verdict = ch13_11.judge_answer(
        "中国的首都是哪里？", "中国的首都是北京。", "北京")
    assert set(verdict.keys()) == {"faithful", "score", "reason"}


@pytest.mark.live
def test_judge_none_vs_false_semantics(ch13_11):
    """裁判失败时 faithful 为 None，成功判定为 False 时是 False（口径严格区分）"""
    verdict = ch13_11.judge_answer("测试问题", "某个回答", "某个参考答案")
    assert verdict["faithful"] in (True, False, None)
    if verdict["faithful"] is None:
        assert verdict["score"] is None      # 失败时 score 也应为 None


@pytest.mark.live
@pytest.mark.slow
def test_run_evaluation_metrics(ch13_11):
    """全量评估返回结构化 metrics（含 judge_failures 单独计数）"""
    metrics = ch13_11.run_evaluation(
        [{"question": "1+1等于几？", "reference": "2"}])
    assert set(metrics.keys()) == {"total", "hallucinated", "halluc_rate",
                                   "avg_score", "avg_similarity",
                                   "judge_failures", "details"}
    assert metrics["total"] == 1
    assert 0 <= metrics["judge_failures"] <= 1


@pytest.mark.live
@pytest.mark.slow
def test_halluc_rate_only_counts_judged(ch13_11):
    """halluc_rate 的样本量是裁判成功数，不是总数（None 不混入分母）"""
    metrics = ch13_11.run_evaluation(
        [{"question": "水的沸点是多少？", "reference": "100摄氏度"}])
    judged = metrics["total"] - metrics["judge_failures"]
    if judged == 0:
        assert metrics["halluc_rate"] is None       # 无有效判定 → None
    else:
        assert 0.0 <= metrics["halluc_rate"] <= 1.0
