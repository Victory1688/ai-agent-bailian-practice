# 【例 12-1】Web 服务化部署实战 —— 记录日志与并发控制
#
# ★ 教材简化 vs 生产级改写
#
# 教材原版问题（已注释保留）：
#   ① torch.time.time() 是 bug —— torch 没有 time 模块，应为 time.time()
#   ② 本地加载 Qwen/Qwen3-7B + .cuda() —— 需要本地 GPU（约 15GB 显存），
#      普通开发机无法运行；且与全书统一的 dashscope API 模式脱节
#   ③ 章节标题是"记录日志并发"，但原代码请求处理中没有任何一行日志输出
#      —— logging.basicConfig 配置了却从未使用
#   ④ 并发只有 model_lock 一把锁，没有并发演示，无法验证并发能力
#   ⑤ 没有 /health 健康检查端点
#   ⑥ 没有 main self-test，app.run() 直接阻塞
#
# 本次改写（保持 OpenAI 兼容响应格式 —— vLLM/Ollama 等推理服务的行业标准）：
#   ① dashscope.Generation.call 替代本地 transformers 推理（与前 10 章统一）
#   ② 修复 torch.time.time() → time.time()
#   ③ 真实日志：request_id + 耗时 + token 用量 + 并发数，同时写控制台和
#      日志文件 agent_server.log
#   ④ 并发演示：活跃请求计数器 + 多线程并发 self-test
#   ⑤ 加 /health 健康检查端点
#   ⑥ main 入口：后台线程启动 Flask → 顺序测试 → 并发测试 → 自动退出
#
# 关键架构洞察：教材用本地 GPU 推理时需要 model_lock（GPU 显存限制并发），
# 改用云端 API 后并发难题交给服务提供商 —— 这正是"部署"的核心价值之一。

# ============================================================
# 原代码（注释保留——教材简化版，本地 GPU 推理 + 无日志 + torch.time bug）
# ============================================================
# import os
# import threading
# import logging
# from flask import Flask, request, jsonify
# from transformers import AutoTokenizer, AutoModelForCausalLM
# import torch
#
# logging.basicConfig(level=logging.INFO)
# logger = logging.getLogger(__name__)
#
# app = Flask(__name__)
#
# MODEL_NAME = "Qwen/Qwen3-7B"
# tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
# model = AutoModelForCausalLM.from_pretrained(MODEL_NAME, trust_remote_code=True).cuda()
# model.eval()
#
# model_lock = threading.Lock()
#
# @app.route('/v1/chat/completions', methods=['POST'])
# def chat_completions():
#     data = request.get_json()
#     messages = data.get("messages", [])
#     ...
#     created = int(torch.time.time())          # ← bug：torch 没有 time 模块
#     with model_lock:                          # ← 本地推理必须加锁
#         outputs = model.generate(inputs, ...)
#     ...
#
# if __name__ == '__main__':
#     app.run(host='0.0.0.0', port=8000)        # ← 无验证直接阻塞
# ============================================================

import os
import sys
import time
import uuid
import threading
import logging
from flask import Flask, request, jsonify
import dashscope

# ===== dashscope 统一配置（前 10 章模式）=====
dashscope.api_key = os.environ.get("DASHSCOPE_API_KEY")

# ===== 日志配置：控制台 + 文件双输出 =====
# 教材只配了 basicConfig 却从未打日志；这里每个请求都产生结构化日志行
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_server.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),          # 控制台实时输出
        logging.FileHandler(LOG_FILE, encoding="utf-8"),  # 落盘持久化
    ],
)
logger = logging.getLogger(__name__)

# ===== Flask 应用 =====
app = Flask(__name__)

# ===== 常量 =====
PORT = 8000
DASHSCOPE_MODEL = "qwen-plus"

# ===== 并发统计（演示 Flask 多线程并发处理能力）=====
# 教材的 model_lock 是"本地 GPU 推理必须串行"；API 化后服务端天然可并发，
# 这里用计数器观测并发水位 —— max_active 就是同时处理的峰值请求数
_stats = {"total": 0, "active": 0, "max_active": 0}
_stats_lock = threading.Lock()


# ============================================================
# /health 健康检查端点（生产部署必需，教材缺失）
# ============================================================

@app.route("/health", methods=["GET"])
def health():
    """健康检查端点，返回服务状态与并发统计"""
    return jsonify({
        "status": "ok",
        "model": DASHSCOPE_MODEL,
        "stats": dict(_stats),
    })


# ============================================================
# 核心业务路由：OpenAI 兼容的 /v1/chat/completions
# ============================================================

@app.route("/v1/chat/completions", methods=["POST"])
def chat_completions():
    """OpenAI 兼容 Chat API 端点（含结构化日志与并发观测）

    请求 JSON: {"messages": [{"role", "content"}], "max_tokens", "temperature"}
    响应 JSON: OpenAI 兼容格式（id/object/created/choices/usage）
    """
    request_id = uuid.uuid4().hex[:8]  # 每个请求的唯一标识，日志用它能串联完整链路

    # Step 1: 参数校验（教材只判空 messages，这里补齐 JSON 解析异常）
    try:
        data = request.get_json(force=True)
    except Exception:
        logger.warning(f"[{request_id}] 非法 JSON 请求体")
        return jsonify({"error": {"code": 400, "message": "Invalid JSON body"}}), 400

    messages = data.get("messages", [])
    max_tokens = data.get("max_tokens", 512)
    temperature = data.get("temperature", 0.7)

    if not messages:
        logger.warning(f"[{request_id}] messages 为空")
        return jsonify({"error": {"code": 400, "message": "No messages provided"}}), 400

    # Step 2: 并发计数 +1（观测并发水位）
    with _stats_lock:
        _stats["total"] += 1
        _stats["active"] += 1
        _stats["max_active"] = max(_stats["max_active"], _stats["active"])
        active_now = _stats["active"]
    logger.info(f"[{request_id}] 请求开始 messages={len(messages)} 并发={active_now}")

    # Step 3: 调用云端 LLM（替代教材的本地 model.generate）
    # 注意：教材这里要用 model_lock 串行化；API 调用天然支持并发，无需加锁
    t0 = time.time()
    try:
        response = dashscope.Generation.call(
            model=DASHSCOPE_MODEL,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            result_format="message",
        )
        content = response.output.choices[0].message.content
        # dashscope 的 usage 字段映射为 OpenAI 兼容命名
        usage = {
            "prompt_tokens": response.usage.input_tokens,
            "completion_tokens": response.usage.output_tokens,
            "total_tokens": response.usage.total_tokens,
        }
    except Exception as e:
        logger.error(f"[{request_id}] LLM 调用失败: {e}")
        return jsonify({"error": {"code": 502, "message": f"Upstream LLM error: {e}"}}), 502
    finally:
        # Step 4: 并发计数 -1（必须放 finally，出错也要释放）
        with _stats_lock:
            _stats["active"] -= 1

    elapsed_ms = int((time.time() - t0) * 1000)
    logger.info(
        f"[{request_id}] 请求完成 耗时={elapsed_ms}ms "
        f"tokens={usage['total_tokens']}"
    )

    # Step 5: 构造 OpenAI 兼容响应（教材响应格式保留 —— 行业标准）
    return jsonify({
        "id": f"chatcmpl-{request_id}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": DASHSCOPE_MODEL,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
        "usage": usage,
    })


# ============================================================
# main 入口：后台启动 Flask + 顺序测试 + 并发测试
# ============================================================

def _wait_server(url: str, timeout: float = 10.0) -> bool:
    """等待 Flask 服务器就绪"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            import requests
            requests.get(url, timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def run_self_test():
    """顺序测试 1 个请求 + 并发测试 3 个请求，验证日志与并发"""
    import requests
    base = f"http://localhost:{PORT}"
    ok = True

    print("\n" + "=" * 60)
    print("  Flask Agent 服务 —— 日志与并发 Self Test")
    print("=" * 60)

    if not _wait_server(f"{base}/health"):
        print("  [失败] 服务器未在 10s 内启动")
        return False

    # 测试 1: /health
    print("\n--- Test 1: GET /health ---")
    try:
        r = requests.get(f"{base}/health", timeout=5)
        assert r.json()["status"] == "ok"
        print("  [通过] status=ok")
    except Exception as e:
        print(f"  [失败] {e}")
        ok = False

    # 测试 2: 顺序调用 1 次（观察单请求日志链路）
    print("\n--- Test 2: POST /v1/chat/completions（单请求）---")
    try:
        r = requests.post(f"{base}/v1/chat/completions", timeout=30, json={
            "messages": [{"role": "user", "content": "1+1 等于几？只回答数字。"}],
            "max_tokens": 64,
        })
        data = r.json()
        assert data["choices"][0]["message"]["content"]
        print(f"  [通过] answer={data['choices'][0]['message']['content'][:30]}")
        print(f"         usage={data['usage']}")
    except Exception as e:
        print(f"  [失败] {e}")
        ok = False

    # 测试 3: 并发 3 个请求（观察日志交叉与 max_active >= 3）
    print("\n--- Test 3: 并发 3 请求（多线程同时 POST）---")
    results = []

    def _worker(i: int):
        try:
            r = requests.post(f"{base}/v1/chat/completions", timeout=30, json={
                "messages": [{"role": "user", "content": f"用 5 个字说明数字 {i} 的用途"}],
                "max_tokens": 64,
            })
            results.append(r.json())
        except Exception as e:
            results.append({"error": str(e)})

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    success_n = sum(1 for r in results if "choices" in r)
    if success_n == 3:
        print(f"  [通过] 3 个并发请求全部完成")
    else:
        print(f"  [失败] 并发成功 {success_n}/3")
        ok = False

    # 测试 4: 校验并发统计（max_active 应 >= 3，证明真并发而非串行）
    print("\n--- Test 4: 并发统计校验 ---")
    try:
        stats = requests.get(f"{base}/health", timeout=5).json()["stats"]
        print(f"  total={stats['total']} max_active={stats['max_active']}")
        assert stats["max_active"] >= 3, "max_active < 3 说明请求被串行处理"
        print("  [通过] max_active >= 3，并发处理得到验证")
    except Exception as e:
        print(f"  [失败] {e}")
        ok = False

    print(f"\n{'=' * 60}")
    print(f"  {'全部 4 项 self-test 通过' if ok else '存在失败项'}")
    print(f"  日志文件: {LOG_FILE}")
    print(f"{'=' * 60}")
    return ok


if __name__ == "__main__":
    # 后台线程启动 Flask（教材直接 app.run 阻塞，无法自动验证）
    threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=PORT, use_reloader=False),
        daemon=True,
    ).start()

    success = run_self_test()
    sys.exit(0 if success else 1)
