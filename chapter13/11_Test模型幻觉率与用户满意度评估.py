# 第13章 项目案例：从零实现一个复合智能体系统
# 【例13-11】模型幻觉率与用户满意度评估
#
# ★ 教材原版问题（已注释保留）：
#   ① Qwen2Chat / DeepSeekChat 虚构类 + langchain.schema 过时 import
#      （13-08/09/10 同款，import 即崩，从未跑通过）
#   ② 【最严重】幻觉检测算法错误：difflib.SequenceMatcher 字符相似度
#      < 0.6 判幻觉——字符相似度与事实一致性是两个维度：
#        · 事实正确的回答（表述不同，如"GDP总量约121万亿元" vs
#          "约为121万亿元人民币"）相似度可能低于阈值 → 误判幻觉
#        · 编造数值的回答（"500万亿元" vs "121万亿元"）大部分字符
#          相同 → 相似度高 → 事实错误反而不被判幻觉
#      用文本相似度冒充事实校验，测出来的"幻觉率"方向都可能是反的
#   ③ 用户满意度是纯随机数：random.randint(3,5) 打分——评分与回答
#      质量毫无关系，统计出的"平均满意度"没有任何意义
#   ④ "[ERROR]" 字符串混流 + user_score 靠字符串包含判错误
#   ⑤ 阈值 0.6 无任何依据（拍脑袋值）；SequenceMatcher 对中英文混排
#      与标点差异极敏感，同一事实换个标点相似度就大变
#   ⑥ run_demo() 模块顶层直接执行，无入口保护
#   ⑦ 无 self-test
#
# 本次改写（按真实业界 LLM 评估实践重构——LLM-as-a-Judge 裁判模式）：
#   ① 被测模型（qwen-plus）生成回答；裁判模型（qwen-plus）按
#      faithfulness 维度判定事实一致性，输出结构化 JSON
#      {"faithful", "score", "reason"}——Ragas / DeepEval / OpenAI
#      evals 的主流路线；裁判 prompt 明确"表述不同不影响判定"
#   ② 裁判输出经 _clean_json 安全清洗（13-02 确立：剥围栏 →
#      括号定位 → 严格 json.loads），杜绝 eval 与 str.format 花括号坑
#   ③ 满意度评分由裁判模型基于回答内容（准确性/完整性/清晰度）给出
#      1~5 分——仍是模拟用户评分，但至少内容相关；文档明确：
#      真实满意度应从产品埋点采集，此处是内容质量代理评估
#   ④ difflib 相似度保留为【辅助指标】单独报告（文本相似度≠事实
#      一致性，正可通过实测对照展示）——教育意义保留，语义纠正
#   ⑤ 结构化 metrics：{"total", "hallucinated", "halluc_rate",
#      "avg_score", "avg_similarity", "details"}——不再 print 混流
#   ⑥ self-test 5 项：JSON 清洗单测 / 相似度单测 / 裁判判别力实测
#      （构造对错答案验证裁判能区分）/ 全量真实评估 / metrics 契约
#
# 注：原教材无 redis、无 A2A/MCP 协议 → 两条备注不触发

# ============================================================
# 原代码（注释保留——教材简化版，相似度冒充幻觉检测 + 随机满意度）
# ============================================================
# # 【例13-11】
# # -*- coding:utf-8 -*-
# # 模型幻觉率与满意度评估系统（Qwen + Deepseek）
# # 评估大模型回答幻觉率与用户满意度的测试看框架，支持加载问答对比数据集，
# # 自动调用Qwen3.0与DeepSeek模型进行回答生成，比较模型输出与标准答案的差异程度，
# # 并且采集用户评分，最终输出幻觉率与满意度统计结果。
#
# import random
# import difflib
# from langchain_community.chat_models import Qwen2Chat, DeepSeekChat  # ← 虚构类
# from langchain.schema import HumanMessage                            # ← 过时 import
#
# # 一、定义基础问答数据集（真实QA + 标准答案）
# EVAL_SET = [
#     {
#         "question": "请问2022年中国的GDP是多少？",
#         "reference": "2022年中国GDP约为121万亿元人民币",
#     },
#     {
#         "question": "地球上最大的哺乳动物是什么？",
#         "reference": "地球上最大的哺乳动物是蓝鲸",
#     },
#     {
#         "question": "爱因斯坦是哪一年获得诺贝尔奖的？",
#         "reference": "爱因斯坦于1921年获得诺贝尔物理学奖",
#     },
#     {
#         "question": "Transformer模型由哪位研究者提出？",
#         "reference": "Transformer由Google的Vaswani等人在2017年提出",
#     },
#     {
#         "question": "请列出中国的四大发明",
#         "reference": "中国四大发明包括造纸术、指南针、火药和印刷术",
#     }
# ]
#
# # 二、加载模型接口
# class EvalAgent:
#     def __init__(self, model_type="qwen"):
#         if model_type == "qwen":
#             self.model = Qwen2Chat(model="Qwen/Qwen1.5-7B-Chat")   # ← 虚构
#         elif model_type == "deepseek":
#             self.model = DeepSeekChat(model="deepseek-ai/deepseek-llm-chat")
#         else:
#             raise ValueError("不支持的模型类型")
#
#     def ask(self, text: str) -> str:
#         try:
#             msg = [HumanMessage(content=text)]
#             response = self.model(msg)
#             return response.content.strip()
#         except Exception as e:
#             return f"[ERROR] 模型调用失败：{str(e)}"   # ← 错误字符串混流
#
# # 三、幻觉检测算法（基于规则与人工比对）
# def hallucination_detect(generated: str, reference: str) -> bool:
#     seq = difflib.SequenceMatcher(None, generated, reference)
#     similarity = seq.ratio()
#     return similarity < 0.6  # ← 字符相似度 ≠ 事实一致性（核心 bug）
#
# # 四、模拟用户满意度评分（随机+权重）
# def user_score(generated: str) -> int:
#     if "[ERROR]" in generated:                 # ← 字符串判错
#         return 1
#     base = random.randint(3, 5)                # ← 纯随机打分，与内容无关
#     if "不知道" in generated or "无法回答" in generated:
#         return base - 2
#     return base
#
# # 五、评估主流程
# def run_evaluation(model_type="qwen"):
#     agent = EvalAgent(model_type=model_type)
#     hallucinated = 0
#     total = len(EVAL_SET)
#     total_score = 0
#
#     print(f"\n【评估模型：{model_type.upper()}】")
#
#     for i, item in enumerate(EVAL_SET):
#         print(f"\n问题{i+1}：{item['question']}")
#         answer = agent.ask(item["question"])
#         print("生成回答：", answer)
#         print("参考答案：", item["reference"])
#         is_hallucinated = hallucination_detect(answer, item["reference"])
#         score = user_score(answer)
#         total_score += score
#         if is_hallucinated:
#             print("[×] 存在幻觉")
#             hallucinated += 1
#         else:
#             print("[✓] 无幻觉")
#         print(f"用户评分（模拟）：{score}")
#
#     halluc_rate = hallucinated / total
#     avg_score = total_score / total
#
#     print("\n【评估结果统计】")
#     print(f"总问题数：{total}")
#     print(f"幻觉数量：{hallucinated}")
#     print(f"幻觉率：{halluc_rate:.2f}")
#     print(f"平均满意度得分（1~5）：{avg_score:.2f}")
#
# # 六、执行评估
# def run_demo():
#     run_evaluation("qwen")
#     run_evaluation("deepseek")
#
# run_demo()                                    # ← import 即执行
# ============================================================

import os
import sys
import json
import difflib
import logging

# ===== dashscope 统一配置（前 10 章模式）=====
import dashscope
dashscope.api_key = os.environ.get("DASHSCOPE_API_KEY")

# ===== 日志：控制台输出 =====
logging.basicConfig(level=logging.WARNING,
                    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

# ===== 常量 =====
MAX_TOKENS = 512
EVAL_MODEL = "qwen-plus"    # 被测模型（生成回答）
JUDGE_MODEL = "qwen-plus"   # 裁判模型（LLM-as-a-Judge；生产建议用更强模型）

# ===== 评估数据集（教材 5 条原样保留）=====
EVAL_SET = [
    {"question": "请问2022年中国的GDP是多少？",
     "reference": "2022年中国GDP约为121万亿元人民币"},
    {"question": "地球上最大的哺乳动物是什么？",
     "reference": "地球上最大的哺乳动物是蓝鲸"},
    {"question": "爱因斯坦是哪一年获得诺贝尔奖的？",
     "reference": "爱因斯坦于1921年获得诺贝尔物理学奖"},
    {"question": "Transformer模型由哪位研究者提出？",
     "reference": "Transformer由Google的Vaswani等人在2017年提出"},
    {"question": "请列出中国的四大发明",
     "reference": "中国四大发明包括造纸术、指南针、火药和印刷术"},
]

# 裁判 prompt（LLM-as-a-Judge 核心：明确判定标准，要求结构化输出）
JUDGE_PROMPT = """你是严格的事实性评估裁判。给定【问题】【模型回答】【参考答案】，请判定：
1. faithful：模型回答的核心事实是否与参考答案一致。判定标准：
   - 关键事实（数值、主体、时间、名单）不矛盾即为一致，即使表述方式完全不同；
   - 回答补充了参考答案之外的正确信息，不影响一致性判定；
   - 关键事实错误、编造、或与参考答案冲突，判为不一致。
2. score：作为用户对该回答的满意度评分（1~5 整数）：
   1=答非所问或关键事实错误；3=基本正确但不完整；5=准确完整且表述清晰。
只输出一个 JSON 对象，不要输出任何其他内容：
{"faithful": true或false, "score": 1到5的整数, "reason": "一句话理由"}"""


# ============================================================
# 组件 1：裁判输出安全解析（13-02 确立的三步清洗）
# ============================================================

def _clean_json(text: str) -> dict:
    """从裁判模型输出中安全提取 JSON（剥围栏 → 括号定位 → 严格解析）

    参数: text — 裁判模型原始输出（可能含 markdown 围栏或前后缀文本）
    返回: 解析后的字典
    异常: ValueError — 输出中找不到合法 JSON
    """
    cleaned = text.strip()
    # 第一步：剥 ```json 围栏（若存在）
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    # 第二步：定位首尾大括号（截掉前后缀文本）
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"裁判输出中未找到 JSON：{text[:80]}")
    # 第三步：严格 json.loads（不 eval，杜绝代码执行）
    return json.loads(cleaned[start:end + 1])


# ============================================================
# 组件 2：模型调用（被测生成 + 裁判判定，均走 dashscope 原生协议）
# ============================================================

def generate_answer(question: str) -> str:
    """被测模型生成回答

    参数: question — 评估问题
    返回: 回答文本；调用失败返回空串（失败计入评估详情，不炸全流程）
    """
    try:
        resp = dashscope.Generation.call(
            model=EVAL_MODEL, result_format="message",
            messages=[{"role": "user", "content": question}])
        if resp.status_code != 200:
            logger.warning(f"[生成失败] {resp.code} {resp.message}")
            return ""
        return resp.output.choices[0].message.content.strip()
    except Exception as e:
        logger.warning(f"[生成异常] {e}")
        return ""


def judge_answer(question: str, generated: str, reference: str) -> dict:
    """裁判模型判定事实一致性与内容评分（LLM-as-a-Judge）

    参数: question — 原问题; generated — 被测模型回答; reference — 参考答案
    返回: {"faithful": bool, "score": int, "reason": str}；
          裁判调用失败时返回 {"faithful": None, "score": None, "reason": 失败说明}
          （None 与 False 区分：False 是"判定为不一致"，None 是"没判成"）
    """
    try:
        prompt = (f"【问题】{question}\n【模型回答】{generated}\n"
                  f"【参考答案】{reference}\n请按系统要求只输出 JSON。")
        resp = dashscope.Generation.call(
            model=JUDGE_MODEL, result_format="message",
            messages=[{"role": "system", "content": JUDGE_PROMPT},
                      {"role": "user", "content": prompt}])
        if resp.status_code != 200:
            return {"faithful": None, "score": None,
                    "reason": f"裁判调用失败 {resp.code}"}
        verdict = _clean_json(resp.output.choices[0].message.content)
        # 字段级校验：防止裁判漏字段或类型漂移
        return {"faithful": bool(verdict.get("faithful")),
                "score": int(verdict.get("score", 0)),
                "reason": str(verdict.get("reason", ""))}
    except Exception as e:
        return {"faithful": None, "score": None, "reason": f"裁判异常：{e}"}


def text_similarity(a: str, b: str) -> float:
    """文本相似度（difflib）——辅助指标，与事实一致性分开报告

    参数: a, b — 待比较文本
    返回: 0.0 ~ 1.0 相似度
    """
    return difflib.SequenceMatcher(None, a, b).ratio()


# ============================================================
# 组件 3：单条评估 + 全量评估（结构化 metrics）
# ============================================================

def evaluate_case(item: dict) -> dict:
    """评估单条 QA：生成 → 裁判判定 → 相似度辅助指标

    参数: item — {"question", "reference"} 数据条目
    返回: {"question", "generated", "reference", "faithful",
           "score", "reason", "similarity"}
    """
    generated = generate_answer(item["question"])
    verdict = judge_answer(item["question"], generated, item["reference"])
    return {
        "question": item["question"],
        "generated": generated[:60],
        "reference": item["reference"],
        "faithful": verdict["faithful"],
        "score": verdict["score"],
        "reason": verdict["reason"],
        "similarity": round(text_similarity(generated, item["reference"]), 3),
    }


def run_evaluation(eval_set: list = None) -> dict:
    """执行全量评估，返回结构化 metrics

    参数: eval_set — 评估数据集（默认教材 EVAL_SET）
    返回: {"total", "hallucinated", "halluc_rate", "avg_score",
           "avg_similarity", "judge_failures", "details"}
    """
    if eval_set is None:
        eval_set = EVAL_SET
    details = [evaluate_case(item) for item in eval_set]

    judged = [d for d in details if d["faithful"] is not None]   # 裁判成功的条目
    hallucinated = sum(1 for d in judged if not d["faithful"])
    scored = [d["score"] for d in details if d["score"] is not None]
    metrics = {
        "total": len(details),
        "hallucinated": hallucinated,
        "halluc_rate": round(hallucinated / len(judged), 3) if judged else None,
        "avg_score": round(sum(scored) / len(scored), 3) if scored else None,
        "avg_similarity": round(sum(d["similarity"] for d in details) / len(details), 3),
        "judge_failures": len(details) - len(judged),
        "details": details,
    }
    logger.warning(f"[评估] 完成 · 幻觉 {metrics['hallucinated']}/{len(judged)} · "
                   f"均分 {metrics['avg_score']} · 相似度 {metrics['avg_similarity']}")
    return metrics


def format_report(metrics: dict) -> str:
    """把评估 metrics 格式化为可读报告

    参数: metrics — run_evaluation 返回字典
    返回: 多行字符串报告
    """
    lines = [
        "=" * 60,
        f"  幻觉率与满意度评估报告 · 被测 {EVAL_MODEL} / 裁判 {JUDGE_MODEL}",
        "-" * 60,
        f"  总问题数：{metrics['total']}（裁判失败 {metrics['judge_failures']} 条）",
        f"  幻觉数量：{metrics['hallucinated']} · 幻觉率：{metrics['halluc_rate']}",
        f"  平均满意度（1~5，裁判模拟）：{metrics['avg_score']}",
        f"  平均文本相似度（辅助指标）：{metrics['avg_similarity']}",
        "-" * 60,
    ]
    for i, d in enumerate(metrics["details"], 1):
        mark = "一致" if d["faithful"] else ("未判" if d["faithful"] is None else "不一致")
        lines.append(f"  Q{i} [{mark}] 评分{d['score']} 相似度{d['similarity']} · {d['reason'][:36]}")
    lines.append("=" * 60)
    return "\n".join(lines)


# ============================================================
# self-test（5 项）
# ============================================================

def run_self_test() -> bool:
    """验证 JSON 清洗 / 相似度 / 裁判判别力 / 全量评估 / metrics 契约"""
    ok = True

    print("\n" + "=" * 60)
    print("  char13-11 模型幻觉率与用户满意度评估 —— Self Test")
    print("=" * 60)

    # Test 1: _clean_json 单测（三种输出形态，确定性）
    print("\n--- Test 1: 裁判输出 JSON 清洗单测 ---")
    try:
        assert _clean_json('{"faithful": true, "score": 5, "reason": "对"}')["faithful"] is True
        assert _clean_json('```json\n{"faithful": false, "score": 1, "reason": "编造"}\n```')["score"] == 1
        assert _clean_json('评估结果如下：{"faithful": true, "score": 4, "reason": "ok"} 以上。')["score"] == 4
        try:
            _clean_json("完全没有大括号的输出"); assert False, "应抛 ValueError"
        except ValueError:
            pass
        print("  [通过] 纯JSON / 围栏包裹 / 前后缀混杂三种形态均可提取；无JSON正确抛错")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 2: 相似度辅助指标单测（确定性）
    print("\n--- Test 2: 文本相似度单测 ---")
    try:
        assert text_similarity("蓝鲸", "蓝鲸") == 1.0, "相同文本应为 1.0"
        assert text_similarity("蓝鲸是最大的哺乳动物", "蓝鲸") > 0.3, "相关文本应有中等相似度"
        assert text_similarity("蓝鲸", "Transformer架构") < 0.2, "无关文本应低相似度"
        print("  [通过] 相同=1.0 / 相关中等 / 无关低——辅助指标语义正确")
    except Exception as e:
        print(f"  {e}"); ok = False

    # Test 3: 裁判判别力实测（构造对错答案验证裁判能区分）
    print("\n--- Test 3: 裁判判别力实测（LLM-as-a-Judge 核心验证）---")
    try:
        q = "地球上最大的哺乳动物是什么？"
        ref = "地球上最大的哺乳动物是蓝鲸"
        right = judge_answer(q, "世界上最大的哺乳动物是蓝鲸，体长可达30米。", ref)
        wrong = judge_answer(q, "地球上最大的哺乳动物是非洲象。", ref)
        assert right["faithful"] is True, f"正确答案被判不一致: {right}"
        assert wrong["faithful"] is False, f"编造答案未被识别: {wrong}"
        assert right["score"] > wrong["score"], f"评分未拉开差距: {right} vs {wrong}"
        print(f"  [通过] 表述不同的正确回答→一致(评分{right['score']})；"
              f"编造'非洲象'→不一致(评分{wrong['score']})——裁判判别力生效")
        print(f"        （对照教材 difflib：'非洲象'版与参考答案字符相似度 "
              f"{text_similarity('地球上最大的哺乳动物是非洲象。', ref):.2f}，"
              f"很可能高于阈值 0.6 而漏判）")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 4: 全量真实评估（5 条教材题）
    print("\n--- Test 4: 全量真实评估（qwen-plus 生成 + qwen-plus 裁判）---")
    try:
        metrics = run_evaluation()
        assert metrics["total"] == 5
        assert metrics["halluc_rate"] is not None and 0.0 <= metrics["halluc_rate"] <= 1.0
        assert metrics["avg_score"] is not None and 1 <= metrics["avg_score"] <= 5
        assert metrics["judge_failures"] <= 1, f"裁判失败过多: {metrics['judge_failures']}"
        print(f"  [通过] 幻觉率 {metrics['halluc_rate']} · 均分 {metrics['avg_score']} · "
              f"相似度 {metrics['avg_similarity']} · 裁判失败 {metrics['judge_failures']} 条")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 5: metrics 结构契约
    print("\n--- Test 5: metrics 结构契约 ---")
    try:
        metrics = run_evaluation(EVAL_SET[:2])   # 2 条降低成本，只验结构
        keys = {"total", "hallucinated", "halluc_rate", "avg_score",
                "avg_similarity", "judge_failures", "details"}
        assert keys.issubset(metrics.keys()), f"缺少键: {keys - metrics.keys()}"
        assert len(metrics["details"]) == 2
        for d in metrics["details"]:
            assert {"question", "generated", "reference", "faithful",
                    "score", "reason", "similarity"}.issubset(d.keys()), d
        report = format_report(metrics)
        assert "幻觉率" in report and "满意度" in report and "相似度" in report
        print("  [通过] metrics 七键完整 · details 七字段 · 报告含三大指标区段")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    return ok


def run_demo():
    """手动体验入口：全量评估并输出完整报告"""
    print(format_report(run_evaluation()))


def main():
    """入口：跑 self-test；--demo 进入评估演示"""
    ok = run_self_test()
    print("\n" + "=" * 60)
    print("  全部 5 项 self-test 通过" if ok else "  存在失败项")
    print("=" * 60)
    if "--demo" in sys.argv:
        run_demo()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
