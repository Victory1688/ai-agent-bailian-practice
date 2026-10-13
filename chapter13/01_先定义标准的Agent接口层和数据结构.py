# 第13章 项目案例：从零实现一个复合智能体系统
# 【例13-1】先定义标准的 Agent 接口层和数据结构
#
# ★ 教材简化 vs 生产级改写
#
# 教材原版问题（已注释保留）：
#   ① Qwen2Chat / DeepSeekChat —— LangChain 社区库虚构类（char12 已验证
#      不存在，from langchain_community.chat_models import 会直接 ImportError）
#   ② from langchain.schema import ... —— import 路径已迁移（新版在
#      langchain_core.messages），且本项目统一用 dashscope 原生协议，
#      不经 LangChain 中转
#   ③ 本地 GPU 模型（Qwen1.5-7B-Chat / deepseek-llm-chat）—— 无 API
#      Key 即可运行是假的；且两个模型名均非云端托管格式
#   ④ run_demo 每次对话都 new 一个 ModelAdapter —— 若构造函数真的加载
#      大模型，等于每轮对话重新加载（char12-05 踩过的同款坑）；
#      适配器应注册/复用，而不是用完即弃
#   ⑤ Message 角色校验延迟到 to_langchain() —— 坏数据先入列、后报错，
#      违反 fail fast；应在构造消息时就校验
#   ⑥ traceback 原样返回给调用方 —— 生产环境把堆栈暴露给客户端属于
#      信息泄露，错误信息应止于日志
#   ⑦ 无 self-test —— 接口层的正确性全靠肉眼
#
# 本次改写（dashscope 原生协议 + 适配器注册表 + fail fast）：
#   ① Message：构造时白名单校验 role（user/assistant/system），提供
#      to_dict() 序列化（为后续篇章落盘 cache.json 铺垫）
#   ② ConversationContext：会话上下文容器，as_dict() 输出 dashscope
#      原生 messages 格式（不再需要 to_langchain 中转层）
#   ③ ModelAdapter：模型注册表驱动（注册表含模型名 + 协议类型），
#      统一 call(context) 接口屏蔽协议差异：
#      - qwen → qwen-plus（dashscope 原生协议）
#      - deepseek → 实测当前百炼账号未开通 DeepSeek 托管（deepseek-*
#        模型 404），改用 qwen-turbo + OpenAI 兼容协议演示跨模型切换；
#        若账号开通 deepseek-v3，把注册表里的 model 改回即可
#   ④ get_adapter 适配器池：实例复用，不重复构造（修复教材④）
#   ⑤ self-test 5 项：role 校验 / 上下文结构 / 未知模型拒绝 /
#      qwen 真实调用 / 跨模型共享上下文（"它"指代验证）

# ============================================================
# 原代码（注释保留——教材简化版，虚构类 + 过时 import + 重复加载）
# ============================================================
# # -*- coding:utf-8 -*-
# import uuid
# import traceback
# from typing import List, Dict, Any
# from langchain_community.chat_models import Qwen2Chat, DeepSeekChat  # ← 虚构类
# from langchain.schema import HumanMessage, AIMessage, SystemMessage  # ← 路径已迁移
#
# # 一、统一上下文结构定义
# class Message:
#     def __init__(self, role: str, content: str):
#         self.role = role
#         self.content = content
#
#     def to_langchain(self):
#         if self.role == "user":
#             return HumanMessage(content=self.content)
#         elif self.role == "assistant":
#             return AIMessage(content=self.content)
#         elif self.role == "system":
#             return SystemMessage(content=self.content)
#         else:
#             raise ValueError(f"不支持的角色类型：{self.role}")   # ← 校验太晚
#
# # 二、标准化上下文管理
# class ConversationContext:
#     def __init__(self, session_id=None):
#         self.session_id = session_id or str(uuid.uuid4())
#         self.messages: List[Message] = []
#
#     def add_message(self, role, content):
#         self.messages.append(Message(role, content))
#
#     def get_langchain_messages(self):
#         return [msg.to_langchain() for msg in self.messages]
#
#     def as_dict(self):
#         return [{"role": msg.role, "content": msg.content} for msg in self.messages]
#
# # 三、模型适配器封装
# class ModelAdapter:
#     def __init__(self, model_type="qwen"):
#         self.model_type = model_type
#         self.model = self._load_model(model_type)      # ← 构造即加载大模型
#
#     def _load_model(self, model_type):
#         if model_type == "qwen":
#             return Qwen2Chat(model="Qwen/Qwen1.5-7B-Chat")       # ← 虚构
#         elif model_type == "deepseek":
#             return DeepSeekChat(model="deepseek-ai/deepseek-llm-chat")  # ← 虚构
#         else:
#             raise ValueError("不支持的模型类型")
#
#     def call(self, context: ConversationContext):
#         try:
#             messages = context.get_langchain_messages()
#             response = self.model(messages)
#             return {"success": True, "response": response.content}
#         except Exception as e:
#             return {"success": False, "error": str(e),
#                     "traceback": traceback.format_exc()}  # ← 堆栈外泄
#
# # 四、实际应用示例
# def run_demo():
#     ...
#     adapter = ModelAdapter(model_type="qwen")      # ← 每轮 new，不复用
#     ...
#     adapter2 = ModelAdapter(model_type="deepseek")
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
VALID_ROLES = ("user", "assistant", "system")   # 消息角色白名单（fail fast）
MAX_TOKENS = 256

# ===== 模型注册表：类型 → (模型名, 协议) =====
# 注：实测当前百炼账号未开通 DeepSeek 托管（deepseek-* 模型 404），
# 故 deepseek 槽位用 qwen-turbo + OpenAI 兼容协议演示跨模型切换；
# 若账号开通 deepseek-v3，把 model 改回 "deepseek-v3" 即可
MODEL_REGISTRY = {
    "qwen": {"model": "qwen-plus", "protocol": "native"},      # dashscope 原生协议
    "deepseek": {"model": "qwen-turbo", "protocol": "openai"},  # OpenAI 兼容协议
}

DASHSCOPE_COMPAT_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"


# ============================================================
# 组件 1：Message —— 最小消息单元（构造时即校验，fail fast）
# ============================================================

class Message:
    """标准消息单元：role 白名单校验 + 序列化（教材校验延迟问题在此修复）"""

    def __init__(self, role: str, content: str):
        """构造消息，非法 role 立即抛错

        参数: role — user / assistant / system; content — 消息文本
        异常: ValueError — role 不在白名单
        """
        if role not in VALID_ROLES:
            raise ValueError(f"不支持的角色类型：{role}（合法值 {VALID_ROLES}）")
        self.role = role
        self.content = content

    def to_dict(self) -> dict:
        """序列化为 dashscope 原生 messages 格式的一条"""
        return {"role": self.role, "content": self.content}


# ============================================================
# 组件 2：ConversationContext —— 会话上下文容器
# ============================================================

class ConversationContext:
    """标准化上下文管理：消息追加 + 原生格式导出（跨模型共享历史的数据底座）"""

    def __init__(self, session_id: str = None):
        """初始化上下文

        参数: session_id — 会话标识；缺省自动生成 uuid
        """
        self.session_id = session_id or str(uuid.uuid4())
        self.messages: list = []

    def add_message(self, role: str, content: str) -> Message:
        """追加一条消息并返回（校验委托给 Message 构造器）

        参数: role — 消息角色; content — 消息文本
        返回: 新建的 Message 对象
        异常: ValueError — role 非法（由 Message 抛出）
        """
        msg = Message(role, content)
        self.messages.append(msg)
        return msg

    def as_dict(self) -> list:
        """导出为 dashscope / OpenAI 双兼容的 messages 列表"""
        return [msg.to_dict() for msg in self.messages]


# ============================================================
# 组件 3：ModelAdapter —— 注册表驱动的模型适配器
# ============================================================

class ModelAdapter:
    """模型适配器：统一 call(context) 接口，屏蔽 qwen 原生与 OpenAI 兼容两种协议

    适配器模式要点：上层（ConversationContext / 业务编排）只依赖 call()，
    底层换模型、换协议都不影响调用方——这正是本章"接口层"的题眼。
    """

    def __init__(self, model_type: str):
        """按注册表初始化适配器（只记录配置，不做重加载）

        参数: model_type — 注册表中的模型类型键
        异常: ValueError — 类型未注册
        """
        if model_type not in MODEL_REGISTRY:
            raise ValueError(f"不支持的模型类型：{model_type}（已注册 {list(MODEL_REGISTRY)}）")
        spec = MODEL_REGISTRY[model_type]
        self.model_type = model_type
        self.model_name = spec["model"]
        self.protocol = spec["protocol"]

    def call(self, context: ConversationContext) -> dict:
        """调用模型并返回结构化结果（错误止于日志，堆栈不外泄）

        参数: context — 会话上下文（含完整历史）
        返回: 成功 {"success", "model", "response"} / 失败 {"success", "error"}
        """
        try:
            answer = self._invoke(context.as_dict())
            logger.info(f"[模型] {self.model_type}({self.model_name}/{self.protocol}) 调用成功")
            return {"success": True, "model": self.model_name, "response": answer}
        except Exception as e:
            logger.error(f"[模型] {self.model_type} 调用失败: {e}")
            return {"success": False, "error": str(e)}

    def _invoke(self, messages: list) -> str:
        """按注册协议分发调用

        参数: messages — 原生格式消息列表
        返回: 助手回复文本
        异常: 调用失败抛 RuntimeError / SDK 异常（由 call 统一兜底）
        """
        if self.protocol == "native":
            resp = dashscope.Generation.call(model=self.model_name, messages=messages,
                                             max_tokens=MAX_TOKENS, result_format="message")
            if resp.status_code != 200:
                raise RuntimeError(f"{resp.code} {resp.message}")
            return resp.output.choices[0].message.content
        # OpenAI 兼容协议（deepseek 槽位 / 任意兼容模型）
        from openai import OpenAI
        client = OpenAI(api_key=dashscope.api_key, base_url=DASHSCOPE_COMPAT_BASE)
        resp = client.chat.completions.create(model=self.model_name, messages=messages,
                                              max_tokens=MAX_TOKENS)
        return resp.choices[0].message.content


# ===== 适配器池：实例复用（修复教材每轮 new 的重复构造）=====
_adapter_pool: dict = {}


def get_adapter(model_type: str) -> ModelAdapter:
    """获取（或创建）适配器单例——同一类型全程复用

    参数: model_type — 注册表中的模型类型键
    返回: ModelAdapter 实例
    """
    if model_type not in _adapter_pool:
        _adapter_pool[model_type] = ModelAdapter(model_type)
    return _adapter_pool[model_type]


# ============================================================
# self-test（5 项）
# ============================================================

def run_self_test() -> bool:
    """验证接口层契约：校验 / 结构 / 注册表 / 真实调用 / 跨模型共享上下文"""
    ok = True

    print("\n" + "=" * 60)
    print("  char13-01 标准 Agent 接口层与数据结构 —— Self Test")
    print("=" * 60)

    # Test 1: Message 角色白名单校验（fail fast）
    print("\n--- Test 1: Message role 校验 ---")
    try:
        try:
            Message("robot", "hi")
            raise AssertionError("非法 role 应抛 ValueError")
        except ValueError as e:
            print(f"  [通过] 非法 role 被构造时拦截: {e}")
    except AssertionError as e:
        print(f"  [失败] {e}"); ok = False

    # Test 2: ConversationContext 结构
    print("\n--- Test 2: ConversationContext 结构 ---")
    try:
        ctx = ConversationContext()
        ctx.add_message("system", "你是一个专业的AI助手")
        ctx.add_message("user", "请简要解释什么是注意力机制")
        data = ctx.as_dict()
        assert data[0] == {"role": "system", "content": "你是一个专业的AI助手"}
        assert len(ctx.session_id) == 36, "session_id 应为 uuid"
        print(f"  [通过] as_dict 输出原生格式 {len(data)} 条，session_id 自动生成")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 3: 未注册模型类型拒绝
    print("\n--- Test 3: 未注册模型类型拒绝 ---")
    try:
        try:
            ModelAdapter("gpt-5")
            raise AssertionError("未注册类型应抛 ValueError")
        except ValueError as e:
            print(f"  [通过] {e}")
    except AssertionError as e:
        print(f"  [失败] {e}"); ok = False

    # Test 4: qwen 适配器真实调用（dashscope 原生协议）
    print("\n--- Test 4: qwen 适配器真实调用 ---")
    try:
        ctx = ConversationContext()
        ctx.add_message("system", "你是一个专业的AI助手")
        ctx.add_message("user", "请用一句话解释什么是注意力机制")
        result = get_adapter("qwen").call(ctx)
        assert result["success"], result.get("error")
        assert "traceback" not in result, "堆栈不应外泄"
        print(f"  [通过] model={result['model']} 回复: {result['response'][:50]}...")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 5: 跨模型共享上下文（"它"指代验证，OpenAI 兼容协议）
    print("\n--- Test 5: 跨模型共享上下文 ---")
    try:
        ctx.add_message("user", "它和多头注意力有什么关系？")
        result = get_adapter("deepseek").call(ctx)
        assert result["success"], result.get("error")
        assert "多头" in result["response"] or "注意力" in result["response"], \
            f"回复应承接上文话题: {result['response'][:60]}"
        print(f"  [通过] model={result['model']} 回复: {result['response'][:50]}...")
        print("  [通过] 第二问的'它'正确指代第一问的注意力机制 —— 上下文跨适配器共享")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    return ok


def run_demo():
    """手动体验入口：教材同款双模型对话流程（跨模型共享上下文）"""
    print("=== 示例：使用 qwen 模型进行对话 ===")
    context = ConversationContext()
    context.add_message("system", "你是一个专业的AI助手")
    context.add_message("user", "请简要解释什么是注意力机制")

    result = get_adapter("qwen").call(context)
    if result["success"]:
        print("[qwen-plus 回复]", result["response"])
        context.add_message("assistant", result["response"])
    else:
        print("[qwen 失败]", result["error"])
        return

    print("\n=== 切换到 deepseek 槽位模型继续对话 ===")
    context.add_message("user", "它和多头注意力有什么关系？")
    result2 = get_adapter("deepseek").call(context)
    if result2["success"]:
        print(f"[{result2['model']} 回复]", result2["response"])
    else:
        print("[deepseek 槽位失败]", result2["error"])


def main():
    """入口：跑 self-test 并按结果退出"""
    ok = run_self_test()
    print("\n" + "=" * 60)
    print("  全部 5 项 self-test 通过" if ok else "  存在失败项")
    print("=" * 60)
    if ok:
        print("\n手动体验教材同款流程：python 本文件 --demo")
    if "--demo" in sys.argv:
        run_demo()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
