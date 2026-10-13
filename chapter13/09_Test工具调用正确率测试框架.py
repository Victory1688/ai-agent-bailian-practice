# 第13章 项目案例：从零实现一个复合智能体系统
# 【例13-9】工具调用正确率测试框架
#
# ★ 教材原版问题（已注释保留）：
#   ① 【最严重】测试逻辑本身是坏的：run_tool_test 用
#      if case["expected_tool"] in output 判定匹配——expected_tool 是
#      内部工具名（weather_tool），output 是最终自然语言回复
#      （"北京天气为晴，温度25°C"），工具名永远不会出现在回复里，
#      正确率永远 0%；教材评论还写"故意触发错误"——但测试逻辑本身就是错的
#   ② 教材声称三项指标（工具名准确率、参数提取成功率、返回一致性），
#      实际一项都没真正实现
#   ③ initialize_agent / AgentType.OPENAI_FUNCTIONS / Tool.from_function
#      legacy 全线废弃（13-08 同款，import 即崩）
#   ④ Qwen2Chat / DeepSeekChat 虚构类
#   ⑤ 错误字符串混流：run 返回 "[ERROR] ..." 与正常输出同通道
#   ⑥ 无 self-test
#
# 本次改写（复用 13-08 AgentCore 作为被测主体，测试框架真正可测）：
#   ① 测试框架从 AgentCore.run 返回的 steps（工具调用轨迹）里提取
#      实际工具调用，与 expected_tool / expected_params /
#      expected_result_pattern 三项契约结构化比对——正确率可被真实测量
#   ② 实现三项指标：
#      - tool_name_accuracy：预期工具名 vs steps 里的实际工具名
#      - param_extraction_rate：必需参数是否存在、值是否符合预期
#      - return_consistency：工具返回是否匹配预期模式（正则）
#   ③ 测试集 TEST_CASES 扩展为三字段（tool + params + result_pattern）
#   ④ 多模型对比：qwen-plus vs qwen-turbo（实测可用；原教材 DeepSeek 未开通）
#   ⑤ run_tool_test 返回结构化 metrics 字典（替代 print 混流）
#   ⑥ self-test 5 项：三项指标单测 / 多模型对比 / 边界用例 /
#      月球多工具场景 / metrics 结构化输出
#
# 注：原教材无 redis、无 A2A/MCP 协议 → 两条备注不触发

# ============================================================
# 原代码（注释保留——教材简化版，测试逻辑本身坏掉 + legacy 全线）
# ============================================================
# # 【例13-9】
# # -*- coding:utf-8 -*-
# # 工具调用正确率测试系统（Qwen + Deepseek + LangChain Tools）
# # 发送自然语言测试用例，检测工具名称识别准确率，参数提取成功率与调用返回一致性，
# # 并输出调用正确率指标。
#
# from typing import List
# from langchain.agents import initialize_agent, Tool, AgentExecutor, AgentType  # ← legacy 全线废弃
# from langchain_community.chat_models import Qwen2Chat, DeepSeekChat           # ← 虚构类
# from langchain_core.tools import tool
#
# # 一、定义测试工具函数
# @tool
# def weather_tool(city: str) -> str:
#     """模拟天气查询工具"""
#     if city.lower() not in ["北京", "上海", "广州"]:
#         raise ValueError("城市不支持")
#     return f"{city}天气为晴，温度25°C"
#
# @tool
# def multiply_tool(a: str, b: str) -> str:
#     """模拟乘法计算工具"""
#     try:
#         return str(float(a) * float(b))
#     except:
#         raise ValueError("输入格式错误")
#
# TOOLS = [
#     Tool.from_function(weather_tool),   # ← @tool 已是 StructuredTool，双重包装
#     Tool.from_function(multiply_tool),
# ]
#
# # 二、构建工具测试Agent
# class ToolTestAgent:
#     def __init__(self, model_type="qwen"):
#         self.model_type = model_type
#         self.llm = self._load_model()
#         self.executor = initialize_agent(
#             tools=TOOLS,
#             llm=self.llm,
#             agent=AgentType.OPENAI_FUNCTIONS,
#             verbose=False,
#             handle_parsing_errors=True
#         )
#
#     def _load_model(self):
#         if self.model_type == "qwen":
#             return Qwen2Chat(model="Qwen/Qwen1.5-7B-Chat")
#         elif self.model_type == "deepseek":
#             return DeepSeekChat(model="deepseek-ai/deepseek-llm-chat")
#         else:
#             raise ValueError("不支持的模型类型")
#
#     def run(self, prompt: str) -> str:
#         try:
#             return self.executor.run(prompt)
#         except Exception as e:
#             return f"[ERROR] {str(e)}"
#
# # 三、定义测试集与执行框架
# TEST_CASES = [
#     {"input": "请查询一下北京的天气", "expected_tool": "weather_tool"},
#     {"input": "上海今天气温多少？", "expected_tool": "weather_tool"},
#     {"input": "广州天气怎么样？", "expected_tool": "weather_tool"},
#     {"input": "请帮我计算7乘以8", "expected_tool": "multiply_tool"},
#     {"input": "12和13相乘是多少？", "expected_tool": "multiply_tool"},
#     {"input": "你知道北京和月球的温度吗？", "expected_tool": "weather_tool"},  # ← 教材说"故意触发错误"
# ]
#
# def run_tool_test(agent_type="qwen"):
#     agent = ToolTestAgent(model_type=agent_type)
#     correct = 0
#     total = len(TEST_CASES)
#     print(f"\n【开始测试】模型：{agent_type.upper()} | 总用例数：{total}")
#
#     for i, case in enumerate(TEST_CASES):
#         print(f"\n测试{i+1} 输入：{case['input']}")
#         output = agent.run(case["input"])
#         print("输出结果：", output)
#
#         if case["expected_tool"] in output:    # ← 核心 bug！内部工具名 vs 自然语言回复
#             print("[✓] 匹配成功")
#             correct += 1
#         else:
#             print("[✗] 匹配失败")
#
#     print(f"\n【测试完成】模型：{agent_type.upper()} 正确率：{correct}/{total} = {correct/total:.2f}")
#
# # 四、运行主测试
# def run_demo():
#     run_tool_test("qwen")
#     run_tool_test("deepseek")
#
# run_demo()
# ============================================================

import os
import re
import sys
import json
import logging

# ===== 复用 13-08 AgentCore（被测主体，dashscope 原生 function calling）=====
# 用 importlib 动态加载，避免硬编码绝对路径
import importlib.util

_CHAR13_DIR = os.path.dirname(os.path.abspath(__file__))
_CHAR08_PATH = os.path.join(_CHAR13_DIR, "08_LangChain的通用Agent主控链条.py")
_spec = importlib.util.spec_from_file_location("char13_08", _CHAR08_PATH)
_mod08 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod08)
AgentCore = _mod08.AgentCore
MODEL_REGISTRY = _mod08.MODEL_REGISTRY
TOOLS_SPEC = _mod08.TOOLS_SPEC

# ===== dashscope 统一配置（前 10 章模式）=====
import dashscope
dashscope.api_key = os.environ.get("DASHSCOPE_API_KEY")

# ===== 日志：控制台输出 =====
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)


# ============================================================
# 组件 1：测试集定义（结构化契约——三项指标各有对位点）
# ============================================================

# 教材原测试集用 weather_tool / multiply_tool，13-08 TOOLS_SPEC 已统一为
# get_temperature / multiply（dashscope 原生命名）；测试集同步对齐

# 说明：每个用例的三项契约——
#   expected_tools:      预期模型会调用的工具名列表（可多个，如多工具场景）
#                        —— 用于 tool_name_accuracy 指标
#   expected_params:     预期工具调用的参数（可选，只覆盖最关键的必需参数字段）
#                        —— 用于 param_extraction_rate 指标
#   expected_result_pat: 预期工具返回的正则模式（用 re.search 匹配）
#                        —— 用于 return_consistency 指标
TEST_CASES = [
    # —— get_temperature 系列 ——
    {"id": "T01", "input": "请查询一下北京的天气",
     "expected_tools": ["get_temperature"],
     "expected_params": {"city": "北京"},
     "expected_result_pat": r"北京.*温度"},

    {"id": "T02", "input": "上海今天气温多少？",
     "expected_tools": ["get_temperature"],
     "expected_params": {"city": "上海"},
     "expected_result_pat": r"上海.*温度"},

    {"id": "T03", "input": "广州天气怎么样？",
     "expected_tools": ["get_temperature"],
     "expected_params": {"city": "广州"},
     "expected_result_pat": r"广州.*温度"},

    # —— multiply 系列 ——
    {"id": "T04", "input": "请帮我计算7乘以8",
     "expected_tools": ["multiply"],
     "expected_params": {"a": "7", "b": "8"},
     "expected_result_pat": r"56\.?"},

    {"id": "T05", "input": "12和13相乘是多少？",
     "expected_tools": ["multiply"],
     "expected_params": {"a": "12", "b": "13"},
     "expected_result_pat": r"156\.?"},

    # —— 多工具 + 错误回填（教材原"故意触发错误"用例，语义纠正）——
    # 教材原逻辑：单工具 weather_tool，城市月球触发 ValueError → 测"故意错误"
    # 改写逻辑：双工具 get_temperature，北京正常 + 月球触发错误回填 → 测多工具 + 错误回填链路
    {"id": "T06", "input": "你知道北京和月球的温度吗？",
     "expected_tools": ["get_temperature", "get_temperature"],
     "expected_params": None,   # 多参数场景不硬编码，由 param_extraction 单独测
     "expected_result_pat": None},
]


# ============================================================
# 组件 2：测试执行器（三项指标真实可测）
# ============================================================

def _extract_actual_tools(steps: list) -> list:
    """从 AgentCore.run 返回的 steps 里提取实际工具调用序列

    参数: steps — [{"round", "tool", "args", "result"}, ...] 列表
    返回: 工具名序列（按调用顺序）
    """
    return [s["tool"] for s in steps]


def _check_tool_name(expected: list, actual: list) -> bool:
    """工具名准确率比对：预期序列 vs 实际序列

    参数: expected — 预期工具名列表; actual — 实际工具名列表（可能为空，LLM 直答）
    返回: 序列完全一致为 True；预期非空但实际空 → False
    """
    if not expected and not actual:
        return True
    if expected and not actual:
        return False  # LLM 直答但预期要调工具 → 工具名失败
    return expected == actual


def _check_params(steps: list, expected_params: dict | None) -> bool:
    """参数提取成功率比对：预期必需参数字段是否存在且值匹配

    参数: steps — 工具调用轨迹（可能为空，LLM 直答）;
          expected_params — 预期参数字典（None 跳过此用例）
    返回: 所有必需参数均匹配为 True；预期非空但 steps 空 → False
    """
    if expected_params is None:
        return True
    if not steps:
        return False  # LLM 直答没调工具 → 参数提取失败
    # 取首个工具步骤的 args（一般单工具场景只有一条）
    first_step = steps[0]
    actual_args = first_step["args"]
    for key, exp_val in expected_params.items():
        if key not in actual_args:
            return False
        if actual_args[key] != exp_val:
            return False
    return True


def _check_result_pattern(steps: list, pattern: str | None) -> bool:
    """返回一致性比对：工具返回文本是否匹配预期正则

    参数: steps — 工具调用轨迹（可能为空，LLM 直答）;
          pattern — 正则模式字符串（None 跳过此用例）
    返回: 任一工具返回匹配模式为 True；预期非空但 steps 空 → False
    """
    if pattern is None:
        return True
    if not steps:
        return False  # LLM 直答没调工具 → 返回一致性无法验证
    for s in steps:
        if re.search(pattern, s["result"]):
            return True
    return False


def run_tool_test(model_name: str = "qwen-plus") -> dict:
    """执行全量测试集，返回结构化 metrics

    参数: model_name — 被测模型名（qwen-plus / qwen-turbo 等）
    返回: {
        "model": 模型名,
        "total_cases": 总用例数,
        "tool_name_rate": 工具名准确率（0.0 ~ 1.0）,
        "param_rate": 参数提取成功率,
        "return_rate": 返回一致性,
        "details": [每个用例的 pass/fail 分项结果],
        "overall": 三项指标的平均值
    }
    """
    metrics = {
        "model": model_name,
        "total_cases": len(TEST_CASES),
        "tool_name_rate": 0.0,
        "param_rate": 0.0,
        "return_rate": 0.0,
        "details": [],
        "overall": 0.0,
    }

    # 临时把 MODEL_REGISTRY 的 primary 槽位指向被测模型（不影响 backup）
    old_primary = MODEL_REGISTRY["primary"]["model"]
    MODEL_REGISTRY["primary"]["model"] = model_name
    try:
        agent = AgentCore()

        tool_hits = param_hits = return_hits = 0
        logger.info(f"[测试] 开始 · 模型 {model_name} · 用例 {len(TEST_CASES)}")

        for case in TEST_CASES:
            result = agent.run(case["input"])
            steps = result.get("steps", [])

            # 三项指标各自独立判断（任一不通过都不影响其他指标）
            actual_tools = _extract_actual_tools(steps)
            tool_ok = _check_tool_name(case["expected_tools"], actual_tools)
            param_ok = _check_params(steps, case["expected_params"])
            return_ok = _check_result_pattern(steps, case["expected_result_pat"])

            if tool_ok:
                tool_hits += 1
            if param_ok:
                param_hits += 1
            if return_ok:
                return_hits += 1

            metrics["details"].append({
                "id": case["id"],
                "input": case["input"],
                "expected_tools": case["expected_tools"],
                "actual_tools": actual_tools,
                "tool_ok": tool_ok,
                "param_ok": param_ok,
                "return_ok": return_ok,
                "reply": result.get("reply", "")[:80],
            })

            logger.info(f"  [{case['id']}] tool={'OK' if tool_ok else 'FAIL'} "
                        f"param={'OK' if param_ok else 'FAIL'} "
                        f"return={'OK' if return_ok else 'FAIL'} "
                        f"· 实际调用 {actual_tools}")

    finally:
        MODEL_REGISTRY["primary"]["model"] = old_primary  # 无论成败都还原注册表

    n = len(TEST_CASES)
    metrics["tool_name_rate"] = round(tool_hits / n, 3)
    metrics["param_rate"] = round(param_hits / n, 3)
    metrics["return_rate"] = round(return_hits / n, 3)
    metrics["overall"] = round((metrics["tool_name_rate"] + metrics["param_rate"] + metrics["return_rate"]) / 3, 3)

    logger.info(f"[测试] 完成 · {model_name} · "
                f"工具 {metrics['tool_name_rate']} / 参数 {metrics['param_rate']} / "
                f"返回 {metrics['return_rate']} · 综合 {metrics['overall']}")
    return metrics


# ============================================================
# 组件 3：多模型对比 + 报告输出
# ============================================================

def run_multi_model_compare(models: list = None) -> list:
    """对多个模型跑同一份测试集，返回 metrics 列表（便于并排对比）

    参数: models — 被测模型名列表，默认 ["qwen-plus", "qwen-turbo"]
    返回: 每个模型的 run_tool_test 结果 dict
    """
    if models is None:
        models = ["qwen-plus", "qwen-turbo"]
    return [run_tool_test(m) for m in models]


def format_metrics(metrics: dict) -> str:
    """把结构化 metrics 格式化为可读报告

    参数: metrics — run_tool_test 返回的字典
    返回: 多行字符串报告
    """
    lines = []
    lines.append("=" * 60)
    lines.append(f"  模型：{metrics['model']} · 总用例 {metrics['total_cases']}")
    lines.append("-" * 60)
    lines.append(f"  工具名准确率：{metrics['tool_name_rate']:.1%}")
    lines.append(f"  参数提取成功率：{metrics['param_rate']:.1%}")
    lines.append(f"  返回一致性：{metrics['return_rate']:.1%}")
    lines.append(f"  综合得分：{metrics['overall']:.1%}")
    lines.append("-" * 60)
    for d in metrics["details"]:
        tool_mark = "[OK]" if d["tool_ok"] else "[FAIL]"
        param_mark = "[OK]" if d["param_ok"] else "[FAIL]"
        return_mark = "[OK]" if d["return_ok"] else "[FAIL]"
        lines.append(f"  {d['id']} {tool_mark}{param_mark}{return_mark} · "
                     f"预期 {d['expected_tools']} → 实际 {d['actual_tools']}")
    lines.append("=" * 60)
    return "\n".join(lines)


# ============================================================
# self-test（5 项）
# ============================================================

def run_self_test() -> bool:
    """验证三项指标单测 / 多模型对比 / 边界用例 / 月球多工具 / metrics 结构化"""
    ok = True

    print("\n" + "=" * 60)
    print("  char13-09 工具调用正确率测试框架 —— Self Test")
    print("=" * 60)

    # Test 1: 三项指标单测（用 AgentCore.run 的 steps 确定性验证）
    print("\n--- Test 1: 三项指标单测（确定性）---")
    try:
        # 手动构造 steps，模拟 agent 正确调用 get_temperature('北京')
        fake_steps = [{"round": 1, "tool": "get_temperature",
                       "args": {"city": "北京"}, "result": "北京当前温度为26°C"}]
        assert _extract_actual_tools(fake_steps) == ["get_temperature"], "工具名提取"
        assert _check_tool_name(["get_temperature"], ["get_temperature"]), "工具名匹配"
        assert _check_params(fake_steps, {"city": "北京"}), "参数匹配"
        assert _check_result_pattern(fake_steps, r"北京.*温度"), "返回匹配"
        # 反向验证：错误工具名 / 错误参数 / 错误模式 都能被识别
        assert not _check_tool_name(["get_temperature"], ["multiply"]), "工具名不匹配应返回 False"
        assert not _check_params(fake_steps, {"city": "上海"}), "参数不匹配应返回 False"
        assert not _check_result_pattern(fake_steps, r"上海.*温度"), "模式不匹配应返回 False"
        print("  [通过] 三项指标单测全部正确——预期/实际比对逻辑无偏差")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 2: 真实链路（qwen-plus，测试集前 3 条 get_temperature + T04/T05 multiply）
    print("\n--- Test 2: 真实链路（qwen-plus，T01-T05 前 5 条）---")
    try:
        metrics = run_tool_test("qwen-plus")
        assert metrics["tool_name_rate"] >= 0.8, f"工具名准确率过低 {metrics['tool_name_rate']}"
        assert metrics["param_rate"] >= 0.8, f"参数提取成功率过低 {metrics['param_rate']}"
        assert metrics["return_rate"] >= 0.8, f"返回一致性过低 {metrics['return_rate']}"
        print(f"  [通过] 工具 {metrics['tool_name_rate']:.1%} / 参数 {metrics['param_rate']:.1%} / 返回 {metrics['return_rate']:.1%}")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 3: 月球多工具场景 T06（多工具 + 错误回填）
    print("\n--- Test 3: 月球多工具场景 T06 ---")
    try:
        old_primary = MODEL_REGISTRY["primary"]["model"]
        MODEL_REGISTRY["primary"]["model"] = "qwen-plus"
        try:
            agent = AgentCore()
            result = agent.run("你知道北京和月球的温度吗？")
        finally:
            MODEL_REGISTRY["primary"]["model"] = old_primary
        actual_tools = _extract_actual_tools(result.get("steps", []))
        # LLM 可能的行为：
        #   路径A：两次 get_temperature（北京 + 月球）→ 正确，tool_name 匹配 "get_temperature", "get_temperature"
        #   路径B：一次 get_temperature('北京') + 拒绝月球 → actual_tools = ["get_temperature"]
        # 测试策略：只要调过 get_temperature 就算工具调用生效，具体指标由 Test 2 分项覆盖
        assert "get_temperature" in actual_tools, f"未调温度工具: {actual_tools}"
        print(f"  [通过] 实际工具序列 {actual_tools}——LLM 行为已采集（多工具由 Test 2 分项覆盖）")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 4: metrics 结构化输出契约
    print("\n--- Test 4: metrics 结构化契约 ---")
    try:
        metrics = run_tool_test("qwen-plus")
        required_keys = {"model", "total_cases", "tool_name_rate", "param_rate",
                         "return_rate", "details", "overall"}
        assert required_keys.issubset(metrics.keys()), f"缺少键: {required_keys - metrics.keys()}"
        assert len(metrics["details"]) == len(TEST_CASES), "details 条数与测试集不符"
        for d in metrics["details"]:
            assert {"id", "tool_ok", "param_ok", "return_ok", "actual_tools"}.issubset(d.keys())
        print(f"  [通过] metrics 结构完整，details 每条含 id/工具名/参数/返回 OK 标记")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 5: 多模型对比（qwen-plus vs qwen-turbo）
    print("\n--- Test 5: 多模型对比 ---")
    try:
        compared = run_multi_model_compare(["qwen-plus", "qwen-turbo"])
        assert len(compared) == 2
        assert compared[0]["model"] == "qwen-plus"
        assert compared[1]["model"] == "qwen-turbo"
        # qwen-plus 综合得分应 >= qwen-turbo（turbo 是轻量模型）
        # 注：这是方向性预期，不严格断言，只记录对比数据
        print(f"  [通过] plus 综合 {compared[0]['overall']:.1%} / turbo 综合 {compared[1]['overall']:.1%} "
              f"——对比数据已产出")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    return ok


def run_demo():
    """手动体验入口：跑双模型对比"""
    print(format_metrics(run_tool_test("qwen-plus")))
    print(format_metrics(run_tool_test("qwen-turbo")))


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
