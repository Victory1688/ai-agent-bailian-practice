# 【例 12-6】智能体限流与降级系统 —— 高并发下的稳定性保护
#
# ★ 教材简化 vs 生产级改写
#
# 教材原版问题（已注释保留）：
#   ① Redis 令牌桶 —— 本环境无 Redis，按约定改用进程内令牌桶 + cache.json
#      持久化桶状态（防重启凭空回满绕过限流）
#   ② 令牌桶实现有两处 bug：
#      a) 桶初始为空（get or 0）—— 启动后第一批请求全部被拒，正确做法是
#         初始满桶
#      b) get/set/decr 三步非原子 —— 并发请求同时读到同一 token 数，
#         桶会被扣成负数；Redis 正确姿势是 Lua 脚本原子执行
#   ③ Qwen2Chat/DeepSeekChat 虚构类 + ConversationChain 废弃（同例 12-4/05）
#   ④ @app.on_event("startup") 已被 FastAPI 废弃（新版用 lifespan）
#   ⑤ 单消费者 worker —— 吞吐量约 0.5 req/s，队列必然积压
#   ⑥ 限流/削峰/优先级/降级 全部零验证 —— 第七节只有一行启动注释
#   ⑦ worker 异常退出后等待中的 future 永远 pending（请求挂死）
#
# 本次改写（Flask 线程模型统一 + 三大机制全部实测）：
#   ① 令牌桶 TokenBucket：threading.Lock 保证原子性（单进程正确姿势），
#     惰性按时间补充、初始满桶；状态落盘 cache.json（替代 Redis 持久化职责）
#   ② 优先级队列：queue.PriorityQueue + (priority, seq) 排序 —— 高优先级
#     插队、同级先进先出（seq 单调递增保证稳定性）
#   ③ Worker 池：2 个消费者线程（教材单 worker 是吞吐瓶颈）
#   ④ 降级链：qwen-plus 失败 → qwen-turbo → 兜底文案（沿用例 12-5 模式）
#   ⑤ 结果桥接：请求线程经 threading.Event 等待 worker 完成结果
#   ⑥ self-test 6 项：正常流 / 限流 429 / 令牌恢复 / 优先级插队 / 降级 / 削峰

# ============================================================
# 原代码（注释保留——教材简化版，Redis 非原子桶 + 单 worker + 零验证）
# ============================================================
# import redis
# from fastapi import FastAPI, HTTPException
# from langchain_community.chat_models import Qwen2Chat, DeepSeekChat  # ← 虚构
# from langchain.chains import ConversationChain                       # ← 废弃
#
# redis_client = redis.Redis(host="localhost", port=6379, db=0)
# BUCKET_KEY = "agent_rate_limit"
# MAX_TOKENS, REFILL_RATE = 10, 1
#
# def refill_bucket():
#     now = int(time.time())
#     last_refill = int(redis_client.get("last_refill") or now)
#     elapsed = now - last_refill
#     if elapsed > 0:
#         tokens = min(MAX_TOKENS,
#                      int(redis_client.get(BUCKET_KEY) or 0) + elapsed * REFILL_RATE)
#         redis_client.set(BUCKET_KEY, tokens)     # ← 初始为 0，首批请求全被拒
#         redis_client.set("last_refill", now)
#
# def acquire_token():
#     refill_bucket()
#     tokens = int(redis_client.get(BUCKET_KEY) or 0)
#     if tokens > 0:
#         redis_client.decr(BUCKET_KEY)            # ← get/decr 非原子，并发竞态
#         return True
#     return False
#
# request_queue = asyncio.PriorityQueue()
# @app.post("/chat")
# async def chat(req: ChatRequest):
#     if not acquire_token():
#         raise HTTPException(status_code=429, ...)
#     fut = asyncio.get_event_loop().create_future()
#     await request_queue.put((req.priority, time.time(), req, fut))
#     return await fut                              # ← 挂起等待 worker 结果
#
# @app.on_event("startup")                         # ← FastAPI 已废弃的钩子
# async def startup_event():
#     asyncio.create_task(queue_worker())          # ← 单 worker，吞吐瓶颈
# ============================================================

import os
import sys
import time
import json
import uuid
import queue
import threading
import itertools
import logging
from flask import Flask, request, jsonify
import dashscope

# ===== dashscope 统一配置（前 10 章模式）=====
dashscope.api_key = os.environ.get("DASHSCOPE_API_KEY")

# ===== 日志：控制台 + 文件双输出 =====
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_throttle.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout),
              logging.FileHandler(LOG_FILE, encoding="utf-8")],
)
logger = logging.getLogger(__name__)

# ===== 常量 =====
PORT = 8901
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache.json")
BUCKET_CAPACITY = 5        # 令牌桶容量（教学值设小，方便验证限流）
REFILL_RATE = 2            # 每秒补充 2 个令牌（教学值）
WORKER_COUNT = 2           # worker 池大小
QUEUE_MAXSIZE = 20         # 队列上限（背压保护）
FALLBACK_MSG = "系统繁忙，请稍后再试。"


# ============================================================
# 组件 1：令牌桶（修正教材两处 bug + cache.json 持久化）
# ============================================================

class TokenBucket:
    """令牌桶限流：容量 capacity，每秒补充 refill_rate 个，桶空则拒绝

    与教材实现的差异（本篇两个 bug 修复点）：
      - 初始满桶（教材初始 0，启动后首批请求全被拒）
      - threading.Lock 保证"读-扣-写"原子性（教材 get/decr 分离有竞态）
      - 状态落盘 cache.json（替代 Redis 的持久化职责，防重启回满绕过限流）
    """

    def __init__(self, capacity: int, refill_rate: float, cache_file: str):
        """初始化令牌桶

        参数: capacity — 桶容量; refill_rate — 每秒补充速率; cache_file — 持久化路径
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self._cache_file = cache_file
        self._lock = threading.Lock()
        # 优先从 cache.json 恢复（重启不回满）；首次运行才初始化满桶
        state = self._load_state()
        self._tokens = state["tokens"] if state else float(capacity)
        self._last_refill = state["last_refill"] if state else time.time()

    def acquire(self) -> bool:
        """尝试获取一个令牌

        返回: True 拿到（放行）/ False 桶空（应返回 429）
        """
        with self._lock:
            self._refill_locked()
            if self._tokens >= 1:
                self._tokens -= 1
                self._save_state()
                return True
            return False

    def reset(self):
        """重置为满桶并清空持久化状态（self-test 用，保证测试时序确定性）"""
        with self._lock:
            self._tokens = float(self.capacity)
            self._last_refill = time.time()
            self._save_state()

    def _refill_locked(self):
        """按流逝时间惰性补充令牌（调用方必须已持有 _lock）"""
        now = time.time()
        elapsed = now - self._last_refill
        if elapsed > 0:
            self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_rate)
            self._last_refill = now

    def tokens_now(self) -> float:
        """查询当前令牌数（先惰性补充再返回）"""
        with self._lock:
            self._refill_locked()
            return self._tokens

    def _save_state(self):
        """桶状态落盘 cache.json（缓存目录约定的持久化方式）"""
        try:
            with open(self._cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}
        data["token_bucket"] = {"tokens": round(self._tokens, 3),
                                "last_refill": self._last_refill}
        with open(self._cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)

    def _load_state(self):
        """从 cache.json 恢复桶状态；无记录返回 None"""
        try:
            with open(self._cache_file, "r", encoding="utf-8") as f:
                return json.load(f).get("token_bucket")
        except (FileNotFoundError, json.JSONDecodeError):
            return None


# ============================================================
# 组件 2：优先级队列 + Worker 池（削峰填谷）
# ============================================================

class PriorityEntry:
    """队列条目：(priority, seq) 排序 —— 高优先级先处理，同级按入队顺序

    seq 单调递增是关键：纯 tuple 比较 (priority, time) 在同秒内不稳定，
    seq 保证同级 FIFO 且永不抛比较异常。
    """

    _seq = itertools.count()

    def __init__(self, priority: int, payload: dict):
        """构造队列条目

        参数: priority — 0 高优先级 / 1 默认; payload — 请求负载
        """
        self.priority = priority
        self.seq = next(PriorityEntry._seq)
        self.payload = payload
        self.event = threading.Event()    # 请求线程等待 worker 完成的桥
        self.result = None

    def __lt__(self, other):
        return (self.priority, self.seq) < (other.priority, other.seq)


class AgentService:
    """LLM 调用 + 降级链（主后端失败 → 备用 → 兜底文案）"""

    def __init__(self, backends: list):
        """初始化服务

        参数: backends — [{name, model}]，按优先级排序的后端配置列表
        """
        self.backends = backends

    def generate(self, message: str) -> str:
        """带降级的 LLM 调用

        参数: message — 用户消息
        返回: 成功后端的回复；全部失败返回兜底文案
        """
        messages = [{"role": "user", "content": message}]
        for backend in self.backends:
            try:
                if backend["model"].startswith("qwen"):
                    resp = dashscope.Generation.call(
                        model=backend["model"], messages=messages,
                        max_tokens=128, result_format="message")
                    if resp.status_code != 200:
                        raise RuntimeError(f"{backend['model']}: {resp.code}")
                    answer = resp.output.choices[0].message.content
                else:
                    from openai import OpenAI
                    client = OpenAI(api_key=dashscope.api_key,
                                    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
                    answer = client.chat.completions.create(
                        model=backend["model"], messages=messages, max_tokens=128
                    ).choices[0].message.content
                logger.info(f"[LLM] 由 {backend['name']} 处理成功")
                return answer
            except Exception as e:
                logger.warning(f"[降级] {backend['name']} 失败: {e} → 尝试下一后端")
        logger.error("[降级] 全部后端不可用")
        return FALLBACK_MSG


# ===== 全局对象：桶 / 队列 / 服务 / 统计 =====
bucket = TokenBucket(BUCKET_CAPACITY, REFILL_RATE, CACHE_FILE)
task_queue = queue.PriorityQueue(maxsize=QUEUE_MAXSIZE)
service = AgentService([
    {"name": "qwen-plus", "model": "qwen-plus"},
    {"name": "qwen-turbo", "model": "qwen-turbo"},
])
queue_stats = {"processed": 0, "failed": 0}


def queue_worker():
    """worker 线程体：循环取最高优先级任务 → 调用 LLM → 回填结果

    与教材差异：多 worker 池并发消费；异常时也回填（不让请求挂死）
    """
    while True:
        entry = task_queue.get()          # 阻塞取（PriorityQueue 保证高优先级先出）
        try:
            result = service.generate(entry.payload["message"])
            entry.result = {"session_id": entry.payload["session_id"], "response": result}
            queue_stats["processed"] += 1
        except Exception as e:
            logger.error(f"[Worker] 处理异常: {e}")
            entry.result = {"session_id": entry.payload["session_id"], "response": FALLBACK_MSG}
            queue_stats["failed"] += 1
        finally:
            entry.event.set()             # 无论成败都唤醒等待的请求线程
            task_queue.task_done()


# ============================================================
# Flask 应用（教材用 FastAPI，本系列统一 Flask）
# ============================================================

app = Flask(__name__)


@app.route("/health", methods=["GET"])
def health():
    """健康检查：限流与队列运行时指标"""
    return jsonify({
        "status": "ok",
        "bucket_tokens": round(bucket.tokens_now(), 2),
        "queue_size": task_queue.qsize(),
        "stats": dict(queue_stats),
    })


@app.route("/chat", methods=["POST"])
def chat():
    """聊天入口：令牌桶限流 → 优先级队列削峰 → 等待 worker 结果

    请求 JSON: {"message": str, "priority": 0 或 1}
    响应: 200 处理结果 / 429 限流 / 503 队列满（背压）
    """
    # ① 令牌桶限流（第一道闸门：超出容量直接拒绝，保护下游）
    if not bucket.acquire():
        logger.warning(f"[限流] 拒绝请求（剩余令牌 {bucket.tokens_now():.2f}）")
        return jsonify({"error": {"code": 429, "message": "请求过多，请稍后重试。"}}), 429

    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({"error": {"code": 400, "message": "Invalid JSON"}}), 400
    message = (data.get("message") or "").strip()
    priority = data.get("priority", 1)
    if not message:
        return jsonify({"error": {"code": 400, "message": "message is required"}}), 400

    # ② 入队削峰（LLM 处理耗时与 HTTP 响应解耦）
    entry = PriorityEntry(priority, {"message": message,
                                     "session_id": str(uuid.uuid4())[:8]})
    try:
        task_queue.put_nowait(entry)
    except queue.Full:
        return jsonify({"error": {"code": 503, "message": "系统繁忙，队列已满"}}), 503

    # ③ 等待 worker 完成结果（Event 桥接异步）
    entry.event.wait(timeout=60)
    if entry.result is None:
        return jsonify({"error": {"code": 504, "message": "处理超时"}}), 504
    return jsonify(entry.result)


# ============================================================
# main 入口：6 项 self-test
# ============================================================

def _wait_server(url: str, timeout: float = 10.0) -> bool:
    """等待 Flask 服务器就绪"""
    import requests
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            requests.get(url, timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def run_self_test():
    """验证限流/削峰/优先级/降级"""
    import requests
    base = f"http://localhost:{PORT}"
    ok = True

    print("\n" + "=" * 60)
    print("  限流与降级系统 —— Self Test")
    print("=" * 60)

    bucket.reset()   # 重置满桶：上次运行持久化的低令牌会干扰本测试时序
    if not _wait_server(f"{base}/health"):
        print("  [失败] 服务器未在 10s 内启动")
        return False

    # Test 1: 正常请求（真实 LLM + 队列）
    print("\n--- Test 1: 正常请求（真实 LLM + 队列处理）---")
    try:
        r = requests.post(f"{base}/chat", timeout=60,
                          json={"message": "1+1 等于几？只回答数字。"})
        assert r.status_code == 200 and r.json()["response"]
        print(f"  [通过] response={r.json()['response'][:20]}")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 2: 限流验证（并发突发耗尽令牌 → 429）
    # 必须并发：真实 LLM 单发间隔 3s+，令牌边用边补充永远够；
    # 并发突发才还原"流量洪峰"场景，同时需要本地假 LLM 加速消耗
    print("\n--- Test 2: 并发突发耗尽令牌 → 429 限流 ---")
    try:
        # 注入本地假 LLM（0.3s 固定延迟，零 API 成本，处理时序可观测）
        def fake_generate(message):
            time.sleep(0.3)
            logger.info(f"[处理] {message}")
            return f"已处理: {message}"
        service.generate = fake_generate          # 实例属性遮蔽类方法

        codes = []

        def _burst(i):
            r = requests.post(f"{base}/chat", timeout=60,
                              json={"message": f"burst-{i}", "priority": 9})
            codes.append(r.status_code)

        threads = [threading.Thread(target=_burst, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        print(f"  状态码序列: {sorted(codes)}")
        assert codes.count(429) >= 1, "并发突发应触发限流"
        assert codes.count(200) >= 1, "部分请求应正常处理"
        print(f"  [通过] 10 个并发请求: {codes.count(200)} 个成功，{codes.count(429)} 个被限流")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 3: 令牌恢复验证（等待补充速率窗口）
    print("\n--- Test 3: 令牌按速率恢复 ---")
    try:
        time.sleep(2.5)            # 2.5s × 2/s ≈ 5 个令牌
        r = requests.post(f"{base}/chat", timeout=60, json={"message": "恢复了吗？"})
        assert r.status_code == 200, f"令牌应已恢复，实际 {r.status_code}"
        print(f"  [通过] 等待 2.5s 后令牌恢复，请求成功")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 4: 优先级插队（三线程错峰并发，构造"worker 全忙 + 高优先级排队"场景）
    print("\n--- Test 4: 高优先级插队验证 ---")
    try:
        bucket.reset()   # 满桶，排除令牌等待对时序的干扰
        # 注入本地假 LLM（差异化延迟，零 API 成本）：
        #   低-1=0.5s, 低-2=0.9s（占住两个 worker 且让低-2 慢慢做）
        #   高-0=0.1s（一旦被取走立即完成）
        def fake_generate(message):
            delays = {"低-1": 0.5, "低-2": 0.9, "高-0": 0.1}
            time.sleep(delays.get(message, 0.3))
            logger.info(f"[处理] {message}")
            return f"已处理: {message}"
        service.generate = fake_generate          # 实例属性遮蔽类方法

        # 时序设计（2 worker 并行 + 三线程错峰发出）：
        #   t0      低-1 入队 → worker-0 取走（忙 0.5s）
        #   t0+0.05 低-2 入队 → worker-1 取走（忙 0.9s）
        #   t0+0.20 高-0 入队 → 两 worker 全忙，高-0 在队列中等待
        #   t0+0.50 worker-0 空闲 → 队列头是高-0（priority=0）→ 插队取走
        #   t0+0.60 高-0 完成；t0+0.95 低-2 才完成
        #   → 插队成功 ⇔ 完成顺序中 高-0 早于 低-2
        def _post(message, priority, delay):
            time.sleep(delay)
            requests.post(f"{base}/chat", timeout=60,
                          json={"message": message, "priority": priority})
        threads = [threading.Thread(target=_post, args=("低-1", 1, 0.0)),
                   threading.Thread(target=_post, args=("低-2", 1, 0.05)),
                   threading.Thread(target=_post, args=("高-0", 0, 0.20))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        time.sleep(0.8)           # 等队列彻底清空
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            order = [ln.split("[处理] ")[-1].strip() for ln in f if "[处理] " in ln]
        tail = order[-3:]
        print(f"  处理顺序（尾部）: {tail}")
        assert set(tail) == {"低-1", "低-2", "高-0"}, f"三条都应被处理，实际 {tail}"
        # 断言只能用 tail（本次运行的三条）：order 是跨次运行累积的日志，
        # 历史记录会干扰 index 首次命中位置
        assert tail.index("高-0") < tail.index("低-2"), \
            f"高-0 应插队到 低-2 之前完成，实际顺序 {tail}"
        print("  [通过] 高-0 在低-2 之前完成 —— 优先级插队生效")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False
    finally:
        del service.generate      # 删除实例属性，恢复真实类方法（防污染后续测试）

    # Test 5: 降级验证（主后端故障 → 备用真实接管）
    print("\n--- Test 5: 主后端故障 → 降级到 qwen-turbo ---")
    try:
        # 主后端配置为不存在的模型名触发真实失败
        service.backends = [{"name": "broken", "model": "not-exist-model"},
                            {"name": "qwen-turbo", "model": "qwen-turbo"}]
        r = requests.post(f"{base}/chat", timeout=60, json={"message": "1+2 等于几？"})
        assert r.status_code == 200 and r.json()["response"] not in FALLBACK_MSG
        print(f"  [通过] 主后端失败 → qwen-turbo 接管: {r.json()['response'][:20]}")
        service.backends = [{"name": "qwen-plus", "model": "qwen-plus"},
                            {"name": "qwen-turbo", "model": "qwen-turbo"}]
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 6: 削峰统计（queue_size 与 processed 指标可观测）
    print("\n--- Test 6: 队列运行指标 ---")
    try:
        h = requests.get(f"{base}/health", timeout=5).json()
        print(f"  bucket_tokens={h['bucket_tokens']} queue_size={h['queue_size']} stats={h['stats']}")
        assert h["stats"]["processed"] >= 5, "处理计数应累积"
        print("  [通过] 削峰队列指标可观测")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    print(f"\n{'=' * 60}")
    print(f"  {'全部 6 项 self-test 通过' if ok else '存在失败项'}")
    print(f"{'=' * 60}")
    return ok


if __name__ == "__main__":
    # 启动 worker 池（替代教材废弃的 @app.on_event("startup")）
    for i in range(WORKER_COUNT):
        threading.Thread(target=queue_worker, name=f"worker-{i}", daemon=True).start()

    # 后台线程启动 Flask
    threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=PORT, use_reloader=False, threaded=True),
        daemon=True,
    ).start()

    success = run_self_test()

    print(f"\n手动调用示例：")
    print(f"  curl -X POST http://localhost:{PORT}/chat \\")
    print(f"       -H 'Content-Type: application/json' \\")
    print(f"       -d '{{\"message\":\"你好\",\"priority\":0}}'")

    sys.exit(0 if success else 1)
