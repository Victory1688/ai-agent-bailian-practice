# 第13章 项目案例：从零实现一个复合智能体系统
# 【例13-4】子状态管理与任务调度
#
# ★ 教材简化 vs 生产级改写
#
# 教材原版问题（已注释保留）：
#   ① 标题又写"Qwen3.0"，代码里是 Qwen/Qwen1.5-7B-Chat —— 标题内容不符（同 13-03）
#   ② Qwen2Chat / DeepSeekChat 虚构类 + langchain.schema 过时 import
#      （同 13-01，import 即崩）
#   ③ _run_model 的 try/except: raise —— 捕获后原样重抛，零处理零记录，
#      纯噪音代码（"虚假异常处理"：看起来有容错，实际什么都没做）
#   ④ 状态迁移零校验：update() 接受任意字符串，"idle → running → success"
#      的合法路径没有任何约束，可以直接从 idle 跳 success（状态机形同虚设）
#   ⑤ task_type → prompt 的 if/elif 链与 agents 状态注册表是两份平行维护
#      的映射——新增一个子 Agent 要同时改两处；且 if/elif 末尾的
#      raise ValueError("未知任务类型") 是死代码（未注册类型早已被
#      前面的 if not agent 拦截）
#   ⑥ _execute_with_fallback 吞掉原始异常：外层 except 捕获 e 却抛出
#      不带原因的 RuntimeError("所有模型均执行失败")，排查无从下手
#   ⑦ last_result / last_error 记录了但快照不含它们——get_status_snapshot
#      只返回 status，失败后排查拿不到错误原因，状态记录形同摆设
#   ⑧ 无 self-test
#
# 本次改写（状态机白名单 + 单一注册表 + 异常链 + 完整快照）：
#   ① AgentState 状态机：STATUS_TRANSITIONS 显式声明合法迁移
#      （idle→running→success/failed，success/failed→running 允许重派），
#      非法迁移与非法状态值一律 ValueError 拦截（fail fast）
#   ② TASK_REGISTRY 单一注册表：任务类型 → 子 Agent 名称 + 提示词模板，
#      一处定义，消灭 if/elif 平行映射与死代码；模板填充用 replace
#      （例 13-02 的 format 花括号坑经验）
#   ③ 模型调用延续前几篇模式：dashscope 原生协议 + MODEL_REGISTRY 主备
#      （qwen-plus / qwen-turbo），回退原因 logging 落日志，最终
#      RuntimeError 携带原始异常链（raise ... from e）
#   ④ get_status_snapshot 输出完整快照（status + last_result 截断 +
#      last_error），失败排查信息不再丢失
#   ⑤ self-test 5 项：状态机校验 / 未注册类型 / 真实调度与重派 /
#      快照完整性 / 模型级回退实测（注入坏模型名）

# ============================================================
# 原代码（注释保留——教材简化版，虚构类 + 虚假异常处理 + 平行映射）
# ============================================================
# # 【例13-4】
# # -*- coding:utf-8 -*-
# # Agent子系统状态管理与调度机制
# # 支持基于任务意图动态激活智能体子模块，管理其状态迁移，并整合多轮执行结果，
# # 集成Qwen3.0 与 DeepSeek模型作为通用执行单元。
#
# import time
# import uuid
# import traceback
# from typing import Dict, List
# from langchain_community.chat_models import Qwen2Chat, DeepSeekChat  # ← 虚构类
# from langchain.schema import HumanMessage                            # ← 路径过时
#
# # 一、子Agent状态定义
# class AgentState:
#     def __init__(self, name: str):
#         self.name = name
#         self.status = "idle"  # idle, running, success, failed
#         self.last_result = None
#         self.last_error = None
#
#     def update(self, status: str, result=None, error=None):
#         self.status = status          # ← 状态迁移零校验，任意字符串都接受
#         self.last_result = result
#         self.last_error = error
#
# # 二、任务调度控制器
# class AgentController:
#     def __init__(self):
#         self.session_id = str(uuid.uuid4())
#         self.agents: Dict[str, AgentState] = {
#             "intent": AgentState("意图识别Agent"),
#             "qa": AgentState("问答Agent"),
#             "tool": AgentState("工具调用Agent"),
#             "dialog": AgentState("对话Agent"),
#         }
#         self.qwen = Qwen2Chat(model="Qwen/Qwen1.5-7B-Chat")          # ← 虚构
#         self.deepseek = DeepSeekChat(model="deepseek-ai/deepseek-llm-chat")
#
#     def _run_model(self, model, prompt: str) -> str:
#         try:
#             messages = [HumanMessage(content=prompt)]
#             response = model(messages)
#             return response.content.strip()
#         except Exception:             # ← 捕获后原样 raise：虚假异常处理
#             raise
#
#     def _execute_with_fallback(self, prompt: str) -> str:
#         try:
#             return self._run_model(self.qwen, prompt)
#         except Exception as e:
#             print("[WARN] Qwen执行失败，切换至Deepseek")   # ← print 无日志
#             try:
#                 return self._run_model(self.deepseek, prompt)
#             except Exception:
#                 raise RuntimeError("所有模型均执行失败")   # ← 丢失原始原因
#
#     def dispatch_task(self, task_type: str, input_text: str) -> str:
#         agent = self.agents.get(task_type)
#         if not agent:
#             return f"未找到任务类型：{task_type}"
#         agent.update("running")
#         try:
#             if task_type == "intent":                   # ← 与 agents 字典平行
#                 prompt = f"请识别该用户输入的意图：{input_text}"    #   维护的两份映射
#             elif task_type == "qa":
#                 prompt = f"请回答该问题：{input_text}"
#             elif task_type == "tool":
#                 prompt = f"是否需要调用工具来完成该任务？{input_text}"
#             elif task_type == "dialog":
#                 prompt = f"请以自然语言与用户继续交谈：{input_text}"
#             else:
#                 raise ValueError("未知任务类型")        # ← 死代码：永远走不到
#             result = self._execute_with_fallback(prompt)
#             agent.update("success", result=result)
#             return result
#         except Exception as e:
#             agent.update("failed", error=str(e))
#             return f"[ERROR] {agent.name}执行失败：{str(e)}"
#
#     def get_status_snapshot(self) -> Dict[str, str]:
#         return {k: v.status for k, v in self.agents.items()}   # ← 快照缺错误信息
# ============================================================

import os
import sys
import uuid
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

# 模型注册表：主备槽位（延续 13-03 模式，统一 dashscope 原生协议）
# 注：实测当前百炼账号未开通 DeepSeek 托管（deepseek-* 模型 404），
# 备用槽位用 qwen-turbo 演示回退；若开通后改回 "deepseek-v3" 即可
MODEL_REGISTRY = {
    "primary": {"model": "qwen-plus"},
    "backup": {"model": "qwen-turbo"},
}

# ===== 子 Agent 状态机定义 =====
# 合法状态与迁移路径显式声明（教材的 update 无约束，任何跳转都放行）
VALID_STATUSES = ("idle", "running", "success", "failed")
# 迁移白名单：success/failed → running 意味着允许重新派发 / 重试
STATUS_TRANSITIONS = {
    "idle": {"running"},
    "running": {"success", "failed"},
    "success": {"running"},
    "failed": {"running"},
}

# ===== 任务注册表（单一映射：任务类型 → 子 Agent 名称 + 提示词模板）=====
# 教材的 if/elif 链与此处 agents 字典平行维护，新增子 Agent 要改两处；
# 改写后一处定义，教材四类任务的提示词原文保留
TASK_REGISTRY = {
    "intent": {"name": "意图识别Agent",
               "prompt": "请识别该用户输入的意图：{input}"},
    "qa": {"name": "问答Agent",
           "prompt": "请回答该问题：{input}"},
    "tool": {"name": "工具调用Agent",
             "prompt": "是否需要调用工具来完成该任务？{input}"},
    "dialog": {"name": "对话Agent",
               "prompt": "请以自然语言与用户继续交谈：{input}"},
}


# ============================================================
# 组件 1：AgentState —— 带状态机校验的子 Agent 状态
# ============================================================

class AgentState:
    """子 Agent 状态单元：迁移白名单校验（fail fast）+ 完整快照序列化"""

    def __init__(self, name: str):
        """初始化状态单元

        参数: name — 子 Agent 显示名称
        """
        self.name = name
        self.status = "idle"
        self.last_result = None
        self.last_error = None

    def update(self, status: str, result=None, error=None):
        """按白名单迁移状态（非法迁移与非法状态值一律拒绝）

        参数: status — 目标状态（必须在 STATUS_TRANSITIONS 白名单内）;
              result — 成功结果; error — 失败原因
        异常: ValueError — 状态值不在 VALID_STATUSES，或迁移路径不在白名单
        """
        if status not in VALID_STATUSES:
            raise ValueError(f"{self.name} 非法状态值：{status}（合法值 {VALID_STATUSES}）")
        if status not in STATUS_TRANSITIONS[self.status]:
            raise ValueError(f"{self.name} 非法状态迁移：{self.status} → {status}")
        self.status = status
        self.last_result = result
        self.last_error = error

    def to_dict(self) -> dict:
        """完整快照：status + 结果摘要 + 失败原因（教材快照只有 status）

        返回: {"name", "status", "last_result", "last_error"} 字典
        """
        result = self.last_result
        # 结果可能很长，快照里截断到 80 字符保证可读（完整结果由调用方持有）
        if isinstance(result, str) and len(result) > 80:
            result = result[:80] + "..."
        return {"name": self.name, "status": self.status,
                "last_result": result, "last_error": self.last_error}


# ============================================================
# 组件 2：AgentController —— 任务调度控制器（主备回退 + 状态机驱动）
# ============================================================

class AgentController:
    """任务调度控制器：按注册表派发任务、驱动状态机、模型级失败主备回退"""

    def __init__(self):
        """初始化控制器（会话标识 + 各子 Agent 状态单元 + 回退尝试记录）"""
        self.session_id = str(uuid.uuid4())
        # 子 Agent 状态单元与注册表同键（intent/qa/tool/dialog）
        self.agents: dict = {task: AgentState(spec["name"])
                             for task, spec in TASK_REGISTRY.items()}
        self.attempted_slots: list = []   # 记录最近一次派发尝试的模型槽位

    def _run_model(self, model_name: str, prompt: str) -> str:
        """单模型调用（dashscope 原生协议，单轮对话）

        参数: model_name — 模型名; prompt — 完整提示词
        返回: 模型回复文本（已去首尾空白）
        异常: RuntimeError — 接口非 200（由上层统一兜底）
        """
        resp = dashscope.Generation.call(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=MAX_TOKENS, result_format="message")
        if resp.status_code != 200:
            raise RuntimeError(f"{resp.code} {resp.message}")
        return resp.output.choices[0].message.content.strip()

    def _execute_with_fallback(self, prompt: str) -> str:
        """主备模型回退执行（教材语义保留，失败原因不丢失）

        参数: prompt — 完整提示词
        返回: 模型回复文本
        异常: RuntimeError — 所有模型均失败（携带原始异常链）
        """
        last_err = None
        for slot in ("primary", "backup"):
            self.attempted_slots.append(slot)
            try:
                logger.info(f"[模型] 使用 {slot}({MODEL_REGISTRY[slot]['model']}) 执行")
                return self._run_model(MODEL_REGISTRY[slot]["model"], prompt)
            except Exception as e:
                last_err = e
                logger.warning(f"[回退] {slot} 模型级失败: {e}")
        # 教材抛 RuntimeError 但不带原因；改写携带原始异常链便于排查
        raise RuntimeError(f"所有模型均执行失败，最后错误：{last_err}") from last_err

    def dispatch_task(self, task_type: str, input_text: str) -> str:
        """派发任务：查注册表 → 状态机迁移 → 回退执行 → 记录结果

        参数: task_type — 任务类型（注册表键）; input_text — 用户输入
        返回: 任务输出文本（未注册类型返回提示，执行失败返回错误摘要）
        """
        spec = TASK_REGISTRY.get(task_type)
        if not spec:
            # 教材语义保留：未注册类型返回提示（不做静默兜底）
            return f"未找到任务类型：{task_type}"
        state = self.agents[task_type]
        state.update("running")
        try:
            # replace 填充模板（例 13-02 实测：模板含花括号时 format 会误解析）
            prompt = spec["prompt"].replace("{input}", input_text)
            result = self._execute_with_fallback(prompt)
            state.update("success", result=result)
            return result
        except Exception as e:
            logger.error(f"[任务] {spec['name']} 执行失败: {e}")
            state.update("failed", error=str(e))
            return f"[ERROR] {spec['name']}执行失败：{e}"

    def get_status_snapshot(self) -> dict:
        """完整状态快照（含 last_result 摘要与 last_error，替代教材的纯 status 表）

        返回: {任务类型: {"name", "status", "last_result", "last_error"}} 字典
        """
        return {task: state.to_dict() for task, state in self.agents.items()}


# ============================================================
# self-test（5 项）
# ============================================================

def run_self_test() -> bool:
    """验证状态机校验 / 未注册类型 / 真实调度与重派 / 快照完整性 / 模型级回退"""
    ok = True
    controller = AgentController()

    print("\n" + "=" * 60)
    print("  char13-04 子状态管理与任务调度 —— Self Test")
    print("=" * 60)

    # Test 1: 状态机白名单校验
    print("\n--- Test 1: 状态机白名单 ---")
    try:
        st = AgentState("测试Agent")
        st.update("running")
        st.update("success", result="ok")
        st.update("running")           # success → running：允许重派
        assert st.status == "running"
        st2 = AgentState("测试Agent2")
        for bad in ("success", "flying"):   # idle → success 跳步 / 非法状态值
            try:
                st2.update(bad)
                raise AssertionError(f"非法迁移未被拦截: {bad}")
            except ValueError:
                pass
        print("  [通过] 合法链 idle→running→success→running 通过；跳步与非法值全部拦截")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 2: 未注册任务类型
    print("\n--- Test 2: 未注册任务类型 ---")
    try:
        out = controller.dispatch_task("unknown", "随便说点")
        assert "未找到任务类型" in out, out
        assert all(s["status"] == "idle" for s in controller.get_status_snapshot().values()), \
            "未注册类型不应影响任何子 Agent 状态"
        print(f"  [通过] {out}（现有状态不受干扰）")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 3: 真实调度 intent + dialog（含 success → running 重派路径）
    print("\n--- Test 3: 真实调度与重派（qwen-plus）---")
    try:
        out1 = controller.dispatch_task("intent", "我想查一下北京的天气")
        assert out1 and "调用失败" not in out1, out1
        assert controller.attempted_slots == ["primary"], controller.attempted_slots
        out2 = controller.dispatch_task("dialog", "你好，可以和我聊聊人工智能吗？")
        assert out2 and "调用失败" not in out2, out2
        assert controller.agents["dialog"].status == "success"
        print(f"  [通过] intent → {out1[:36]}...；dialog → {out2[:36]}...（重派路径正常）")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 4: 真实调度 qa + 快照完整性
    print("\n--- Test 4: 快照完整性（教材快照缺 last_error 的修复验证）---")
    try:
        controller.dispatch_task("qa", "Transformer的注意力机制原理是什么？")
        snap = controller.get_status_snapshot()
        qa = snap["qa"]
        assert qa["status"] == "success" and qa["last_result"], qa
        assert "name" in qa and "last_error" in qa, f"快照字段不完整: {qa.keys()}"
        print(f"  [通过] qa 快照 = {qa}")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 5: 模型级回退实测（注入坏模型名强制 primary 失败）
    print("\n--- Test 5: 模型级回退（primary 注入坏模型名）---")
    try:
        old = MODEL_REGISTRY["primary"]["model"]
        MODEL_REGISTRY["primary"]["model"] = "nonexistent-model-for-test"
        try:
            controller.attempted_slots = []
            out = controller.dispatch_task("tool", "现在外面温度是多少？")
        finally:
            MODEL_REGISTRY["primary"]["model"] = old   # 无论成败都还原注册表
        assert controller.attempted_slots == ["primary", "backup"], \
            f"回退未发生: {controller.attempted_slots}"
        assert "[ERROR]" not in out and out, out
        assert controller.agents["tool"].status == "success", \
            controller.agents["tool"].to_dict()
        print(f"  [通过] 主模型失败 → 备用接管，子 Agent 状态 success: {out[:40]}...")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    return ok


def run_demo():
    """手动体验入口：教材同款 4 条任务逐条派发"""
    controller = AgentController()
    tasks = [
        ("intent", "我想查一下北京的天气"),
        ("tool", "现在外面温度是多少？"),
        ("qa", "Transformer的注意力机制原理是什么？"),
        ("dialog", "你好，可以和我聊聊人工智能吗？"),
    ]
    for i, (task_type, text) in enumerate(tasks):
        print(f"\n任务{i + 1}：{task_type} → {text}")
        output = controller.dispatch_task(task_type, text)
        print("任务输出：", output)

    print("\n【Agent状态快照】")
    for task, info in controller.get_status_snapshot().items():
        print(f"  {task}: {info}")


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
