# 第13章 项目案例：从零实现一个复合智能体系统
# 【例13-3】工具调用链与异常回退机制
#
# ★ 教材简化 vs 生产级改写
#
# 教材原版问题（已注释保留）：
#   ① 标题写"Qwen3.0 + Deepseek"，代码里却是 Qwen/Qwen1.5-7B-Chat —— 标题与
#      内容自相矛盾
#   ② Qwen2Chat / DeepSeekChat 虚构类（char13-01 已验证不存在，import 即崩）
#   ③ initialize_agent + AgentType.OPENAI_FUNCTIONS —— LangChain 0.3+ 已废弃
#      的 Agent 构建方式（官方推荐 LangGraph / LCEL），且教材版本实际跑不通
#   ④ Tool.from_function(query_weather) 重复包装：@tool 装饰器已经返回
#      StructuredTool 实例，再 from_function 包装一次是错上加错
#   ⑤ calculate_expression 用 eval(expr) 计算 —— expr 由 LLM 决定，与例 13-2
#      同款的远程代码执行洞，只是这次洞开在工具内部
#   ⑥ except: 裸吞所有异常（含 KeyboardInterrupt），且无日志
#   ⑦ 工具级失败与模型级失败混为一谈："未知城市" raise 后被当成模型失败
#      触发 DeepSeek 回退——工具错误应当作为数据返回给模型（模型可见、可改述），
#      只有模型本身调不通才需要回退
#   ⑧ 每轮 run_with_tools 都 initialize_agent 重新构建 Agent（同 13-01 坑）
#   ⑨ traceback 打印到 stdout 外泄；无 self-test
#
# 本次改写（dashscope 原生 function calling + AST 白名单求值 + 双层回退语义）：
#   ① safe_eval：ast 白名单求值，只允许数字与 + - * / %（幂运算可构造
#      9**9**9 的 DoS，一并拒绝）——恶意表达式绝不执行
#   ② 工具注册表：真实函数 + JSON Schema 声明 + 统一执行入口 execute_tool
#      （工具名白名单校验 / 参数 JSON 解析 / 异常兜底，错误一律结构化返回）
#   ③ 双层回退语义：
#      - 工具级失败 → {"success": False, "error": ...} 回填给模型，由模型
#        向用户解释（工具错误是"数据"，链路不中断、不触发模型回退）
#      - 模型级失败 → 主备回退 qwen-plus → qwen-turbo，均走 dashscope 原生
#        function calling（双协议适配已在例 13-1 演示，本篇聚焦工具链，
#        统一原生协议避免 tool_calls 回填格式分叉）
#   ④ 工具调用轮数上限 MAX_TOOL_ROUNDS 防止无限循环
#   ⑤ self-test 6 项：safe_eval 白名单 / 工具级错误结构化 / 真实天气工具链 /
#      真实计算工具链 / 模型级回退（注入坏模型名实测）/ 非工具问题直答

# ============================================================
# 原代码（注释保留——教材简化版，废弃 Agent API + eval 工具洞 + 回退语义混淆）
# ============================================================
# # -*- coding:utf-8 -*-
# # 工具链调用与回退机制实现（Qwen3.0 + Deepseek + LangChain Tool）
# # 实现一个具备LangChain工具集成，函数调用链调度，异常识别处理与自动回退机制的智能体
#
# import traceback
# from typing import List
# from langchain_core.tools import tool
# from langchain.agents import initialize_agent, AgentType          # ← 已废弃
# from langchain.agents import Tool
# from langchain_community.chat_models import Qwen2Chat, DeepSeekChat  # ← 虚构类
# from langchain.schema import HumanMessage                         # ← 路径过时
#
# # 一、定义可供调用的工具函数
# @tool
# def query_weather(city: str) -> str:
#     """查询某地当前天气（模拟接口）"""
#     if city.lower() == "未知":
#         raise Exception("无法获取指定城市天气信息")   # ← 工具错误被当模型错误
#     return f"{city}当前天气：晴，气温26°C"
#
# @tool
# def calculate_expression(expr: str) -> str:
#     """计算表达式结果"""
#     try:
#         result = eval(expr)          # ← LLM 决定 expr：远程代码执行洞
#         return f"计算结果为：{result}"
#     except:                          # ← 裸吞一切异常
#         return "表达式有误，无法计算"
#
# TOOLS = [
#     Tool.from_function(query_weather),          # ← @tool 已返回实例，重复包装
#     Tool.from_function(calculate_expression),
# ]
#
# # 二、工具Agent管理器
# class ToolAgentManager:
#     def __init__(self):
#         self.primary_model = Qwen2Chat(model="Qwen/Qwen1.5-7B-Chat")       # ← 虚构
#         self.backup_model = DeepSeekChat(model="deepseek-ai/deepseek-llm-chat")
#
#     def run_with_tools(self, input_text: str) -> str:
#         # 首先尝试Qwen模型
#         try:
#             print("[INFO] 使用Qwen执行任务")
#             agent = initialize_agent(TOOLS, self.primary_model,          # ← 每轮重建
#                 agent=AgentType.OPENAI_FUNCTIONS, verbose=False)
#             return agent.run(input_text)
#         except Exception as e:
#             print("[WARN] Qwen执行失败，回退至Deepseek")
#             print(traceback.format_exc())                                # ← 堆栈外泄
#             # 若Qwen失败，尝试Deepseek
#             try:
#                 agent = initialize_agent(TOOLS, self.backup_model,
#                     agent=AgentType.OPENAI_FUNCTIONS, verbose=False)
#                 return agent.run(input_text)
#             except Exception as e2:
#                 print("[ERROR] 所有模型调用失败")
#                 print(traceback.format_exc())
#                 return "调用失败，系统暂时无法完成该请求。"
# ============================================================

import os
import sys
import ast
import json
import logging
import operator
import dashscope

# ===== dashscope 统一配置（前 10 章模式）=====
dashscope.api_key = os.environ.get("DASHSCOPE_API_KEY")

# ===== 日志：控制台输出 =====
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

# ===== 常量 =====
MAX_TOKENS = 512
MAX_TOOL_ROUNDS = 4   # 单次请求最多工具调用轮数（防模型无限循环调工具）

# 模型注册表：主备槽位（统一 dashscope 原生协议，理由见头部注释 ③）
# 注：实测当前百炼账号未开通 DeepSeek 托管（deepseek-* 模型 404），
# 备用槽位用 qwen-turbo 演示回退；若开通后改回 "deepseek-v3" 即可
MODEL_REGISTRY = {
    "primary": {"model": "qwen-plus"},
    "backup": {"model": "qwen-turbo"},
}


# ============================================================
# 组件 1：safe_eval —— AST 白名单求值（替代工具内部的 eval）
# ============================================================

# 允许的二元 / 一元运算符白名单（ast 节点类型 → 对应操作函数）
_ALLOWED_BINOPS = {
    ast.Add: operator.add, ast.Sub: operator.sub,
    ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.Mod: operator.mod,
}
_ALLOWED_UNARYOPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _eval_node(node):
    """递归求值单个 AST 节点（不在白名单的节点一律拒绝）

    参数: node — ast 解析出的节点
    返回: 数值结果（int / float）
    异常: ValueError — 节点类型不在白名单（含函数调用、属性访问、幂运算等）
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        return _ALLOWED_BINOPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARYOPS:
        return _ALLOWED_UNARYOPS[type(node.op)](_eval_node(node.operand))
    # 幂运算（ast.Pow）刻意不进白名单：9**9**9... 可在毫秒内打爆内存（DoS）
    raise ValueError(f"表达式包含不允许的语法：{type(node).__name__}")


def safe_eval(expr: str):
    """计算四则运算表达式的值（AST 白名单，绝不执行任意代码）

    参数: expr — 数学表达式字符串，如 "7 * (8 + 3)"
    返回: 数值结果
    异常: SyntaxError — 语法不合法; ValueError — 含白名单外的语法（eval 会执行
          的 __import__ / lambda 等在此全部被拒绝）
    """
    tree = ast.parse(expr, mode="eval")
    return _eval_node(tree.body)


# ============================================================
# 组件 2：工具注册表 —— 真实函数 + Schema 声明 + 统一执行入口
# ============================================================

def query_weather(city: str) -> str:
    """查询某地当前天气（模拟接口，教材语义保留）

    参数: city — 城市名；"未知" 按教材约定视为查不到
    返回: JSON 字符串 {"success": True/False, "result"/"error": ...}
          教材的 raise 改为结构化错误——工具错误是数据，不是故障
    """
    city = city.strip()
    if city == "未知":
        return json.dumps({"success": False, "error": "无法获取指定城市天气信息"},
                          ensure_ascii=False)
    return json.dumps({"success": True, "result": f"{city}当前天气：晴，气温26°C"},
                      ensure_ascii=False)


def calculate_expression(expr: str) -> str:
    """计算四则运算表达式（safe_eval 白名单求值，替代教材的 eval）

    参数: expr — 数学表达式字符串
    返回: JSON 字符串 {"success": True/False, "result"/"error": ...}
    """
    try:
        result = safe_eval(expr)
        return json.dumps({"success": True, "result": result}, ensure_ascii=False)
    except (SyntaxError, ValueError, ZeroDivisionError) as e:
        return json.dumps({"success": False, "error": f"表达式有误，无法计算：{e}"},
                          ensure_ascii=False)


# 工具 JSON Schema 声明（dashscope 原生 function calling 格式，与 OpenAI 兼容）
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "query_weather",
            "description": "查询某地当前天气",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string", "description": "城市名"}},
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_expression",
            "description": "计算四则运算表达式的值，仅支持数字与 + - * / % 和括号",
            "parameters": {
                "type": "object",
                "properties": {"expr": {"type": "string",
                                        "description": "数学表达式，如 7 * (8 + 3)"}},
                "required": ["expr"],
            },
        },
    },
]

# 工具名 → 可执行函数（白名单：不在表内的工具名一律拒绝）
TOOL_FUNCS = {
    "query_weather": query_weather,
    "calculate_expression": calculate_expression,
}


def _extract_tool_calls(msg) -> list:
    """从模型响应中提取工具调用列表（统一转为 {"name", "arguments"} dict）

    实测 dashscope Message 响应形态：
    - 模型未请求工具时，Message 对象上没有 tool_calls 属性（AttributeError）
    - 模型请求工具时，tool_calls 是元素为 dict 的列表（非 ToolCall 对象）
    两种形态都必须兼容，否则工具链在第一次真实调用就断

    参数: msg — dashscope 返回的 Message 对象
    返回: [{"name": 工具名, "arguments": 参数 JSON 字符串}, ...]，无调用返回空列表
    """
    calls = []
    for call in getattr(msg, "tool_calls", None) or []:
        # 兼容 dict / 对象两种元素形态（实测以 dict 出现）
        fn = call.get("function") if isinstance(call, dict) else call.function
        if isinstance(fn, dict):
            calls.append({"name": fn.get("name", ""),
                          "arguments": fn.get("arguments", "{}")})
        else:
            calls.append({"name": fn.name, "arguments": fn.arguments})
    return calls


def execute_tool(name: str, arguments: str) -> str:
    """统一工具执行入口：白名单校验 + 参数解析 + 异常兜底（永不抛出）

    参数: name — 模型要调用的工具名; arguments — 模型给的 JSON 参数字符串
    返回: JSON 字符串（工具结果或结构化错误），回填给模型
    """
    if name not in TOOL_FUNCS:
        return json.dumps({"success": False, "error": f"未知工具：{name}"},
                          ensure_ascii=False)
    try:
        args = json.loads(arguments)
    except json.JSONDecodeError as e:
        return json.dumps({"success": False, "error": f"参数不是合法 JSON：{e}"},
                          ensure_ascii=False)
    try:
        return TOOL_FUNCS[name](**args)
    except Exception as e:
        # 工具内部任何意外都转为结构化错误回填模型，链路不中断
        logger.warning(f"[工具] {name} 执行异常: {e}")
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ============================================================
# 组件 3：ToolAgentManager —— 工具调用链 + 主备回退（双层回退语义）
# ============================================================

class ToolAgentManager:
    """工具调用链管理器：模型级失败触发主备回退，工具级失败回填错误给模型"""

    def __init__(self):
        # 记录尝试过的模型槽位（self-test 用它验证"回退是否真的发生"）
        self.attempted_slots: list = []

    def run_with_tools(self, input_text: str) -> str:
        """执行任务：主模型 → 失败切备用模型 → 全败返回兜底文案

        参数: input_text — 用户原始请求
        返回: 模型最终回答文本（永不抛异常）
        """
        for slot in ("primary", "backup"):
            self.attempted_slots.append(slot)
            try:
                logger.info(f"[模型] 使用 {slot}({MODEL_REGISTRY[slot]['model']}) 执行任务")
                return self._run_tool_loop(input_text, slot)
            except Exception as e:
                # 只有"模型级失败"才走到这里（网络 / 限流 / 模型名不存在）
                logger.warning(f"[回退] {slot} 模型级失败: {e}")
        logger.error("[回退] 所有模型调用失败")
        return "调用失败，系统暂时无法完成该请求。"   # 教材兜底语义保留

    def _run_tool_loop(self, input_text: str, slot: str) -> str:
        """单模型的工具调用循环：调模型 → 执行工具 → 回填结果 → 再调模型

        参数: input_text — 用户请求; slot — 模型注册表槽位键
        返回: 模型不再请求工具时的最终回答文本
        异常: RuntimeError — 接口非 200 / 超过工具轮数上限（由上层触发回退）
        """
        messages = [{"role": "user", "content": input_text}]
        for _ in range(MAX_TOOL_ROUNDS):
            resp = dashscope.Generation.call(
                model=MODEL_REGISTRY[slot]["model"],
                messages=messages,
                tools=TOOLS_SCHEMA,
                max_tokens=MAX_TOKENS,
                result_format="message",
            )
            if resp.status_code != 200:
                raise RuntimeError(f"{resp.code} {resp.message}")
            msg = resp.output.choices[0].message
            calls = _extract_tool_calls(msg)
            # 模型不再请求工具 → 最终回答
            if not calls:
                content = getattr(msg, "content", None)
                return content if isinstance(content, str) else ""
            # assistant 消息（含 tool_calls）以原生 dict 原样回传——
            # 这是 function calling 协议要求；用 dict 而非 SDK 对象，
            # 避免二次序列化的形态不确定性（实测踩坑）
            messages.append({"role": "assistant",
                             "content": getattr(msg, "content", "") or "",
                             "tool_calls": getattr(msg, "tool_calls", []) or []})
            for call in calls:
                result = execute_tool(call["name"], call["arguments"])
                # 工具结果（含结构化错误）以 role=tool 回填，模型可见、可改述
                messages.append({"role": "tool", "content": result})
        raise RuntimeError(f"工具调用轮数超过上限 {MAX_TOOL_ROUNDS}")


# ============================================================
# self-test（6 项）
# ============================================================

def run_self_test() -> bool:
    """验证 safe_eval 白名单 / 工具错误结构化 / 真实工具链 / 模型级回退 / 直答"""
    ok = True
    manager = ToolAgentManager()

    print("\n" + "=" * 60)
    print("  char13-03 工具调用链与异常回退机制 —— Self Test")
    print("=" * 60)

    # Test 1: safe_eval 白名单（对比 eval 的安全洞）
    print("\n--- Test 1: safe_eval 白名单求值 ---")
    try:
        assert safe_eval("7 * (8 + 3)") == 77, "基础四则运算失败"
        assert safe_eval("-3 + 5 * 2") == 7, "一元负号处理失败"
        # 以下三条 eval 会真的执行/计算，safe_eval 必须全部拒绝
        for bad in ["__import__('os').system('echo hacked')", "(lambda: 1)()", "9 ** 9"]:
            try:
                safe_eval(bad)
                raise AssertionError(f"恶意/超纲表达式未被拒绝: {bad}")
            except (ValueError, SyntaxError):
                pass
        print("  [通过] 四则运算正确；__import__/lambda/幂运算全部拒绝——工具内 eval 洞已封")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 2: 工具级错误结构化（不抛异常、不触发模型回退）
    print("\n--- Test 2: 工具级错误结构化返回 ---")
    try:
        r1 = json.loads(execute_tool("query_weather", '{"city": "未知"}'))
        assert r1["success"] is False and "无法获取" in r1["error"], r1
        r2 = json.loads(execute_tool("nonexistent_tool", "{}"))
        assert r2["success"] is False and "未知工具" in r2["error"], r2
        r3 = json.loads(execute_tool("calculate_expression",
                                     '{"expr": "__import__(\'os\').system(\'id\')"}'))
        assert r3["success"] is False and "表达式有误" in r3["error"], r3
        print(f"  [通过] 未知城市 / 未知工具 / 恶意表达式均返回结构化错误: {r3}")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 3: 真实天气工具调用链（教材输入 1）
    print("\n--- Test 3: 天气工具链（qwen-plus 原生 function calling）---")
    try:
        manager.attempted_slots = []
        result = manager.run_with_tools("帮我查一下北京的天气")
        assert result and "调用失败" not in result, result
        assert manager.attempted_slots == ["primary"], f"不应触发回退: {manager.attempted_slots}"
        print(f"  [通过] {result[:60]}（未触发模型回退）")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 4: 真实计算工具调用链（教材输入 2）
    print("\n--- Test 4: 计算工具链 ---")
    try:
        manager.attempted_slots = []
        result = manager.run_with_tools("计算 7 * (8 + 3)")
        assert "77" in result, f"计算结果应含 77: {result}"
        assert manager.attempted_slots == ["primary"], f"不应触发回退: {manager.attempted_slots}"
        print(f"  [通过] {result[:60]}（safe_eval 参与真实链路）")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 5: 模型级回退实测（注入坏模型名强制主模型失败）
    print("\n--- Test 5: 模型级回退（primary 注入坏模型名）---")
    try:
        old = MODEL_REGISTRY["primary"]["model"]
        MODEL_REGISTRY["primary"]["model"] = "nonexistent-model-for-test"
        try:
            manager.attempted_slots = []
            result = manager.run_with_tools("帮我查一下北京的天气")
        finally:
            MODEL_REGISTRY["primary"]["model"] = old   # 无论成败都还原注册表
        assert manager.attempted_slots == ["primary", "backup"], \
            f"回退未发生: {manager.attempted_slots}"
        assert "调用失败" not in result, result
        print(f"  [通过] 主模型失败 → 备用模型接管: {result[:50]}")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 6: 非工具问题直答（教材输入 4，模型不应强行调工具）
    print("\n--- Test 6: 非工具问题直答 ---")
    try:
        manager.attempted_slots = []
        result = manager.run_with_tools("将这段话翻译为英文：你好")
        assert "Hello" in result, f"翻译结果异常: {result}"
        assert manager.attempted_slots == ["primary"], f"不应触发回退: {manager.attempted_slots}"
        print(f"  [通过] {result[:60]}")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    return ok


def run_demo():
    """手动体验入口：教材同款 4 条输入逐条执行"""
    manager = ToolAgentManager()
    inputs = [
        "帮我查一下北京的天气",
        "计算 7 * (8 + 3)",
        "请查一下未知城市的天气",
        "将这段话翻译为英文：你好",
    ]
    for i, text in enumerate(inputs):
        print(f"\n输入{i + 1}：{text}")
        result = manager.run_with_tools(text)
        print("输出结果：", result)


def main():
    """入口：跑 self-test；--demo 进入手动体验"""
    ok = run_self_test()
    print("\n" + "=" * 60)
    print("  全部 6 项 self-test 通过" if ok else "  存在失败项")
    print("=" * 60)
    if "--demo" in sys.argv:
        run_demo()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
