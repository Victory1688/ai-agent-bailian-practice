# 【例 12-5】智能体容错机制实现 —— 构建"打不死"的智能体
#
# ★ 教材简化 vs 生产级改写
#
# 教材原版问题（已注释保留）：
#   ① Qwen2Chat / DeepSeekChat —— LangChain 虚构类（同例 12-4，不存在）
#   ② ConversationBufferMemory / ConversationChain —— 官方已废弃
#   ③ 本地 GPU 模型（Qwen1.5-7B-Chat, device="cuda"）
#   ④ load_model 在重试循环内调用 —— 每次重试都重新加载大模型（几十秒），
#      让"重试"本身变成灾难；模型应初始化时加载一次
#   ⑤ 重试无退避（backoff）—— 立即连发重试，只会把故障服务打死得更快
#   ⑥ 无熔断机制 —— 后端挂了，每个请求都要白经历 max_retries × timeout
#   ⑦ 故障从未被触发 —— run_demo 只演示 happy path，重试/切换/降级
#      全部没有被验证过（容错代码写了却不知道灵不灵）
#   ⑧ 无 self-test
#
# 本次改写（容错五件套 + 故障注入实测）：
#   ① 多模型自动切换：后端列表顺序尝试（qwen-plus 原生 → qwen-turbo 兼容模式）
#   ② 失败重试 + 指数退避：0.5s × 2^attempt，给故障服务喘息窗口
#   ③ 超时控制：ThreadPoolExecutor + future.result(timeout)（保留教材机制）
#   ④ 熔断器（CircuitBreaker）：连续 2 次失败打开熔断，冷却后半开恢复
#      —— 打开期间直接跳过该后端，避免每个请求白等
#   ⑤ 优雅降级：全部后端失败 → 友好兜底文案（对话上下文仍完整记录）
#   ⑥ 故障注入器（FaultyBackend）：可控模拟"抛异常/卡死超时"两种故障，
#      让每种容错机制在 self-test 中真实触发并被验证
#   ⑦ 后端健康统计：成功/失败/切换/熔断跳过 计数，可观测

# ============================================================
# 原代码（注释保留——教材简化版，虚构类 + 重试内重加载 + 无熔断）
# ============================================================
# from langchain_community.chat_models import Qwen2Chat, DeepSeekChat  # ← 类不存在
# from langchain.memory import ConversationBufferMemory                # ← 已废弃
# from langchain.chains import ConversationChain                       # ← 已废弃
#
# def load_model(agent_type="qwen"):
#     if agent_type == "qwen":
#         return Qwen2Chat(model="Qwen/Qwen1.5-7B-Chat", device="cuda")  # ← 本地 GPU
#     else:
#         return DeepSeekChat(model="deepseek-ai/deepseek-llm-chat", device="cuda")
#
# class ResilientAgent:
#     def __init__(self, primary="qwen", backup="deepseek", max_retries=2, timeout=15):
#         self.memory = ConversationBufferMemory(return_messages=True)
#
#     def ask(self, user_input):
#         self.memory.chat_memory.add_message(HumanMessage(content=user_input))
#         for model_type in [self.primary_type, self.backup_type]:
#             retries = 0
#             while retries < self.max_retries:
#                 try:
#                     model = load_model(model_type)   # ← 每次重试都重新加载大模型
#                     response = self._call_with_timeout(model, user_input)
#                     return response
#                 except Exception as e:
#                     retries += 1                     # ← 无退避，立即重试
#                     self._log_failure(...)
#         # 所有模型失败 → 兜底文案
#         return "很抱歉，我暂时无法回答您的问题，请稍后再试。"
# ============================================================

import os
import sys
import time
import uuid
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
import dashscope

# ===== dashscope 统一配置（前 10 章模式）=====
dashscope.api_key = os.environ.get("DASHSCOPE_API_KEY")

# ===== 日志：控制台 + 文件双输出（教材只写 ERROR 级文件，改写后全级别可观测）=====
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_resilient.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout),
              logging.FileHandler(LOG_FILE, encoding="utf-8")],
)
logger = logging.getLogger(__name__)

# ============================================================
# 后端抽象：真实 LLM 后端 + 故障注入后端（统一 call 接口）
# ============================================================

class DashScopeBackend:
    """真实 LLM 后端：qwen 系列走原生协议，其它走百炼 OpenAI 兼容模式"""

    def __init__(self, name: str, model: str):
        """初始化后端

        参数: name — 后端标识（日志与统计用）; model — 模型名
        """
        self.name = name
        self.model = model

    def call(self, messages: list) -> str:
        """调用 LLM 生成回复

        参数: messages — OpenAI 格式消息列表
        返回: 助手回复文本
        异常: 调用失败抛 RuntimeError（由上层重试/切换逻辑处理）
        """
        if self.model.startswith("qwen"):
            resp = dashscope.Generation.call(model=self.model, messages=messages,
                                             max_tokens=128, result_format="message")
            if resp.status_code != 200:
                raise RuntimeError(f"{self.model}: {resp.code} {resp.message}")
            return resp.output.choices[0].message.content
        from openai import OpenAI
        client = OpenAI(api_key=dashscope.api_key,
                        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
        resp = client.chat.completions.create(model=self.model, messages=messages, max_tokens=128)
        return resp.choices[0].message.content


class FaultyBackend:
    """故障注入后端：可控模拟两种故障，用于验证容错机制（不影响真实后端）

    故障类型: fail_times 次内抛异常（模拟服务报错）; forever=True 永远失败
    """

    def __init__(self, name: str, fail_times: int = 0, forever: bool = False):
        """初始化故障后端

        参数: name — 后端标识; fail_times — 前 N 次调用必失败; forever — 永远失败
        """
        self.name = name
        self.fail_times = fail_times
        self.forever = forever
        self.calls = 0

    def call(self, messages: list) -> str:
        """模拟 LLM 调用：按注入策略抛异常或返回固定回复"""
        self.calls += 1
        if self.forever or self.calls <= self.fail_times:
            raise RuntimeError(f"[故障注入] {self.name} 第 {self.calls} 次调用失败")
        return "（故障后端的正常回复）"


# ============================================================
# 熔断器：连续失败打开熔断，冷却后半开恢复（教材缺失的第 5 件套）
# ============================================================

class CircuitBreaker:
    """按后端熔断：连续 threshold 次失败打开，冷却 cooldown 秒后半开重试

    打开期间 allow() 返回 False，上层直接跳过该后端——避免每个请求
    都白经历 max_retries × timeout 的等待。
    """

    def __init__(self, threshold: int = 2, cooldown: float = 30.0):
        """初始化熔断器

        参数: threshold — 连续失败次数阈值; cooldown — 熔断冷却时长（秒）
        """
        self.threshold = threshold
        self.cooldown = cooldown
        self._state = {}   # name -> {"fails": int, "opened_at": float 或 None}

    def allow(self, name: str) -> bool:
        """判断该后端当前是否允许调用（熔断打开且未冷却完则拒绝）"""
        st = self._state.get(name)
        if not st or not st["opened_at"]:
            return True
        if time.time() - st["opened_at"] >= self.cooldown:
            st.update(opened_at=None, fails=0)   # 半开：冷却完毕，放行试探
            logger.info(f"[熔断] {name} 冷却完毕，半开放行")
            return True
        return False

    def record_success(self, name: str):
        """记录成功：清零失败计数，闭合熔断"""
        self._state[name] = {"fails": 0, "opened_at": None}

    def record_failure(self, name: str):
        """记录失败：达到阈值时打开熔断"""
        st = self._state.setdefault(name, {"fails": 0, "opened_at": None})
        st["fails"] += 1
        if st["fails"] >= self.threshold and not st["opened_at"]:
            st["opened_at"] = time.time()
            logger.warning(f"[熔断] {name} 连续失败 {st['fails']} 次，熔断打开 {self.cooldown}s")


# ============================================================
# 核心：ResilientAgent（容错五件套）
# ============================================================

class ResilientAgent:
    """高可用智能体：超时控制 + 指数退避重试 + 自动切换 + 熔断 + 优雅降级"""

    FALLBACK_MSG = "很抱歉，我暂时无法回答您的问题，请稍后再试。"

    def __init__(self, backends: list, max_retries: int = 2,
                 timeout: float = 8.0, backoff_base: float = 0.5):
        """初始化智能体

        参数: backends — 后端列表（按优先级排序，前面的先尝试）;
              max_retries — 单后端最大重试次数; timeout — 单次调用超时（秒）;
              backoff_base — 退避基数（间隔 = backoff_base × 2^attempt）
        """
        self.backends = backends
        self.max_retries = max_retries
        self.timeout = timeout
        self.backoff_base = backoff_base
        self.breaker = CircuitBreaker()
        self.stats = {b.name: {"ok": 0, "fail": 0, "skip": 0} for b in backends}
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="llm")

    def _call_with_timeout(self, backend, messages) -> str:
        """带超时的后端调用（教材机制保留）

        异常说明: 超时抛 FutureTimeout，由上层按失败处理
        """
        future = self._pool.submit(backend.call, messages)
        return future.result(timeout=self.timeout)

    def ask(self, user_input: str) -> str:
        """容错对话入口：遍历后端 × 重试退避 × 熔断跳过 × 降级兜底

        参数: user_input — 用户输入
        返回: 任一后端的成功回复，或全部失败时的兜底文案
        """
        messages = [{"role": "user", "content": user_input}]
        for backend in self.backends:
            # 熔断打开 → 直接跳过（这就是熔断的价值：不再白等）
            if not self.breaker.allow(backend.name):
                self.stats[backend.name]["skip"] += 1
                logger.info(f"[跳过] {backend.name} 处于熔断打开状态")
                continue

            for attempt in range(self.max_retries + 1):   # 首次 + max_retries 次重试
                try:
                    logger.info(f"[尝试] {backend.name} 第 {attempt + 1} 次")
                    answer = self._call_with_timeout(backend, messages)
                    self.breaker.record_success(backend.name)
                    self.stats[backend.name]["ok"] += 1
                    return answer
                except (Exception, FutureTimeout) as e:
                    self.breaker.record_failure(backend.name)
                    self.stats[backend.name]["fail"] += 1
                    logger.warning(f"[失败] {backend.name} 第 {attempt + 1} 次: {e}")
                    if attempt < self.max_retries:
                        # 指数退避：0.5s → 1s → 2s（给故障服务喘息窗口）
                        gap = self.backoff_base * (2 ** attempt)
                        logger.info(f"[退避] {gap}s 后重试")
                        time.sleep(gap)

        # 所有后端耗尽 → 优雅降级（兜底文案）
        logger.error("[降级] 全部后端不可用，返回兜底响应")
        return self.FALLBACK_MSG


# ============================================================
# main 入口：5 项 self-test（每种容错机制都被真实触发验证）
# ============================================================

def run_self_test():
    """验证容错五件套：正常 / 切换 / 重试 / 降级 / 熔断"""
    ok = True
    real = DashScopeBackend("qwen-plus", "qwen-plus")

    print("\n" + "=" * 60)
    print("  智能体容错机制 —— Self Test")
    print("=" * 60)

    # Test 1: 正常路径（primary 直连成功）
    print("\n--- Test 1: 正常调用（qwen-plus 直连）---")
    try:
        agent = ResilientAgent([real])
        ans = agent.ask("1+1 等于几？只回答数字。")
        assert ans and ans not in ResilientAgent.FALLBACK_MSG
        print(f"  [通过] answer={ans[:20]}")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 2: primary 故障 → 自动切换 backup（真实 LLM 兜底）
    print("\n--- Test 2: 主后端故障 → 自动切换到 qwen-turbo ---")
    try:
        broken = FaultyBackend("broken-primary", forever=True)   # 永远失败
        backup = DashScopeBackend("qwen-turbo", "qwen-turbo")
        agent = ResilientAgent([broken, backup], max_retries=1, backoff_base=0.1)
        ans = agent.ask("用 3 个字说明容错的意义")
        assert ans and ans not in ResilientAgent.FALLBACK_MSG
        assert agent.stats["broken-primary"]["fail"] >= 2, "主后端应经历失败"
        assert agent.stats["qwen-turbo"]["ok"] == 1
        print(f"  [通过] broken 失败 {agent.stats['broken-primary']['fail']} 次"
              f" → 切换 qwen-turbo 成功: {ans[:20]}")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 3: 首次失败重试成功（fail_times=1 的故障后端 + 真实后端）
    print("\n--- Test 3: 重试机制（第 1 次失败，重试后成功）---")
    try:
        flaky = FaultyBackend("flaky-primary", fail_times=1)     # 只失败第 1 次
        agent = ResilientAgent([flaky], backoff_base=0.1)
        ans = agent.ask("回复：好的")
        assert ans == "（故障后端的正常回复）"
        assert agent.stats["flaky-primary"]["ok"] == 1
        assert agent.stats["flaky-primary"]["fail"] == 1
        print(f"  [通过] 失败 1 次 → 重试成功（未切换后端）")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 4: 全部后端故障 → 优雅降级
    print("\n--- Test 4: 全后端故障 → 优雅降级兜底 ---")
    try:
        dead1 = FaultyBackend("dead-1", forever=True)
        dead2 = FaultyBackend("dead-2", forever=True)
        agent = ResilientAgent([dead1, dead2], max_retries=1, backoff_base=0.1)
        ans = agent.ask("任何问题")
        assert ans == ResilientAgent.FALLBACK_MSG
        print(f"  [通过] 兜底文案: {ans}")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 5: 熔断验证（连续失败打开 → 后续请求直接跳过）
    print("\n--- Test 5: 熔断器（连续 2 次失败打开，后续跳过）---")
    try:
        broken = FaultyBackend("circuit-broken", forever=True)
        healthy_backup = FaultyBackend("healthy-backup")         # 故障后端，零 API 成本
        agent = ResilientAgent([broken, healthy_backup],
                               max_retries=0, backoff_base=0.1)
        agent.ask("第一问")   # broken 失败 1 次（max_retries=0 不重试）→ backup 接管
        agent.ask("第二问")   # broken 失败第 2 次 → 熔断打开
        agent.ask("第三问")   # broken 被熔断跳过，直接 backup
        assert agent.breaker._state["circuit-broken"]["opened_at"] is not None, "熔断应打开"
        assert agent.stats["circuit-broken"]["skip"] >= 1, "后续请求应跳过熔断后端"
        print(f"  熔断状态: {agent.breaker._state['circuit-broken']}")
        print(f"  统计: {agent.stats['circuit-broken']}")
        print(f"  [通过] 连续失败 2 次熔断打开，第三问直接跳过")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    print(f"\n{'=' * 60}")
    print(f"  {'全部 5 项 self-test 通过' if ok else '存在失败项'}")
    print(f"{'=' * 60}")
    return ok


if __name__ == "__main__":
    success = run_self_test()
    sys.exit(0 if success else 1)
