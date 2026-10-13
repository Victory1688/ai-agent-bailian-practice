# 第13章 项目案例：从零实现一个复合智能体系统
# 【例13-8】LangChain 的通用 Agent 主控链条
#
# ★ 教材简化 vs 生产级改写
#
# 教材原版问题（已注释保留）：
#   ① 标题又写"Qwen3.0"，代码是 Qwen/Qwen1.5-7B-Chat —— 标题内容不符
#   ② Qwen2Chat / DeepSeekChat 虚构类 + langchain.schema 过时 import
#      （同 13-01，import 即崩）
#   ③ Tool.from_function 重复包装 @tool 产物 —— @tool 装饰器已返回
#      StructuredTool 实例，再包一层是双重包装（13-03 同款教材通病）
#   ④ AgentType.OPENAI_FUNCTIONS / initialize_agent / AgentExecutor /
#      ConversationBufferMemory —— LangChain legacy 全线废弃（1.x 已移除，
#      官方推荐 LangGraph 或原生 function calling）
#   ⑤ 【最严重】回退形同虚设：executor 持有的是裸 qwen 实例
#      （llm=self.model.qwen，注释自曝"切换在外部处理"），AgentExecutor
#      内部调模型不经过 ModelWithFallback.invoke——回退代码写了等于没写；
#      且全败时返回"系统暂时无法响应"字符串混流
#   ⑥ "月球"用例：工具 raise ValueError 且未配置 handle_tool_error ——
#      异常炸穿 executor → 进 except 返回"调用失败"，教材预期输出实际跑不出来；
#      工具错误本应回填给模型让它自行调整（13-03 已确立的双层语义）
#   ⑦ traceback.format_exc() print 外泄（13-01 同款）
#   ⑧ 无 self-test
#
# 本次改写（复用例 13-03 已验证模式，聚焦"主控"三件套）：
#   ① dashscope 原生 function calling 手写最小工具循环——彻底摆脱
#      legacy LangChain；_extract_tool_calls 兼容实测两种形态
#      （未调工具时无 tool_calls 属性 / 调工具时元素是 dict）
#   ② 主备回退内嵌在模型调用层（MODEL_REGISTRY 主备槽位循环）——
#      每一轮循环内的 LLM 调用都受回退保护，修复教材"回退与 executor
#      完全脱节"的假回退；attempted_slots 留痕供 self-test 验证
#   ③ 工具错误结构化回填：execute_tool 捕获一切异常，以 tool 角色
#      消息回填给同一模型（错误是数据，链路不断）——"月球"场景实测
#      模型会收到"未找到对应城市"并生成致歉说明，而非整体失败
#   ④ 多轮记忆：self.history 注入 messages（替代废弃的
#      ConversationBufferMemory；13-05 同款，存 user 原话 + assistant 终答）
#   ⑤ 可观测性：run 返回 {"success", "reply", "steps"}，steps 记录每轮
#      工具调用（替代教材 verbose=True 的布尔开关）
#   ⑥ self-test 5 项：工具单测 / 温度链路 / 乘法与多轮记忆 /
#      工具错误回填（月球场景对照）/ 主备回退实测

# ============================================================
# 原代码（注释保留——教材简化版，假回退 + 废弃 Chain + 工具异常炸穿）
# ============================================================
# # 【例13-8】
# # -*- coding:utf-8 -*-
# # LangChain主控Agent集成（Qwen3.0 + Deepseek + 多工具 + 记忆链）
# # 多工具，内存管理及异常回退机制，实现语言驱动的多工具自动执行流程与自然语言响应能力。
#
# import traceback
# from typing import Optional
# from langchain.agents import initialize_agent, Tool, AgentType   # ← legacy 已废弃
# from langchain.agents.agent import AgentExecutor                 # ← legacy 已废弃
# from langchain.memory import ConversationBufferMemory            # ← 已废弃
# from langchain_community.chat_models import Qwen2Chat, DeepSeekChat  # ← 虚构类
# from langchain_core.tools import tool
#
# # 一、定义工具函数（可扩展多个）
# @tool
# def get_temperature(city: str) -> str:
#     """根据城市名称获取当前温度（模拟）"""
#     if city.lower() == "月球":
#         raise ValueError("未找到对应城市")
#     return f"{city}当前温度为26°C"
#
# @tool
# def multiply(a: str, b: str) -> str:
#     """将两个数字相乘"""
#     try:
#         return str(float(a) * float(b))
#     except:                              # ← 裸 except：连 KeyboardInterrupt 都吞
#         return "输入格式不正确，请输入数字"
#
# TOOLS = [
#     Tool.from_function(get_temperature),  # ← @tool 已是 StructuredTool，双重包装
#     Tool.from_function(multiply),
# ]
#
# # 二、定义支持LangChain的模型加载器
# class ModelWithFallback:
#     def __init__(self):
#         self.qwen = Qwen2Chat(model="Qwen/Qwen1.5-7B-Chat")          # ← 虚构
#         self.deepseek = DeepSeekChat(model="deepseek-ai/deepseek-llm-chat")
#
#     def invoke(self, messages):
#         try:
#             return self.qwen(messages)
#         except Exception as e:
#             print("[WARN] Qwen调用失败，尝试Deepseek")
#             try:
#                 return self.deepseek(messages)
#             except Exception:
#                 print("[ERROR] 所有模型调用失败")
#                 return "系统暂时无法响应"          # ← 错误字符串混流
#
# # 三、构建主控Agent逻辑
# class LangChainAgent:
#     def __init__(self):
#         self.model = ModelWithFallback()
#         self.memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)
#         self.executor: Optional[AgentExecutor] = None
#         self._init_agent()
#
#     def _init_agent(self):
#         self.executor = initialize_agent(
#             tools=TOOLS,
#             llm=self.model.qwen,   # ← 裸实例！回退与 executor 完全脱节（假回退）
#             agent=AgentType.OPENAI_FUNCTIONS,   # ← legacy Agent 类型
#             memory=self.memory,
#             verbose=True,
#             handle_parsing_errors=True
#         )
#
#     def run(self, input_text: str) -> str:
#         try:
#             result = self.executor.run(input_text)
#             return result
#         except Exception as e:
#             print("[ERROR] 执行出错:", traceback.format_exc())   # ← 堆栈外泄
#             return "调用失败，请稍后重试"
# ============================================================

import os
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
MAX_TOKENS = 512
MAX_TOOL_ROUNDS = 5    # 工具循环轮次上限（防无限循环，13-03 同款）

# 模型注册表：主备槽位（延续 13-04/13-05 模式，回退在调用层真实生效）
# 注：实测当前百炼账号未开通 DeepSeek 托管，备用槽位用 qwen-turbo 演示
MODEL_REGISTRY = {
    "primary": {"model": "qwen-plus"},
    "backup": {"model": "qwen-turbo"},
}

# ===== 工具定义（教材两个工具，逻辑原样保留）=====
# 注意外层 {"type": "function", "function": {...}} 包装：dashscope 原生
# Generation API 的 tools 参数要求此格式；实测传 OpenAI 风格的裸 function
# 列表会被静默忽略——模型看不到工具定义，凭先验自造工具名（get_weather）
TOOLS_SPEC = [
    {"type": "function", "function": {
        "name": "get_temperature",
        # 描述刻意强化"必须调用"指引：避免模型对"月球天气"直接拒答不调工具
        "description": "查询指定城市的天气情况与当前温度。"
                       "涉及任何城市、地点的天气或温度问题时，必须调用本工具获取，"
                       "不要凭记忆回答；未收录的城市会由工具返回错误。",
        "parameters": {"type": "object",
                       "properties": {"city": {"type": "string", "description": "城市名称"}},
                       "required": ["city"]}}},
    {"type": "function", "function": {
        "name": "multiply",
        "description": "将两个数字相乘",
        "parameters": {"type": "object",
                       "properties": {"a": {"type": "string", "description": "数字a"},
                                      "b": {"type": "string", "description": "数字b"}},
                       "required": ["a", "b"]}}},
]


# ============================================================
# 组件 1：工具实现与注册表（教材逻辑原样，双重包装移除）
# ============================================================

def get_temperature(city: str) -> str:
    """根据城市名称获取当前温度（模拟）——教材原逻辑：月球抛错

    参数: city — 城市名称
    返回: 温度描述文本
    异常: ValueError — 城市未收录（由 execute_tool 捕获回填）
    """
    if city.lower() == "月球":
        raise ValueError("未找到对应城市")
    return f"{city}当前温度为26°C"


def multiply(a: str, b: str) -> str:
    """将两个数字相乘——教材原逻辑（裸 except 收敛为 except Exception）

    参数: a, b — 数字字符串（模型传入）
    返回: 乘积字符串；格式非法返回提示
    """
    try:
        return str(float(a) * float(b))
    except Exception:
        return "输入格式不正确，请输入数字"


TOOL_IMPLS = {
    "get_temperature": get_temperature,
    "multiply": multiply,
}


def execute_tool(name: str, arguments: dict) -> str:
    """执行工具并结构化回填错误（13-03 确立：错误是数据，链路不断）

    参数: name — 工具名; arguments — 模型生成的参数字典
    返回: 工具输出文本（执行异常时返回错误描述文本）
    """
    if name not in TOOL_IMPLS:
        return f"工具执行失败：未知工具 {name}"
    try:
        return str(TOOL_IMPLS[name](**arguments))
    except Exception as e:
        return f"工具执行失败：{e}"


# ============================================================
# 组件 2：AgentCore —— 主控链条（工具循环 + 主备回退 + 多轮记忆）
# ============================================================

def _extract_tool_calls(message) -> list:
    """提取模型响应中的工具调用（13-03 实测兼容两种形态）

    实测：未调工具时 message 无 tool_calls 属性；调工具时元素是 dict
    （原生协议下也是对象，两种都兼容）

    参数: message — dashscope 返回的 message 对象
    返回: 统一化的 [{"id", "type", "function": {"name", "arguments"}}] 列表
    """
    calls = getattr(message, "tool_calls", None)
    if not calls:
        return []
    out = []
    for tc in calls:
        if isinstance(tc, dict):
            out.append(tc)
        else:
            out.append({"id": tc.id, "type": "function",
                        "function": {"name": tc.function.name,
                                     "arguments": tc.function.arguments}})
    return out


class AgentCore:
    """通用 Agent 主控：LLM 工具循环 × 主备回退 × 多轮记忆 × 步骤留痕

    修复教材三大断裂：回退在模型调用层真实生效（不再脱节）、
    工具错误回填（不再炸穿）、记忆用原生 messages（不再依赖废弃 Memory）
    """

    def __init__(self):
        """初始化主控（多轮记忆 + 回退尝试记录）"""
        self.history: list = []          # 多轮记忆：user 原话 + assistant 终答
        self.attempted_slots: list = []  # 最近一次 run 的模型槽位尝试记录

    def _invoke(self, model_name: str, messages: list):
        """单模型 function calling 调用（dashscope 原生协议）

        参数: model_name — 模型名; messages — 原生格式消息列表
        返回: message 对象（content 与 tool_calls 由调用方提取）
        异常: RuntimeError — 接口非 200（由上层触发回退）
        """
        resp = dashscope.Generation.call(
            model=model_name, messages=messages,
            tools=TOOLS_SPEC, result_format="message")
        if resp.status_code != 200:
            raise RuntimeError(f"{resp.code} {resp.message}")
        return resp.output.choices[0].message

    def _chat_with_fallback(self, messages: list):
        """主备回退执行一轮 LLM 调用（回退在调用层真实生效）

        参数: messages — 当前轮消息列表
        返回: (content, tool_calls) —— content 可能为 None（纯工具轮）
        异常: RuntimeError — 所有模型均失败（由 run 转结构化失败）
        """
        last_err = None
        for slot in ("primary", "backup"):
            self.attempted_slots.append(slot)
            try:
                model = MODEL_REGISTRY[slot]["model"]
                logger.info(f"[模型] 使用 {slot}({model})")
                msg = self._invoke(model, messages)
                return msg.content, _extract_tool_calls(msg)
            except Exception as e:
                last_err = e
                logger.warning(f"[回退] {slot} 模型级失败: {e}")
        raise RuntimeError(f"所有模型均执行失败，最后错误：{last_err}") from last_err

    def run(self, input_text: str) -> dict:
        """主控入口：记忆注入 → 工具循环（含错误回填）→ 终答写记忆

        参数: input_text — 用户输入
        返回: 成功 {"success": True, "reply", "steps"}；
              失败 {"success": False, "steps", "error"}
        """
        steps: list = []
        self.attempted_slots = []
        try:
            # 多轮记忆注入（13-05 同款：历史 + 本轮 user 消息）
            messages = self.history + [{"role": "user", "content": input_text}]
            for round_no in range(1, MAX_TOOL_ROUNDS + 1):
                content, tool_calls = self._chat_with_fallback(messages)
                if not tool_calls:
                    # 终答：本轮 user 与 assistant 终答写入记忆
                    self.history.append({"role": "user", "content": input_text})
                    self.history.append({"role": "assistant", "content": content})
                    return {"success": True, "reply": content, "steps": steps}
                # 工具轮：assistant 消息（含 tool_calls）原样回传，再逐个回填结果
                messages.append({"role": "assistant", "content": content,
                                 "tool_calls": tool_calls})
                for tc in tool_calls:
                    name = tc["function"]["name"]
                    try:
                        args = json.loads(tc["function"]["arguments"] or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    result = execute_tool(name, args)
                    steps.append({"round": round_no, "tool": name,
                                  "args": args, "result": result[:120]})
                    logger.info(f"[工具] 第{round_no}轮 {name}({args}) → {result[:50]}")
                    messages.append({"role": "tool", "tool_call_id": tc["id"],
                                     "content": result})
            return {"success": False, "steps": steps,
                    "error": f"超过最大工具轮次（{MAX_TOOL_ROUNDS}）"}
        except Exception as e:
            logger.error(f"[主控] 执行失败: {e}")
            return {"success": False, "steps": steps, "error": str(e)}


# ============================================================
# self-test（5 项）
# ============================================================

def run_self_test() -> bool:
    """验证工具单测 / 真实链路 / 多轮记忆 / 工具错误回填 / 主备回退"""
    ok = True

    print("\n" + "=" * 60)
    print("  char13-08 LangChain 的通用 Agent 主控链条 —— Self Test")
    print("=" * 60)

    # Test 1: 工具单测（教材逻辑原样验证）
    print("\n--- Test 1: 工具单测与错误回填 ---")
    try:
        assert get_temperature("北京") == "北京当前温度为26°C", "温度工具输出不符"
        # 教材原逻辑 str(float*float) 输出 "56.0"（带小数点），此处按数值断言
        assert float(multiply("7", "8")) == 56.0, "乘法结果不符"
        assert "输入格式不正确" in multiply("a", "b"), "非法输入提示缺失"
        assert execute_tool("get_temperature", {"city": "月球"}) == "工具执行失败：未找到对应城市", "异常未回填"
        assert "未知工具" in execute_tool("no_such", {}), "未知工具未拦截"
        print("  [通过] 温度/乘法正常（str(float) 结果为 56.0 属教材原样）；月球异常被回填；未知工具拦截")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 2: 真实工具链路（温度）
    print("\n--- Test 2: 温度查询链路（qwen-plus）---")
    try:
        agent = AgentCore()
        result = agent.run("请帮我查询北京的当前温度")
        assert result["success"] and "26" in result["reply"], result
        assert any(s["tool"] == "get_temperature" for s in result["steps"]), result["steps"]
        # 工具循环含 2 轮 LLM 调用（调工具轮 + 终答轮），全部命中 primary 未触发回退
        assert set(agent.attempted_slots) == {"primary"}, agent.attempted_slots
        print(f"  [通过] {result['reply'][:44]}...（steps 已留痕）")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 3: 乘法链路 + 多轮记忆（"再"字接续，同一实例）
    print("\n--- Test 3: 乘法与多轮记忆 ---")
    try:
        agent = AgentCore()
        r1 = agent.run("将7和8相乘是多少")
        assert r1["success"] and "56" in r1["reply"], r1
        r2 = agent.run("再帮我乘一下12和13")
        assert r2["success"] and "156" in r2["reply"], r2
        print(f"  [通过] 第一轮 7×8=56；第二轮（'再'接续）12×13=156——记忆生效")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 4: 工具错误回填（月球场景——教材版此场景整体失败）
    # 注意 LLM 非确定性：模型可能调工具（路径A：错误回填后致歉），
    # 也可能用自身知识直接解释月球无天气（路径B）——两种均为合理行为，
    # 只验契约；回填机制本身已由 Test 1 的 execute_tool 单测确定性覆盖
    print("\n--- Test 4: 月球场景（错误回填 / 直答均为合理路径）---")
    try:
        agent = AgentCore()
        result = agent.run("请查一下月球的天气")
        assert result["success"] and result["reply"], result
        if any("未找到对应城市" in s["result"] for s in result["steps"]):
            print(f"  [通过] 路径A（调工具→回填→致歉）: {result['reply'][:40]}...")
        else:
            print(f"  [通过] 路径B（模型直答月球无天气，LLM 非确定行为）: {result['reply'][:40]}...")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 5: 主备回退实测（注入坏模型名）
    print("\n--- Test 5: 模型级回退（primary 注入坏模型名）---")
    try:
        old = MODEL_REGISTRY["primary"]["model"]
        MODEL_REGISTRY["primary"]["model"] = "nonexistent-model-for-test"
        try:
            agent = AgentCore()
            result = agent.run("将7和8相乘是多少")
        finally:
            MODEL_REGISTRY["primary"]["model"] = old   # 无论成败都还原注册表
        assert agent.attempted_slots, "无回退记录"
        # 工具循环每轮 LLM 调用都独立回退：切成 (primary, backup) 对逐对校验
        pairs = list(zip(agent.attempted_slots[::2], agent.attempted_slots[1::2]))
        assert len(agent.attempted_slots) % 2 == 0 and \
            all(pair == ("primary", "backup") for pair in pairs), \
            f"回退对异常: {agent.attempted_slots}"
        assert result["success"] and "56" in result["reply"], result
        print(f"  [通过] 循环内每轮 LLM 调用均 primary失败→backup接管（共 {len(pairs)} 轮）: "
              f"{result['reply'][:36]}...")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    return ok


def run_demo():
    """手动体验入口：教材同款 4 条输入"""
    agent = AgentCore()
    inputs = [
        "请帮我查询北京的当前温度",
        "将7和8相乘是多少",
        "请查一下月球的天气",
        "再帮我乘一下12和13",
    ]
    for i, text in enumerate(inputs):
        print(f"\n输入{i + 1}：{text}")
        result = agent.run(text)
        if result["success"]:
            print("输出结果：", result["reply"])
            if result["steps"]:
                print("执行步骤：", [(s["tool"], s["args"]) for s in result["steps"]])
        else:
            print("[失败]", result["error"])


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
