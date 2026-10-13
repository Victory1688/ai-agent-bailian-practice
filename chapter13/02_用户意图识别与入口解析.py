# 第13章 项目案例：从零实现一个复合智能体系统
# 【例13-2】用户意图识别与入口解析
#
# ★ 教材简化 vs 生产级改写
#
# 教材原版问题（已注释保留）：
#   ① Qwen2Chat / DeepSeekChat 虚构类 + langchain.schema 过时 import
#      （同例 13-1，不赘述）
#   ② eval(response.content.strip()) —— 本篇最严重的问题：直接执行
#      LLM 输出。LLM 可能返回任意 Python 代码（提示注入可让模型输出
#      恶意语句），eval 会原样执行——这是把"解析"写成了"远程代码执行"
#   ③ eval 的实用性也是假的：LLM 输出常带 ```json 围栏、前后说明文字，
#      eval 直接语法错误 → 主备模型全部失败 → 5 条查询全输出"未知"
#      （教材第 7 节的"预期输出"实际跑不出来）
#   ④ JSON 与 Python 字面量不等价：true/false/null vs True/False/None，
#      单引号 vs 双引号——eval 能吞掉这些差异，但代价是上面的安全洞
#   ⑤ 解析结果零校验：intent 拼错、parameters 不是字典都直接透传给
#      下游调度，坏数据在链路里传播
#   ⑥ 兜底过程用 print 且无原因记录；traceback 外泄（同 13-01）
#   ⑦ 无 self-test
#
# 本次改写（安全解析 + schema 校验 + 结构化兜底链）：
#   ① extract_json 安全解析器：剥 markdown 围栏 → 括号配对定位 →
#      json.loads 严格解析；任何失败返回 None，绝不执行模型输出
#   ② validate_intent 结果校验：intent 白名单归一化（模糊包含匹配）、
#      domain 字符串、parameters 字典——不合法归"未知"，坏数据止步于此
#   ③ INTENT_TEMPLATE 强化：要求"仅输出 JSON、双引号、无围栏"，
#      从源头降低解析失败率（教材模板保留为注释）
#   ④ ModelInvoker 内联复用例 13-1 的适配器模式（注册表 + 双协议）；
#      生产中应直接 from 13-01 导入 ModelAdapter
#   ⑤ IntentParser 兜底链：主模型 → 备用模型 → 结构化"未知"
#      （教材语义保留），每步 logging 记录失败原因
#   ⑥ self-test 5 项：干净 JSON / 围栏清洗 / 恶意输出拒绝 /
#      真实意图识别 / schema 校验兜底

# ============================================================
# 原代码（注释保留——教材简化版，eval 执行 LLM 输出 + 零校验）
# ============================================================
# # -*- coding:utf-8 -*-
# import uuid
# import traceback
# from typing import Dict, Any
# from langchain_community.chat_models import Qwen2Chat, DeepSeekChat  # ← 虚构类
# from langchain.schema import HumanMessage                            # ← 路径过时
#
# INTENT_TEMPLATE = """
# 请将以下用户请求进行意图识别，返回格式为JSON，包含：
# - intent：意图类别（如 "查询", "执行", "对话", "工具调用"）
# - domain：任务领域（如 "天气", "数据库", "文本生成"）
# - parameters：提取的关键词参数（以键值对形式返回）
#
# 用户请求：
# "{query}"
# """
#
# class ModelInvoker:
#     def __init__(self, model_type="qwen"):
#         self.model_type = model_type
#         self.model = self._load_model()          # ← 虚构类加载
#
#     def run_intent_recognition(self, user_query: str) -> Dict[str, Any]:
#         prompt = INTENT_TEMPLATE.replace("{query}", user_query)
#         message = [HumanMessage(content=prompt)]
#         try:
#             response = self.model(message)
#             result = eval(response.content.strip())   # ← 执行 LLM 输出：安全洞
#             return {"success": True, "data": result}
#         except Exception as e:
#             return {"success": False, "error": str(e),
#                     "traceback": traceback.format_exc()}   # ← 堆栈外泄
#
# class IntentParser:
#     def __init__(self):
#         self.primary = ModelInvoker("qwen")
#         self.backup = ModelInvoker("deepseek")
#
#     def parse(self, query: str) -> Dict[str, Any]:
#         result = self.primary.run_intent_recognition(query)
#         if result["success"]:
#             return result["data"]                # ← 结果零校验直通下游
#         print("[WARN] Qwen解析失败，尝试使用Deepseek")
#         result = self.backup.run_intent_recognition(query)
#         ...
#         return {"intent": "未知", "domain": "未知", "parameters": {}}
# ============================================================

import os
import re
import sys
import json
import logging
import dashscope

# ===== dashscope 统一配置（前 10 章模式）=====
dashscope.api_key = os.environ.get("DASHSCOPE_API_KEY")

# ===== 日志：控制台输出 =====
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

# ===== 常量 =====
MAX_TOKENS = 256
# 意图白名单（"未知"是兜底链终点，保留教材语义）
VALID_INTENTS = ("查询", "执行", "对话", "工具调用", "未知")

# 模型注册表（复用例 13-1 的适配器模式：注册表 + 双协议）
MODEL_REGISTRY = {
    "qwen": {"model": "qwen-plus", "protocol": "native"},
    "deepseek": {"model": "qwen-turbo", "protocol": "openai"},  # 账号未开通 DeepSeek 托管
}
DASHSCOPE_COMPAT_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# ===== 意图识别模板（教材原版注释保留，输出约束强化）=====
# INTENT_TEMPLATE = """
# 请将以下用户请求进行意图识别，返回格式为JSON，包含：
# - intent：意图类别（如 "查询", "执行", "对话", "工具调用"）
# - domain：任务领域（如 "天气", "数据库", "文本生成"）
# - parameters：提取的关键词参数（以键值对形式返回）
#
# 用户请求：
# "{query}"
# """
INTENT_TEMPLATE = (
    "请将以下用户请求进行意图识别，仅输出一个 JSON 对象，不要输出任何其他文字、"
    "解释或 markdown 代码围栏。JSON 必须使用双引号，格式：\n"
    '{"intent": "查询|执行|对话|工具调用 之一", "domain": "任务领域", "parameters": {"参数名": "值"}}\n\n'
    "用户请求：\n{query}\n"
)


# ============================================================
# 组件 1：extract_json —— 安全 JSON 解析器（替代 eval）
# ============================================================

def extract_json(text: str):
    """从 LLM 输出中安全提取 JSON 对象（绝不执行模型输出）

    三步清洗：剥 markdown 围栏 → 括号配对定位首个 {...} → json.loads 严格解析

    参数: text — 模型原始输出
    返回: 解析成功的 dict；任何失败返回 None（由上层走兜底）
    """
    if not text:
        return None
    cleaned = text.strip()
    # 第一步：剥离 ```json ... ``` 围栏（LLM 最常见的输出习惯）
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.S)
    if fence:
        cleaned = fence.group(1).strip()
    # 第二步：定位首个 { 并做括号配对（容忍 JSON 前后的说明文字）
    start = cleaned.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(cleaned)):
        if cleaned[i] == "{":
            depth += 1
        elif cleaned[i] == "}":
            depth -= 1
            if depth == 0:
                # 第三步：json.loads 严格解析——数据就是数据，永远不当代码执行
                try:
                    return json.loads(cleaned[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


# ============================================================
# 组件 2：validate_intent —— 意图结果 schema 校验（坏数据止步于此）
# ============================================================

def validate_intent(data) -> dict:
    """校验并规范化意图识别结果（不合法归'未知'，拦截坏数据传播）

    参数: data — extract_json 的输出
    返回: {"intent", "domain", "parameters"} 规范化结构
    """
    if not isinstance(data, dict):
        return {"intent": "未知", "domain": "未知", "parameters": {}}
    raw_intent = str(data.get("intent", ""))
    # 白名单精确匹配 → 模糊包含归一化（容忍"天气查询"这类变体）→ 兜底"未知"
    intent = raw_intent if raw_intent in VALID_INTENTS else "未知"
    if intent == "未知":
        for it in VALID_INTENTS:
            if it != "未知" and it in raw_intent:
                intent = it
                break
    domain = data.get("domain")
    params = data.get("parameters")
    return {
        "intent": intent,
        "domain": domain if isinstance(domain, str) else "未知",
        "parameters": params if isinstance(params, dict) else {},
    }


# ============================================================
# 组件 3：ModelInvoker —— 内联简化版适配器（复用例 13-1 模式）
# ============================================================

class ModelInvoker:
    """单模型意图识别调用器（生产中应复用例 13-1 的 ModelAdapter）"""

    def __init__(self, model_type: str):
        """按注册表初始化

        参数: model_type — 注册表键
        异常: ValueError — 类型未注册
        """
        if model_type not in MODEL_REGISTRY:
            raise ValueError(f"不支持的模型类型：{model_type}")
        spec = MODEL_REGISTRY[model_type]
        self.model_type = model_type
        self.model_name = spec["model"]
        self.protocol = spec["protocol"]

    def run_intent_recognition(self, user_query: str) -> dict:
        """意图识别：调模型 → 安全解析 → schema 校验

        参数: user_query — 用户原始请求
        返回: {"success", "data"} 或 {"success", "error"}
        """
        try:
            # 用 replace 而非 format：模板内嵌 JSON 示例的花括号会被
            # format 误解析为占位符（KeyError: '"intent"'）——实测踩坑
            raw = self._invoke(INTENT_TEMPLATE.replace("{query}", user_query))
            data = extract_json(raw)
            if data is None:
                raise ValueError(f"模型输出不是合法 JSON: {raw[:80]}")
            return {"success": True, "data": validate_intent(data)}
        except Exception as e:
            logger.warning(f"[意图] {self.model_type} 解析失败: {e}")
            return {"success": False, "error": str(e)}

    def _invoke(self, prompt: str) -> str:
        """按注册协议分发调用（native / openai 双协议）

        参数: prompt — 完整提示词
        返回: 模型原始输出文本
        异常: 调用失败抛异常（由上层统一兜底）
        """
        if self.protocol == "native":
            resp = dashscope.Generation.call(model=self.model_name, messages=[
                {"role": "user", "content": prompt}],
                max_tokens=MAX_TOKENS, result_format="message")
            if resp.status_code != 200:
                raise RuntimeError(f"{resp.code} {resp.message}")
            return resp.output.choices[0].message.content
        from openai import OpenAI
        client = OpenAI(api_key=dashscope.api_key, base_url=DASHSCOPE_COMPAT_BASE)
        resp = client.chat.completions.create(model=self.model_name,
                                              messages=[{"role": "user", "content": prompt}],
                                              max_tokens=MAX_TOKENS)
        return resp.choices[0].message.content


# ============================================================
# 组件 4：IntentParser —— 主备兜底链（坏数据/坏模型的最终防线）
# ============================================================

class IntentParser:
    """意图解析入口：主模型 → 备用模型 → 结构化"未知"（教材兜底语义保留）"""

    def __init__(self):
        """装配主备模型"""
        self.primary = ModelInvoker("qwen")
        self.backup = ModelInvoker("deepseek")

    def parse(self, query: str) -> dict:
        """解析用户意图（永不抛异常，永远返回合法结构）

        参数: query — 用户原始请求
        返回: {"intent", "domain", "parameters"}
        """
        result = self.primary.run_intent_recognition(query)
        if result["success"]:
            return result["data"]
        logger.warning("[兜底] 主模型解析失败，切换备用模型")
        result = self.backup.run_intent_recognition(query)
        if result["success"]:
            return result["data"]
        logger.error("[兜底] 所有模型解析失败，返回结构化未知")
        # 教材兜底语义保留：结构化"未知"让下游调度可判断、可重试
        return {"intent": "未知", "domain": "未知", "parameters": {}}


# ============================================================
# self-test（5 项）
# ============================================================

def run_self_test() -> bool:
    """验证安全解析 / 围栏清洗 / 恶意输出拒绝 / 真实识别 / 兜底链"""
    ok = True
    parser = IntentParser()

    print("\n" + "=" * 60)
    print("  char13-02 用户意图识别与入口解析 —— Self Test")
    print("=" * 60)

    # Test 1: 干净 JSON 直解
    print("\n--- Test 1: 干净 JSON 解析 ---")
    try:
        data = extract_json('{"intent": "查询", "domain": "天气", "parameters": {"城市": "上海"}}')
        assert data == {"intent": "查询", "domain": "天气", "parameters": {"城市": "上海"}}
        print("  [通过] 合法 JSON 原样解析")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 2: markdown 围栏 + 前后说明文字清洗
    print("\n--- Test 2: 围栏与噪声清洗 ---")
    try:
        noisy = '好的，以下是识别结果：\n```json\n{"intent": "执行", "domain": "数据库",\n "parameters": {"脚本": "清理"}}\n```\n请查收。'
        data = extract_json(noisy)
        assert data and data["intent"] == "执行", f"围栏清洗失败: {data}"
        print(f"  [通过] 围栏+噪声清洗后解析: {data}")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 3: 恶意输出拒绝（对比 eval 的安全洞）
    print("\n--- Test 3: 恶意/非 JSON 输出拒绝 ---")
    try:
        # Python 字面量（单引号 + 函数调用）——eval 会执行，json.loads 必须拒绝
        malicious = "{'intent': '查询', 'cmd': __import__('os').system('echo hacked')}"
        assert extract_json(malicious) is None, "恶意字面量不应被解析"
        assert extract_json("我说的是 { 没有闭合的大括号") is None, "未闭合括号应返回 None"
        assert extract_json("") is None, "空输出应返回 None"
        print("  [通过] eval 会执行上述字面量，extract_json 全部拒绝——安全洞已封")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 4: 真实 LLM 意图识别（教材同款查询）
    print("\n--- Test 4: 真实意图识别（qwen-plus 原生协议）---")
    try:
        result = parser.parse("请帮我查一下今天上海的天气")
        assert result["intent"] in VALID_INTENTS and result["intent"] != "未知", result
        print(f"  [通过] 识别结果: {result}")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 5: 教材多查询批量识别（语义清晰的精确断言，模糊样本只验契约）
    print("\n--- Test 5: 多查询批量识别（教材 5 条）---")
    try:
        # 意图类别边界天然模糊（"生成短文"判"执行"或"工具调用"都合理），
        # 测试只对语义边界清晰的样本精确断言；模糊样本只验证契约合法
        exact_cases = [("帮我执行一下数据库清理脚本", "执行"),
                       ("你好，你能陪我聊聊天吗？", "对话")]
        for q, exp in exact_cases:
            result = parser.parse(q)
            assert result["intent"] == exp, f"{q} → 期望 {exp} 实际 {result}"
            print(f"  [通过] {q[:18]}... → intent={result['intent']} domain={result['domain']}")
        # 模糊样本：只断言白名单契约（防止意图越界透传下游）
        fuzzy = parser.parse("生成一篇关于人工智能未来发展的短文")
        assert fuzzy["intent"] in VALID_INTENTS, f"意图越界: {fuzzy}"
        print(f"  [通过] 模糊样本（生成短文）契约合法: intent={fuzzy['intent']}（分类边界模糊属正常）")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    return ok


def run_demo():
    """手动体验入口：教材同款 5 条查询逐条解析"""
    parser = IntentParser()
    queries = [
        "请帮我查一下今天上海的天气",
        "生成一篇关于人工智能未来发展的短文",
        "将这段文字翻译成英文：你好世界",
        "帮我执行一下数据库清理脚本",
        "你好，你能陪我聊聊天吗？",
    ]
    for i, q in enumerate(queries):
        print(f"\n用户请求{i + 1}：{q}")
        print("识别结果：", parser.parse(q))


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
