"""
test_ch13_02_intent.py —— chapter13 / 02 用户意图识别与入口解析

【TDD 定位】被测文件：chapter13/02_用户意图识别与入口解析.py
【测试策略】extract_json / validate_intent = 纯函数，可大量确定性断言；
            意图识别链路 = 真实调用（@pytest.mark.live）

【本篇要守住的契约】（来自源码逐行核对，非臆造）
  - extract_json 三步清洗：剥 markdown 围栏 → 括号配对定位首个 {...} → json.loads
  - extract_json 任何失败返回 None（绝不执行模型输出，全章零 eval）
  - validate_intent 白名单精确匹配 → 模糊包含归一化 → 兜底"未知"
  - validate_intent 对非 dict 输入返回结构化"未知"
  - INTENT_TEMPLATE 必须用 replace 填充（format 会 KeyError —— 实测踩坑）
  - IntentParser.parse 永不抛异常，永远返回合法结构
  - ModelInvoker 未注册类型抛 ValueError
"""

import pytest

pytestmark = pytest.mark.usefixtures("ch13_02")


# ============================================================
# 1. extract_json —— 安全解析（替代 eval 的核心）
# ============================================================

def test_extract_json_plain(ch13_02):
    """纯 JSON 对象直接解析"""
    assert ch13_02.extract_json('{"intent": "查询"}') == {"intent": "查询"}


def test_extract_json_with_markdown_fence(ch13_02):
    """```json ... ``` 围栏必须被剥离（LLM 最常见输出习惯）"""
    text = '```json\n{"intent": "执行", "domain": "数据库"}\n```'
    assert ch13_02.extract_json(text) == {"intent": "执行", "domain": "数据库"}


def test_extract_json_fence_without_lang(ch13_02):
    """``` ... ``` 无语言标记的围栏同样要剥离"""
    text = '```\n{"intent": "对话"}\n```'
    assert ch13_02.extract_json(text) == {"intent": "对话"}


def test_extract_json_with_surrounding_prose(ch13_02):
    """JSON 前后有说明文字时，括号配对应能定位对象"""
    text = '好的，识别结果如下：{"intent": "查询", "domain": "天气"} 请查收。'
    assert ch13_02.extract_json(text) == {"intent": "查询", "domain": "天气"}


def test_extract_json_nested_braces(ch13_02):
    """嵌套花括号必须正确配对（depth 计数，非简单 find）"""
    text = '{"intent": "查询", "parameters": {"city": "北京", "extra": {"k": "v"}}}'
    out = ch13_02.extract_json(text)
    assert out["parameters"]["city"] == "北京"
    assert out["parameters"]["extra"]["k"] == "v"


def test_extract_json_multiple_objects_takes_first(ch13_02):
    """多个对象时取首个完整对象"""
    text = '{"intent": "A"}{"intent": "B"}'
    assert ch13_02.extract_json(text) == {"intent": "A"}


@pytest.mark.parametrize("bad", [
    "", None, "no json here", "{unclosed", "}{", "plain text",
    '{"intent": }', '{"a": 1,}',      # 尾逗号非法
])
def test_extract_json_returns_none_on_failure(ch13_02, bad):
    """任何非法输入必须返回 None（而非抛异常、更非 eval）"""
    assert ch13_02.extract_json(bad) is None


def test_extract_json_never_evaluates_code(ch13_02):
    """安全底线：即使输入是可执行的 Python 表达式，也绝不执行

    全章不变式②：LLM 输出永不执行，eval 在全章零出现。
    """
    malicious = "__import__('os').system('echo hacked')"
    assert ch13_02.extract_json(malicious) is None


# ============================================================
# 2. validate_intent —— schema 校验与归一化
# ============================================================

@pytest.mark.parametrize("intent", ["查询", "执行", "对话", "工具调用", "未知"])
def test_validate_intent_whitelist_exact(ch13_02, intent):
    """白名单内意图精确匹配通过"""
    out = ch13_02.validate_intent({"intent": intent, "domain": "x", "parameters": {}})
    assert out["intent"] == intent


def test_validate_intent_fuzzy_contains(ch13_02):
    """模糊包含归一化：'天气查询' → '查询'"""
    out = ch13_02.validate_intent({"intent": "天气查询"})
    assert out["intent"] == "查询"


def test_validate_intent_unknown_fallback(ch13_02):
    """完全无法匹配时兜底为 '未知'"""
    out = ch13_02.validate_intent({"intent": "问个好"})
    assert out["intent"] == "未知"


@pytest.mark.parametrize("bad_input", [None, "字符串", 123, ["列表"], (1, 2)])
def test_validate_intent_non_dict_returns_unknown(ch13_02, bad_input):
    """非 dict 输入必须返回结构化'未知'，不抛异常"""
    out = ch13_02.validate_intent(bad_input)
    assert out == {"intent": "未知", "domain": "未知", "parameters": {}}


def test_validate_intent_normalizes_fields(ch13_02):
    """domain 非 str → '未知'；parameters 非 dict → {}"""
    out = ch13_02.validate_intent({"intent": "查询", "domain": 999, "parameters": "坏值"})
    assert out["domain"] == "未知"
    assert out["parameters"] == {}


def test_validate_intent_output_shape(ch13_02):
    """输出必须恒为三字段结构"""
    out = ch13_02.validate_intent({"intent": "查询"})
    assert set(out.keys()) == {"intent", "domain", "parameters"}


def test_validate_intent_missing_fields(ch13_02):
    """缺字段的输入应被补齐为默认值，不 KeyError"""
    out = ch13_02.validate_intent({})
    assert out == {"intent": "未知", "domain": "未知", "parameters": {}}


# ============================================================
# 3. INTENT_TEMPLATE —— replace 填充纪律（实测踩坑）
# ============================================================

def test_template_contains_query_placeholder(ch13_02):
    """模板必须含 {query} 占位符"""
    assert "{query}" in ch13_02.INTENT_TEMPLATE


def test_template_replace_does_not_crash(ch13_02):
    """用 replace 填充不得抛异常 —— 模板内嵌 JSON 花括号会被 format 误解析"""
    filled = ch13_02.INTENT_TEMPLATE.replace("{query}", "北京天气如何")
    assert "北京天气如何" in filled


def test_template_format_would_crash(ch13_02):
    """反证：用 str.format 填充必然 KeyError（这就是源码坚持 replace 的原因）"""
    with pytest.raises((KeyError, IndexError, ValueError)):
        ch13_02.INTENT_TEMPLATE.format(query="北京天气如何")


# ============================================================
# 4. ModelInvoker / IntentParser 结构契约
# ============================================================

def test_invoker_rejects_unregistered(ch13_02):
    """未注册模型类型抛 ValueError"""
    for bad in ("gpt-4", "", "Qwen"):
        with pytest.raises(ValueError):
            ch13_02.ModelInvoker(bad)


def test_intent_parser_never_raises(ch13_02):
    """parse 永不抛异常，恒返回合法三字段结构（真实调用验证）"""
    parser = ch13_02.IntentParser()
    out = parser.parse("帮我查一下北京天气")
    assert set(out.keys()) == {"intent", "domain", "parameters"}
    assert out["intent"] in ch13_02.VALID_INTENTS


def test_valid_intents_includes_unknown(ch13_02):
    """兜底链终点 '未知' 必须在白名单中"""
    assert "未知" in ch13_02.VALID_INTENTS


# ============================================================
# 5. 真实意图识别链路
# ============================================================

@pytest.mark.live
def test_intent_recognition_weather_query(ch13_02):
    """真实调用：'北京天气' 应被识别并输出合法结构"""
    invoker = ch13_02.ModelInvoker("qwen")
    result = invoker.run_intent_recognition("请帮我查询北京的天气")
    assert result["success"] is True, result.get("error")
    data = result["data"]
    assert data["intent"] in ch13_02.VALID_INTENTS
    assert isinstance(data["parameters"], dict)


@pytest.mark.live
def test_intent_parser_fallback_chain(ch13_02):
    """兜底链：主模型正常时应直接返回结果"""
    parser = ch13_02.IntentParser()
    out = parser.parse("计算一下 7 乘以 8 等于多少")
    assert out["intent"] in ch13_02.VALID_INTENTS
