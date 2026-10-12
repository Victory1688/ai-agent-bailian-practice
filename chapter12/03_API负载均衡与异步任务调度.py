# 【例 12-3】API 负载均衡与异步任务调度
#
# ★ 教材简化 vs 生产级改写
#
# 教材原版问题（已注释保留）：
#   ① Celery broker/backend 都依赖 redis://localhost:6379 —— 本环境无 Redis，
#      按项目约定改用运行目录 cache.json 持久化任务状态
#   ② Celery worker 需要独立进程（celery -A tasks worker），且 Windows 上
#      Celery 4+ 官方不再支持，教学环境几乎跑不起来
#   ③ 双文件结构（main.py + tasks.py）—— 无法单文件运行验证
#   ④ 标题承诺"负载均衡"，但代码里没有任何实现 —— 没有多实例、没有分发
#   ⑤ tasks.py 本地加载 Qwen3-7B —— 需要本地 GPU，且与全书 dashscope 模式脱节
#   ⑥ 无认证、无错误处理、无 self-test
#
# 本次改写（单文件可运行，教学核心完整保留）：
#   ① 异步任务：concurrent.futures.ThreadPoolExecutor（标准库）替代 Celery，
#      任务状态机 PENDING → PROCESSING → COMPLETED 语义不变
#   ② 状态持久化：cache.json（运行目录）替代 Redis backend —— 提交的任务
#      重启后仍可查询（备注 1 要求）
#   ③ 负载均衡：补上真实实现 —— RoundRobin 轮询分发器把任务交替分给
#      instance-0 / instance-1 两个模拟后端，日志可观测分发过程
#   ④ LLM 调用：dashscope.Generation.call（前 10 章统一模式）
#   ⑤ main 入口：4 项 self-test（含轮询分发验证 + cache.json 落盘验证）
#
# 生产演进提示：本例的"单进程内线程池 + 文件状态"适用于教学与单机部署；
# 真正的多机水平扩展时，任务队列应升级为 Celery/RQ + Redis，或云服务
# （阿里云 MNS / AWS SQS），负载均衡用 Nginx/云 SLB 的多实例 upstream。

# ============================================================
# 原代码（注释保留——教材简化版，Redis 依赖 + 无负载均衡实现 + 双文件）
# ============================================================
# # main.py
# from fastapi import FastAPI
# from pydantic import BaseModel
# from celery import Celery
# import uvicorn
#
# app = FastAPI()
# celery_app = Celery('tasks',
#                     broker='redis://localhost:6379/0',    # ← Redis 依赖
#                     backend='redis://localhost:6379/0')   # ← Redis 依赖
#
# class Message(BaseModel):
#     prompt: str
#
# @app.post("/generate/")
# async def generate_text(message: Message):
#     task = celery_app.send_task('tasks.generate_response', args=[message.prompt])
#     return {"task_id": task.id}
#
# @app.get("/result/{task_id}")
# async def get_result(task_id: str):
#     result = celery_app.AsyncResult(task_id)
#     if result.ready():
#         return {"status": "completed", "result": result.result}
#     return {"status": "processing"}
#
# # tasks.py（另一个文件）
# @celery_app.task(name="tasks.generate_response")
# def generate_response(prompt: str):
#     model = AutoModelForCausalLM.from_pretrained("Qwen/Qwen3-7B")  # ← 本地 GPU
#     ...
# # 需要手动启动: celery -A tasks worker   ← Windows 支持差，教学难运行
# ============================================================

import os
import sys
import json
import time
import uuid
import threading
import logging
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, request, jsonify
import dashscope

# ===== dashscope 统一配置（前 10 章模式）=====
dashscope.api_key = os.environ.get("DASHSCOPE_API_KEY")

# ===== 日志：控制台 + 文件双输出（沿用例 12-1/02）=====
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_async.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout),
              logging.FileHandler(LOG_FILE, encoding="utf-8")],
)
logger = logging.getLogger(__name__)

# ===== 常量 =====
PORT = 8900
DASHSCOPE_MODEL = "qwen-plus"
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache.json")
NUM_WORKERS = 2   # 任务执行并发数（对应 2 个"后端实例"）

# ============================================================
# 组件 1：Round-Robin 负载均衡分发器（教材标题承诺但未实现的部分）
# ============================================================

class RoundRobinRouter:
    """轮询分发器：把任务交替分配给多个后端实例

    负载均衡最经典的算法。生产中由 Nginx/云 SLB 在多台机器间做同样的事，
    这里在进程内模拟，让新人能直接观测分发过程。
    """

    def __init__(self, instances):
        """初始化分发器

        参数: instances — 后端实例名列表，如 ["instance-0", "instance-1"]
        """
        self.instances = instances
        self._index = 0
        self._lock = threading.Lock()
        self._counters = {name: 0 for name in instances}   # 每实例分发计数

    def next(self) -> str:
        """返回下一个应接收任务的实例名（线程安全）"""
        with self._lock:
            name = self.instances[self._index % len(self.instances)]
            self._index += 1
            self._counters[name] += 1
            return name

    def stats(self) -> dict:
        """返回各实例的分发统计（验证流量是否均匀）"""
        with self._lock:
            return dict(self._counters)


# ============================================================
# 组件 2：异步任务管理器（ThreadPoolExecutor + cache.json 持久化）
# ============================================================

class TaskManager:
    """异步任务管理器：提交-轮询模式（替代 Celery + Redis）

    状态机: PENDING（已入队）→ PROCESSING（执行中）→ COMPLETED / FAILED
    状态持久化到运行目录 cache.json（备注 1：替代 Redis backend）
    """

    def __init__(self, cache_file: str, router: RoundRobinRouter, max_workers: int):
        """初始化任务管理器

        参数: cache_file — 状态持久化文件路径; router — 负载均衡分发器;
              max_workers — 执行线程数（模拟后端实例数）
        """
        self._cache_file = cache_file
        self._router = router
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="worker")
        self._tasks = {}                       # task_id -> 状态字典（内存主数据）
        self._lock = threading.Lock()          # 保护 _tasks 与 cache.json 写入
        self._load_cache()                     # 启动时恢复历史任务（持久化的意义）

    # ----- 持久化（替代 Redis backend）-----

    def _load_cache(self):
        """启动时从 cache.json 恢复历史任务状态"""
        if os.path.exists(self._cache_file):
            try:
                with open(self._cache_file, "r", encoding="utf-8") as f:
                    self._tasks = json.load(f)
                logger.info(f"从 cache.json 恢复 {len(self._tasks)} 个历史任务")
            except (json.JSONDecodeError, OSError):
                logger.warning("cache.json 损坏，忽略并重建")

    def _save_cache(self):
        """把全部任务状态落盘到 cache.json（调用方必须已持有 _lock）"""
        with open(self._cache_file, "w", encoding="utf-8") as f:
            json.dump(self._tasks, f, ensure_ascii=False, indent=2)

    # ----- 对外接口：提交 / 查询 -----

    def submit(self, prompt: str) -> str:
        """提交异步任务，立即返回 task_id（不阻塞等待结果）

        参数: prompt — 用户提示词
        返回: task_id（8 位 hex）
        """
        task_id = uuid.uuid4().hex[:8]
        instance = self._router.next()          # 负载均衡：决定哪个实例处理
        with self._lock:
            self._tasks[task_id] = {
                "status": "PENDING",
                "instance": instance,
                "prompt": prompt,
                "result": None,
                "created_at": time.strftime("%H:%M:%S"),
            }
            self._save_cache()
        logger.info(f"[{task_id}] 任务提交 → 分发给 {instance}（轮询）")
        self._pool.submit(self._execute, task_id, prompt, instance)
        return task_id

    def get(self, task_id: str) -> dict:
        """查询任务状态与结果

        返回: {status, instance, result?, created_at?}；不存在返回 None
        """
        with self._lock:
            t = self._tasks.get(task_id)
            if not t:
                return None
            return {"status": t["status"], "instance": t["instance"],
                    "result": t["result"], "created_at": t["created_at"]}

    def _execute(self, task_id: str, prompt: str, instance: str):
        """工作线程体：调用 LLM 并更新状态（在提交时由线程池调度）

        异常说明: LLM 失败时状态置 FAILED，不让线程静默死亡
        """
        with self._lock:
            self._tasks[task_id]["status"] = "PROCESSING"
        logger.info(f"[{task_id}] {instance} 开始处理")
        try:
            resp = dashscope.Generation.call(
                model=DASHSCOPE_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=128,
                result_format="message",
            )
            content = resp.output.choices[0].message.content
            with self._lock:
                self._tasks[task_id].update(status="COMPLETED", result=content)
                self._save_cache()
            logger.info(f"[{task_id}] 处理完成")
        except Exception as e:
            with self._lock:
                self._tasks[task_id].update(status="FAILED", result=str(e))
                self._save_cache()
            logger.error(f"[{task_id}] 处理失败: {e}")


# ============================================================
# Flask 应用（教材用 FastAPI，本系列统一 Flask，异步模式与框架无关）
# ============================================================

app = Flask(__name__)
router = RoundRobinRouter(["instance-0", "instance-1"])
manager = TaskManager(CACHE_FILE, router, max_workers=NUM_WORKERS)


@app.route("/health", methods=["GET"])
def health():
    """健康检查：含负载均衡分发统计"""
    return jsonify({
        "status": "ok",
        "model": DASHSCOPE_MODEL,
        "instances": router.stats(),
        "cached_tasks": len(manager._tasks),
    })


@app.route("/generate", methods=["POST"])
def generate():
    """提交异步任务 → 立即返回 task_id（教材核心交互：不阻塞等待）"""
    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({"error": {"code": 400, "message": "Invalid JSON body"}}), 400
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": {"code": 400, "message": "prompt is required"}}), 400
    task_id = manager.submit(prompt)
    return jsonify({"task_id": task_id, "status": "PENDING"}), 202


@app.route("/result/<task_id>", methods=["GET"])
def result(task_id: str):
    """轮询任务结果（教材核心交互：状态机 PENDING → COMPLETED）"""
    t = manager.get(task_id)
    if t is None:
        return jsonify({"error": {"code": 404, "message": "task not found"}}), 404
    body = {"status": t["status"].lower(), "instance": t["instance"]}
    if t["status"] in ("COMPLETED", "FAILED"):
        body["result"] = t["result"]
    return jsonify(body)


# ============================================================
# main 入口：4 项 self-test
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
    """验证异步任务全流程：提交/轮询/负载均衡/持久化"""
    import requests
    base = f"http://localhost:{PORT}"
    ok = True

    print("\n" + "=" * 60)
    print("  异步任务 + 负载均衡 —— Self Test")
    print("=" * 60)

    if not _wait_server(f"{base}/health"):
        print("  [失败] 服务器未在 10s 内启动")
        return False

    # Test 1: 提交任务 → 立即返回 task_id
    print("\n--- Test 1: POST /generate 提交任务 ---")
    try:
        r = requests.post(f"{base}/generate", timeout=5,
                          json={"prompt": "用一句话介绍负载均衡"})
        assert r.status_code == 202
        task_id = r.json()["task_id"]
        print(f"  [通过] task_id={task_id}（立即返回，未阻塞）")
    except Exception as e:
        print(f"  [失败] {e}"); return False

    # Test 2: 轮询直到完成，拿到 LLM 结果
    print("\n--- Test 2: GET /result 轮询至完成 ---")
    try:
        final = None
        for _ in range(30):
            body = requests.get(f"{base}/result/{task_id}", timeout=5).json()
            if body["status"] in ("completed", "failed"):
                final = body
                break
            time.sleep(0.5)
        assert final and final["status"] == "completed" and final["result"]
        print(f"  [通过] result={final['result'][:40]}")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 3: 并发提交 4 个任务 → 验证轮询分发均匀
    print("\n--- Test 3: 并发 4 任务 → 轮询分发验证 ---")
    try:
        ids = []
        for i in range(4):
            r = requests.post(f"{base}/generate", timeout=5,
                              json={"prompt": f"用 5 个字说明数字 {i}"})
            ids.append(r.json()["task_id"])
        time.sleep(6)   # 等待后台线程完成（每个任务约 1-2s）
        h = requests.get(f"{base}/health", timeout=5).json()
        stats = h["instances"]
        print(f"  分发统计: {stats}")
        assert all(v > 0 for v in stats.values()), "有实例未被分发到"
        assert sum(stats.values()) == 5, "总分发数应为 5（1+4）"
        print("  [通过] 两个实例都被使用，轮询分发生效")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 4: cache.json 落盘验证（替代 Redis 持久化的证据）
    print("\n--- Test 4: cache.json 持久化验证 ---")
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            persisted = json.load(f)
        assert task_id in persisted, "刚提交的任务未落盘"
        assert persisted[task_id]["status"] == "COMPLETED"
        assert len(persisted) >= 5
        print(f"  [通过] cache.json 已持久化 {len(persisted)} 个任务（含历史）")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    print(f"\n{'=' * 60}")
    print(f"  {'全部 4 项 self-test 通过' if ok else '存在失败项'}")
    print(f"{'=' * 60}")
    return ok


if __name__ == "__main__":
    # 后台线程启动 Flask（教材 uvicorn.run 阻塞且模块名不匹配单文件运行）
    threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=PORT, use_reloader=False),
        daemon=True,
    ).start()

    success = run_self_test()

    print(f"\n手动调用示例：")
    print(f"  curl -X POST http://localhost:{PORT}/generate \\")
    print(f"       -H 'Content-Type: application/json' -d '{{\"prompt\":\"你好\"}}'")
    print(f"  curl http://localhost:{PORT}/result/<task_id>")

    sys.exit(0 if success else 1)
