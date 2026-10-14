"""
test_ch13_03_safe_eval.py —— chapter13 / 03 工具调用链与异常回退机制

【TDD 定位】被测文件：chapter13/03_工具调用链与异常回退机制.py
【测试策略】safe_eval / 工具函数 = 安全边界重灾区，纯函数全量断言；
            工具链真实调用 = @pytest.mark.live

【本篇要守住的契约】（来自源码逐行核对，非臆造）
  - safe_eval 支持 + - * / % 与括号、一元正负
  - safe_eval 拒绝：函数调用、属性访问、幂运算(DoS)、下标、lambda、导入
  - query_weather("未知") 返回 {"success": False}（教材 raise 改结构化错误）
  - calculate_expression 捕获 SyntaxError/ValueError/ZeroDivisionError → 结构化错误
  - execute_tool 白名单：未知工具/非法 JSON/工具异常 均返回 JSON 错误串，永不抛出
  - MCP 错误码常量 -32700/-32601/-32602/-32603
"""

import json
import pytest

pytestmark = pytest.mark.usefixtures("ch13_03")


# ============================================================
# 1. safe_eval —— 允许的语法
# ============================================================

@pytest.mark.parametrize("expr,expected", [
    ("7 * (8 + 3)", 77),
    ("1 + 2 + 3", 6),
    ("10 - 4", 6),
    ("20 / 4", 5.0),
    ("7 % 3", 1),
    ("-5 + 8", 3),
    ("+3", 3),
    ("2 * 3 - 4", 2),
    ("(1 + 2) * (3 + 4)", 21),
    ("100 / 4 / 5", 5.0),
    ("3.5 * 2", 7.0),
])
def test_safe_eval_valid_expressions(ch13_03, expr, expected):
    """四则运算 + 括号 + 一元运算符应正确求值"""
    assert ch13_03.safe_eval(expr) == expected


# ============================================================
# 2. safe_eval —— 拒绝的语法（安全底线，全章不变式②）
# ============================================================

@pytest.mark.parametrize("dangerous", [
    "__import__('os').system('echo x')",   # 导入+调用
    "open('/etc/passwd').read()",          # 文件访问
    "eval('1+1')",                         # 嵌套 eval
    "lambda: 1",                           # lambda
    "[1,2,3][0]",                          # 下标
    "x + 1",                               # 未定义变量
    "9 ** 9 ** 9",                         # 幂运算 DoS（刻意排除 ast.Pow）
    "print(1)",                            # 函数调用
    "'a'.upper()",                         # 属性访问 + 方法调用
    "(1).__class__",                       # 属性访问
    "[x for x in range(3)]",               # 推导式
])
def test_safe_eval_rejects_dangerous(ch13_03, dangerous):
    """白名单外的语法必须被拒绝（ValueError / SyntaxError）"""
    with pytest.raises((ValueError, SyntaxError)):
        ch13_03.safe_eval(dangerous)


def test_safe_eval_rejects_syntax_error(ch13_03):
    """语法不合法抛 SyntaxError"""
    with pytest.raises(SyntaxError):
        ch13_03.safe_eval("1 +* 2")


def test_pow_excluded_from_whitelist(ch13_03):
    """幂运算必须在白名单外（注释明确：9**9**9 可毫秒内打爆内存）"""
    import ast
    assert ast.Pow not in ch13_03._ALLOWED_BINOPS


# ============================================================
# 3. 工具函数 —— 结构化错误（错误是数据）
# ============================================================

def test_query_weather_normal(ch13_03):
    """正常城市返回 success=True 的 JSON"""
    out = json.loads(ch13_03.query_weather("北京"))
    assert out["success"] is True
    assert "北京" in out["result"]


def test_query_weather_unknown_returns_structured_error(ch13_03):
    """'未知' 城市返回 success=False（教材 raise 改为结构化错误）"""
    out = json.loads(ch13_03.query_weather("未知"))
    assert out["success"] is False
    assert "error" in out


def test_query_weather_strips_input(ch13_03):
    """城市名应被 strip —— 前后空格不应影响判定"""
    out = json.loads(ch13_03.query_weather("  未知  "))
    assert out["success"] is False


@pytest.mark.parametrize("expr,expected", [
    ("7 * (8 + 3)", 77), ("1+2+3", 6), ("10/4", 2.5),
])
def test_calculate_expression_valid(ch13_03, expr, expected):
    """合法表达式返回 success=True"""
    out = json.loads(ch13_03.calculate_expression(expr))
    assert out["success"] is True
    assert out["result"] == expected


@pytest.mark.parametrize("bad_expr", ["1 / 0", "1 +* 2", "__import__('os')", "abc + 1"])
def test_calculate_expression_error_structured(ch13_03, bad_expr):
    """除零 / 语法错 / 危险语法 → 结构化错误，不抛出"""
    out = json.loads(ch13_03.calculate_expression(bad_expr))
    assert out["success"] is False
    assert "error" in out


# ============================================================
# 4. execute_tool —— 统一入口，永不抛出
# ============================================================

def test_execute_tool_unknown_tool(ch13_03):
    """未知工具名返回结构化 JSON 错误"""
    out = json.loads(ch13_03.execute_tool("no_such", "{}"))
    assert out["success"] is False
    assert "未知工具" in out["error"]


def test_execute_tool_invalid_json_args(ch13_03):
    """参数不是合法 JSON 返回结构化错误"""
    out = json.loads(ch13_03.execute_tool("query_weather", "not-json"))
    assert out["success"] is False


def test_execute_tool_normal_dispatch(ch13_03):
    """正常分发到工具函数"""
    out = json.loads(ch13_03.execute_tool("calculate_expression", '{"expr": "2+3"}'))
    assert out["success"] is True
    assert out["result"] == 5


def test_execute_tool_never_raises(ch13_03):
    """穷举坏输入，execute_tool 必须始终返回 JSON 字符串"""
    for name, args in [("query_weather", "{}"), ("query_weather", "[]"),
                       ("calculate_expression", "{}"), ("", "{}"), ("x", "bad")]:
        out = ch13_03.execute_tool(name, args)
        assert isinstance(out, str)
        json.loads(out)              # 必须是合法 JSON


# ============================================================
# 5. _extract_tool_calls 两形态兼容
# ============================================================

def test_extract_tool_calls_absent(ch13_03):
    """无 tool_calls 属性 → 空列表"""
    class M:
        content = "x"
    assert ch13_03._extract_tool_calls(M()) == []


def test_extract_tool_calls_dict_element(ch13_03):
    """元素为 dict 形态（实测主形态）"""
    class M:
        tool_calls = [{"function": {"name": "query_weather", "arguments": '{"city":"北京"}'}}]
    out = ch13_03._extract_tool_calls(M())
    assert out == [{"name": "query_weather", "arguments": '{"city":"北京"}'}]


def test_extract_tool_calls_object_element(ch13_03):
    """元素为对象形态同样兼容"""
    class Fn:
        name = "calculate_expression"
        arguments = '{"expr":"1+1"}'
    class Tc:
        function = Fn()
    class M:
        tool_calls = [Tc()]
    out = ch13_03._extract_tool_calls(M())
    assert out[0]["name"] == "calculate_expression"
    assert out[0]["arguments"] == '{"expr":"1+1"}'


# ============================================================
# 6. 常量契约
# ============================================================

def test_tool_funcs_match_schema(ch13_03):
    """TOOL_FUNCS 注册表与 TOOLS_SCHEMA 声明一致"""
    schema_names = {s["function"]["name"] for s in ch13_03.TOOLS_SCHEMA}
    assert schema_names == set(ch13_03.TOOL_FUNCS.keys())


def test_tool_schema_outer_wrapper(ch13_03):
    """TOOLS_SCHEMA 必须双层包装"""
    for s in ch13_03.TOOLS_SCHEMA:
        assert s["type"] == "function"
        assert "function" in s and "name" in s["function"]
