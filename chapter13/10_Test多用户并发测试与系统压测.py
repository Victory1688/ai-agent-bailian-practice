# 第13章 项目案例：从零实现一个复合智能体系统
# 【例13-10】多用户并发测试与系统压测
#
# ★ 教材原版问题（已注释保留）：
#   ① Qwen2Chat / DeepSeekChat 虚构类 + initialize_agent /
#      AgentType.OPENAI_FUNCTIONS / Tool.from_function legacy 全线废弃
#      （13-08/13-09 同款，import 即崩，从未真正跑通过）
#   ② 【最严重】并发不安全：agent 在并发外创建一次，task_runner 闭包
#      捕获同一个实例——改写后的 AgentCore 有 self.history 会话状态，
#      多线程共享会导致「串话」（用户A的问题进用户B的上下文）；
#      多用户语义下每个用户本就该有独立会话
#   ③ 错误判断脆弱：run 返回 "[ERROR] ..." 字符串混流，
#      success 统计靠 "[ERROR]" not in output 字符串包含——若模型
#      回复恰好含 "[ERROR]" 字样会误判；若异常文案变化则失效
#   ④ 指标残缺：教材声称输出"错误率指标"但只打印失败数没算百分比；
#      压测只看平均值——LLM 响应是长尾分布，平均值会被掩盖，
#      生产压测必须看 P95/P99 分位数
#   ⑤ random.choice 无种子——测试不可复现，两次跑结果对不上
#   ⑥ results[:5] 按 as_completed 完成顺序输出（每次不同），
#      教材却展示为固定输出
#   ⑦ 20 并发直接打 LLM API 必触发限流（429），教材无任何限流说明；
#      traceback import 了从未使用
#   ⑧ 无 self-test
#
# 本次改写（复用 13-08 AgentCore 作为被压测主体，13-09 模式延续）：
#   ① 并发安全设计：每个请求新建独立 AgentCore 实例（独立会话 =
#      多用户真实语义，天然规避 history 串话）；dashscope SDK 本身
#      线程安全，可安全并发调用
#   ② 结构化结果契约：每请求返回 {"user_id", "input", "success",
#      "reply", "duration", "tool_hits"}——成功与否看布尔值，
#      不再字符串匹配；tool_hits 记录实际工具调用次数（串话检测依据）
#   ③ 指标补全：compute_metrics 纯函数计算 错误率% / avg / P50 / P95 /
#      QPS / 成功数——拆成纯函数便于单测（13-09 指标可测模式延续）
#   ④ 可复现：random.seed 固定；结果按 user_id 排序输出（完成顺序≠展示顺序）
#   ⑤ 限流防御：默认并发降为可承受范围（self-test 3 用户），并在
#      文档明确「LLM 压测与 Web 压测的差异」（成本 + 限流 + 秒级响应）
#   ⑥ self-test 5 项：指标纯函数单测 / 单请求冒烟 / 小并发真实压测 /
#      结果契约与串话检测 / 分位数与 QPS 合理性
#
# 注：原教材无 redis、无 A2A/MCP 协议 → 两条备注不触发

# ============================================================
# 原代码（注释保留——教材简化版，共享实例并发 + 字符串判错 + 指标残缺）
# ============================================================
# # 【例13-10】
# # -*- coding:utf-8 -*-
# # 多用户并发测试与系统压测脚本（Qwen3.0 + Deepseek + LangChain）
# # 模拟数十用户并发调用系统智能体服务，输出每个请求的响应时间与内容
# # 计算系统平均响应时长，QPS与错误率指标，用于评估大模型在实战场景下的负载能力与稳定性。
#
# import time
# import random
# import traceback                      # ← import 后从未使用
# from concurrent.futures import ThreadPoolExecutor, as_completed
# from langchain.agents import initialize_agent, Tool, AgentType   # ← legacy 已废弃
# from langchain_community.chat_models import Qwen2Chat, DeepSeekChat  # ← 虚构类
# from langchain_core.tools import tool
#
# # 一、定义基础工具函数
# @tool
# def fake_weather(city: str) -> str:
#     return f"{city}天气晴朗，26°C"      # ← 无 docstring（@tool 依赖 docstring 生成描述）
#
# @tool
# def calc(a: str, b: str) -> str:
#     try:
#         return str(float(a) * float(b))
#     except:
#         return "输入有误"                # ← 裸 except
#
# TOOLS = [
#     Tool.from_function(fake_weather),   # ← 双重包装
#     Tool.from_function(calc),
# ]
#
# # 二、定义模型Agent执行器（支持Qwen/Deepseek）
# class ConcurrentAgent:
#     def __init__(self, model_type="qwen"):
#         self.model_type = model_type
#         self.model = self._load_model()
#         self.executor = initialize_agent(
#             tools=TOOLS,
#             llm=self.model,
#             agent=AgentType.OPENAI_FUNCTIONS,
#             verbose=False,
#             handle_parsing_errors=True,
#         )
#
#     def _load_model(self):
#         if self.model_type == "qwen":
#             return Qwen2Chat(model="Qwen/Qwen1.5-7B-Chat")
#         elif self.model_type == "deepseek":
#             return DeepSeekChat(model="deepseek-ai/deepseek-llm-chat")
#         else:
#             raise ValueError("未知模型类型")
#
#     def run(self, text: str) -> str:
#         try:
#             return self.executor.run(text)
#         except Exception as e:
#             return f"[ERROR] {str(e)}"   # ← 错误字符串混流
#
# # 三、并发测试器
# def run_concurrent_test(concurrent_users: int = 20, model_type="qwen"):
#     agent = ConcurrentAgent(model_type=model_type)   # ← 共享单实例，并发串话风险
#     tasks = [
#         "请查询北京的天气",
#         "广州今天什么天气",
#         "请帮我计算 12 * 13",
#         "算一下9乘以7是多少",
#         "帮我查查上海的气温",
#     ]
#
#     results = []
#     start_time = time.time()
#
#     def task_runner(user_id: int):
#         text = random.choice(tasks)      # ← 无种子，不可复现
#         st = time.time()
#         response = agent.run(text)
#         et = time.time()
#         duration = et - st
#         return {
#             "user_id": user_id,
#             "input": text,
#             "output": response,
#             "duration": duration
#         }
#
#     print(f"\n【并发测试启动】模型：{model_type.upper()} | 用户数：{concurrent_users}")
#     with ThreadPoolExecutor(max_workers=concurrent_users) as executor:
#         futures = [executor.submit(task_runner, i) for i in range(concurrent_users)]
#         for f in as_completed(futures):
#             results.append(f.result())
#
#     end_time = time.time()
#     total_time = end_time - start_time
#
#     # 输出统计指标
#     success_count = sum(1 for r in results if "[ERROR]" not in r["output"])  # ← 字符串判错
#     avg_time = sum(r["duration"] for r in results) / len(results)
#     qps = len(results) / total_time
#
#     print("\n【测试结果统计】")
#     print(f"总请求数：{len(results)}")
#     print(f"成功响应数：{success_count}")
#     print(f"失败响应数：{len(results) - success_count}")
#     print(f"平均响应时间：{avg_time:.2f}s")
#     print(f"QPS（每秒处理请求数）：{qps:.2f}")     # ← 无错误率%、无 P95/P99 分位数
#
#     # 输出部分响应详情
#     for r in results[:5]:             # ← as_completed 顺序，每次运行不同
#         print(f"\n用户{r['user_id']}输入：{r['input']}")
#         print(f"响应用时：{r['duration']:.2f}s")
#         print(f"响应内容：{r['output']}")
#
# # 四、测试入口
# def run_demo():
#     run_concurrent_test(concurrent_users=20, model_type="qwen")
#     run_concurrent_test(concurrent_users=20, model_type="deepseek")
#
# run_demo()                            # ← import 即执行，无入口保护
# ============================================================

import os
import sys
import time
import random
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

# ===== 复用 13-08 AgentCore（被压测主体，dashscope 原生 function calling）=====
import importlib.util

_CHAR13_DIR = os.path.dirname(os.path.abspath(__file__))
_CHAR08_PATH = os.path.join(_CHAR13_DIR, "08_LangChain的通用Agent主控链条.py")
_spec = importlib.util.spec_from_file_location("char13_08", _CHAR08_PATH)
_mod08 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod08)
AgentCore = _mod08.AgentCore

# ===== 日志：控制台输出 =====
logging.basicConfig(level=logging.WARNING,
                    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

# ===== 常量 =====
RANDOM_SEED = 42                 # 固定种子：压测任务分配可复现
SELF_TEST_USERS = 3              # self-test 并发数（真实 LLM 调用，控制成本与限流）
DEMO_USERS = 6                   # --demo 默认并发数


# ============================================================
# 组件 1：指标计算（纯函数，与执行解耦，可单测）
# ============================================================

def _percentile(sorted_vals: list, p: float) -> float:
    """计算分位数（线性插值法，与 numpy.percentile 默认语义一致）

    参数: sorted_vals — 已升序排序的数值列表（非空）; p — 分位（0~1）
    返回: 对应分位数值（介于两相邻元素间的插值）
    """
    import math
    pos = p * (len(sorted_vals) - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return sorted_vals[lo]
    # 插值：pos 的小数部分决定两相邻元素的加权比例
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def compute_metrics(results: list, total_time: float) -> dict:
    """从结构化请求结果列表计算压测指标（纯函数，无副作用）

    参数: results — 每请求结果 [{"success", "duration"}, ...]（非空）;
          total_time — 压测墙钟总耗时（秒）
    返回: {"total", "success_count", "failed_count", "error_rate",
           "avg_time", "p50_time", "p95_time", "max_time", "qps"}
    """
    durations = sorted(r["duration"] for r in results)
    success_count = sum(1 for r in results if r["success"])
    failed_count = len(results) - success_count
    return {
        "total": len(results),
        "success_count": success_count,
        "failed_count": failed_count,
        "error_rate": failed_count / len(results),          # 错误率（百分比形式由格式化层转）
        "avg_time": sum(durations) / len(durations),
        "p50_time": _percentile(durations, 0.50),
        "p95_time": _percentile(durations, 0.95),
        "max_time": durations[-1],
        "qps": len(results) / total_time,
    }


# ============================================================
# 组件 2：单请求执行（独立会话 + 结构化契约 + 串话检测依据）
# ============================================================

def run_single_request(user_id: int, text: str) -> dict:
    """以独立 AgentCore 会话执行单个用户请求（多用户语义 = 每请求独立实例）

    参数: user_id — 用户编号; text — 用户输入
    返回: {"user_id", "input", "success", "reply", "duration", "tool_hits"}
          success 为布尔值（替代教材 "[ERROR]" 字符串匹配）；
          tool_hits 为实际工具调用序列（串话检测依据）
    """
    agent = AgentCore()          # 每请求独立实例：history 不跨用户共享（修复串话）
    st = time.time()
    result = agent.run(text)
    duration = time.time() - st
    return {
        "user_id": user_id,
        "input": text,
        "success": bool(result.get("success")),
        "reply": result.get("reply", result.get("error", ""))[:80],
        "duration": duration,
        "tool_hits": [s["tool"] for s in result.get("steps", [])],
    }


# ============================================================
# 组件 3：并发压测调度（线程池 + 串话检测 + 可复现）
# ============================================================

def _detect_cross_talk(results: list) -> list:
    """串话检测：校验每个请求的工具调用与自己的 input 语义一致

    规则：input 含天气/温度/气温关键词 → tool_hits 应含 get_temperature；
          input 含 乘/计算/* → tool_hits 应含 multiply。
    若共享了带 history 的实例，用户问题会进错上下文导致工具错配——
    本函数即以此作为串话信号。

    参数: results — run_concurrent_test 的结果列表
    返回: 串话可疑的 user_id 列表（空列表 = 无串话）
    """
    suspects = []
    for r in results:
        if not r["success"]:
            continue    # 失败请求无有效轨迹，跳过（失败本身已计入错误率）
        weather_ask = any(k in r["input"] for k in ("天气", "温度", "气温"))
        math_ask = any(k in r["input"] for k in ("乘", "计算", "*"))
        if weather_ask and "get_temperature" not in r["tool_hits"]:
            suspects.append(r["user_id"])
        if math_ask and "multiply" not in r["tool_hits"]:
            suspects.append(r["user_id"])
    return suspects


def run_concurrent_test(concurrent_users: int = DEMO_USERS,
                        seed: int = RANDOM_SEED) -> dict:
    """执行一轮并发压测（每请求独立会话 + 结构化指标）

    参数: concurrent_users — 并发用户数（LLM API 场景建议 <=10，
          过高会触发限流且费用线性增长）; seed — 任务分配随机种子（可复现）
    返回: {"metrics": compute_metrics 结果, "results": 按用户排序的明细,
           "cross_talk_suspects": 串话可疑用户列表}
    """
    random.seed(seed)    # 固定种子：每次运行任务分配完全一致（修复教材不可复现）
    tasks = [
        "请查询北京的天气",
        "广州今天什么天气",
        "请帮我计算 12 * 13",
        "算一下9乘以7是多少",
        "帮我查查上海的气温",
    ]
    logger.warning(f"[压测] 启动 · 并发 {concurrent_users} · seed {seed}")

    start_time = time.time()
    with ThreadPoolExecutor(max_workers=concurrent_users) as pool:
        futures = {pool.submit(run_single_request, i, random.choice(tasks)): i
                   for i in range(concurrent_users)}
        results = [f.result() for f in as_completed(futures)]
    total_time = time.time() - start_time

    results.sort(key=lambda r: r["user_id"])   # 按用户排序输出（完成顺序≠展示顺序）
    metrics = compute_metrics(results, total_time)
    suspects = _detect_cross_talk(results)
    return {"metrics": metrics, "results": results, "cross_talk_suspects": suspects}


# ============================================================
# 组件 4：报告格式化（指标字典 → 可读报告）
# ============================================================

def format_report(report: dict) -> str:
    """把压测报告格式化为多行可读文本

    参数: report — run_concurrent_test 返回的字典
    返回: 多行字符串报告
    """
    m = report["metrics"]
    lines = [
        "=" * 60,
        f"  并发压测报告 · 总请求 {m['total']} · 成功 {m['success_count']} · 失败 {m['failed_count']}",
        "-" * 60,
        f"  错误率：{m['error_rate']:.1%}",
        f"  平均响应：{m['avg_time']:.2f}s | P50：{m['p50_time']:.2f}s | "
        f"P95：{m['p95_time']:.2f}s | 最大：{m['max_time']:.2f}s",
        f"  QPS：{m['qps']:.2f}",
        "-" * 60,
    ]
    if report["cross_talk_suspects"]:
        lines.append(f"  [警告] 疑似串话用户：{report['cross_talk_suspects']}")
    else:
        lines.append("  串话检测：无（各用户会话独立，工具调用与输入语义一致）")
    for r in report["results"][:5]:
        lines.append(f"  用户{r['user_id']} · {r['duration']:.2f}s · "
                     f"工具{r['tool_hits'] or '无'} · {r['reply'][:40]}")
    lines.append("=" * 60)
    return "\n".join(lines)


# ============================================================
# self-test（5 项）
# ============================================================

def run_self_test() -> bool:
    """验证指标纯函数 / 单请求冒烟 / 小并发压测 / 契约与串话 / 分位数合理性"""
    ok = True

    print("\n" + "=" * 60)
    print("  char13-10 多用户并发测试与系统压测 —— Self Test")
    print("=" * 60)

    # Test 1: compute_metrics 纯函数单测（fake 数据确定性验证）
    print("\n--- Test 1: 指标计算纯函数单测 ---")
    try:
        fake = [{"success": True, "duration": 1.0},
                {"success": True, "duration": 2.0},
                {"success": False, "duration": 3.0},
                {"success": True, "duration": 4.0}]
        m = compute_metrics(fake, total_time=8.0)
        assert m["total"] == 4 and m["success_count"] == 3 and m["failed_count"] == 1
        assert abs(m["error_rate"] - 0.25) < 1e-9, "错误率应为 25%"
        assert abs(m["avg_time"] - 2.5) < 1e-9, "平均应为 2.5s"
        assert m["p50_time"] == 2.5, f"P50 应为 2.5（线性插值）实际 {m['p50_time']}"
        assert abs(m["p95_time"] - 3.85) < 1e-9, f"P95 应为 3.85 实际 {m['p95_time']}"
        assert abs(m["qps"] - 0.5) < 1e-9, "QPS 应为 0.5"
        print("  [通过] 错误率/平均/P50/P95/QPS 全部符合手工计算值")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 2: 单请求冒烟（真实 LLM 调用）
    print("\n--- Test 2: 单请求冒烟（真实链路）---")
    try:
        r = run_single_request(0, "请帮我计算 12 * 13")
        assert r["success"] and r["reply"], r
        assert "multiply" in r["tool_hits"], f"未调乘法工具: {r['tool_hits']}"
        assert r["duration"] > 0
        print(f"  [通过] 12*13 独立会话正常 · {r['duration']:.2f}s · 工具 {r['tool_hits']}")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 3: 小并发真实压测（3 用户）
    print("\n--- Test 3: 小并发压测（3 用户，控制成本与限流）---")
    try:
        report = run_concurrent_test(concurrent_users=SELF_TEST_USERS)
        m = report["metrics"]
        assert m["total"] == SELF_TEST_USERS
        assert m["success_count"] + m["failed_count"] == m["total"]
        assert m["qps"] > 0 and m["avg_time"] > 0
        # 3 用户全部失败大概率是限流/网络问题，属异常应暴露
        assert m["success_count"] >= 1, f"全部失败，疑似限流: {report['results']}"
        print(f"  [通过] 成功 {m['success_count']}/{m['total']} · "
              f"平均 {m['avg_time']:.2f}s · P95 {m['p95_time']:.2f}s · QPS {m['qps']:.2f}")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 4: 结果契约 + 串话检测（每请求独立会话验证）
    print("\n--- Test 4: 结果契约与串话检测 ---")
    try:
        report = run_concurrent_test(concurrent_users=SELF_TEST_USERS)
        for r in report["results"]:
            assert {"user_id", "input", "success", "reply",
                    "duration", "tool_hits"}.issubset(r.keys()), r
            assert isinstance(r["success"], bool), "success 必须是布尔（非字符串匹配）"
        # 串话检测：成功请求的工具调用必须与自身 input 语义一致
        assert report["cross_talk_suspects"] == [], \
            f"检测到串话: {report['cross_talk_suspects']}"
        # 可复现性：同 seed 任务分配一致
        random.seed(RANDOM_SEED)
        a = [random.choice(["x", "y"]) for _ in range(5)]
        random.seed(RANDOM_SEED)
        b = [random.choice(["x", "y"]) for _ in range(5)]
        assert a == b, "同种子两次分配应一致"
        print("  [通过] 契约字段完整 · success 为布尔 · 无串话 · 同种子分配可复现")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 5: 分位数与报告结构合理性
    print("\n--- Test 5: 分位数与报告结构 ---")
    try:
        report = run_concurrent_test(concurrent_users=SELF_TEST_USERS)
        m = report["metrics"]
        durs = sorted(r["duration"] for r in report["results"])
        assert m["avg_time"] >= 0
        assert m["p50_time"] <= m["p95_time"] <= m["max_time"], \
            f"分位数序异常: P50={m['p50_time']} P95={m['p95_time']} max={m['max_time']}"
        assert min(durs) <= m["avg_time"] <= max(durs), "平均值应落在 [min, max]"
        text = format_report(report)
        assert "错误率" in text and "QPS" in text and "串话检测" in text
        print(f"  [通过] P50({m['p50_time']:.2f}s) <= P95({m['p95_time']:.2f}s) "
              f"<= max({m['max_time']:.2f}s) · 报告含关键区段")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    return ok


def run_demo():
    """手动体验入口：默认 6 用户并发压测并输出完整报告"""
    print(format_report(run_concurrent_test(concurrent_users=DEMO_USERS)))


def main():
    """入口：跑 self-test；--demo 进入并发压测演示"""
    ok = run_self_test()
    print("\n" + "=" * 60)
    print("  全部 5 项 self-test 通过" if ok else "  存在失败项")
    print("=" * 60)
    if "--demo" in sys.argv:
        run_demo()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
