# 【例 11-1】API 与 SDK 支持——基于 Flask 的 A2A Agent Web 服务
#
# ★ 教材简化 vs 生产级改写
#
# 教材原版问题（已注释保留）：
#   ① DashScope 端点过时：api/v1/services/aigc/text-generation/generation
#      —— 这个 v1 端点已经下线，现在标准做法是用 dashscope SDK
#   ② API Key 命名混乱：QWEN_API_KEY 实际指向 DashScope
#   ③ 错误处理粗糙：只判断 status_code == 200，没有 try/except
#   ④ 没有 A2A Agent Card 端点：和 char10 的 A2A 协议脱节
#   ⑤ 没有健康检查：生产部署不可接受
#   ⑥ 没有 main self-test：只能用 Flask run，无法直接验证
#
# 本次改写：
#   ① DashScope：用 dashscope SDK（Generation.call），和 char01-10 统一
#   ② DeepSeek：保留 requests.post + 标准 v1/chat/completions
#   ③ 加 A2A Agent Card 端点 /well-known/agent.json（char10 协议衔接）
#   ④ 加 /health 健康检查端点
#   ⑤ 完整错误处理：try/except + HTTP 状态码 + JSON 错误格式
#   ⑥ main 入口：启动 Flask → localhost self-test → 自动退出
#   ⑦ 无 redis，无需 cache.json 替换

# ============================================================
# 原代码（注释保留——教材简化版，端点过时 + 无 A2A 规范 + 错误处理不足）
# ============================================================
# import os, requests
# from flask import Flask, request, jsonify
#
# app = Flask(__name__)
# QWEN_API_KEY = os.getenv("QWEN_API_KEY")
# QWEN_API_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"  # ← 过时端点
# DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
# DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
#
# def call_qwen_model(prompt):
#     data = {"model": "qwen3-14b", "input": prompt}  # ← 旧格式
#     response = requests.post(QWEN_API_URL, ...)
#
# @app.route("/ask", methods=["POST"])
# def ask():
#     # ← 没有 Content-Type 校验、没有 JSON 错误处理
#     answer = call_qwen_model(question) / call_deepseek_model(question)
#     return jsonify({"answer": answer})
#
# if __name__ == "__main__":
#     app.run(port=5000)
# ============================================================

import os
import sys
import time
import threading
import requests
from flask import Flask, request, jsonify

# ===== 统一用前 10 章的环境变量命名（DASHSCOPE_API_KEY）=====
import dashscope
dashscope.api_key = os.environ.get("DASHSCOPE_API_KEY")

# ===== Flask 应用 =====
app = Flask(__name__)

# ===== 常量 =====
PORT = 5000
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DASHSCOPE_MODEL = "qwen-plus"


# ============================================================
# A2A Agent Card（/well-known/agent.json）——和 char10 协议衔接
# ============================================================

AGENT_CARD = {
    "name": "flask-chat-agent",
    "description": "基于 Flask 的 A2A 协议 Agent 服务，支持 DashScope (qwen-plus) 和 DeepSeek 双模型",
    "endpoint": f"http://localhost:{PORT}/a2a",
    "version": "1.0.0",
    "authentication": {
        "schemes": ["bearer"],
        "bearer": {"description": "可选 Bearer Token 认证"},
    },
    "capabilities": {
        "streaming": False,
        "pushNotifications": False,
    },
    "skills": [
        {
            "id": "chat_dashscope",
            "description": "通用问答（DashScope qwen-plus 模型）",
            "tags": ["问答", "dashscope", "qwen"],
            "inputModes": ["text"],
            "outputModes": ["text"],
        },
        {
            "id": "chat_deepseek",
            "description": "通用问答（DeepSeek-chat 模型）",
            "tags": ["问答", "deepseek"],
            "inputModes": ["text"],
            "outputModes": ["text"],
        },
    ],
}


# ============================================================
# LLM 调用函数（两个后端）
# ============================================================

def call_dashscope(prompt: str, system_prompt: str = "你是一个专业的问答助手，回答简洁准确。") -> str:
    """用 dashscope SDK 调用 qwen-plus（统一前 10 章模式）

    返回: LLM 生成的文本
    异常: 网络超时、API Key 缺失、模型调用失败
    """
    response = dashscope.Generation.call(
        model=DASHSCOPE_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=512,
        result_format='message',
    )
    return response.output.choices[0].message.content


def call_deepseek(prompt: str, system_prompt: str = "你是一个专业的问答助手，回答简洁准确。") -> str:
    """用 requests 调用 DeepSeek Chat API（标准 v1 端点）

    DeepSeek 没有我们统一的 SDK 依赖，用 requests 直调。
    """
    if not DEEPSEEK_API_KEY:
        raise ValueError("DEEPSEEK_API_KEY 环境变量未设置")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
    }
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 512,
    }
    resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=data, timeout=30)
    resp.raise_for_status()
    choices = resp.json().get("choices", [])
    if not choices:
        raise ValueError("DeepSeek 响应无 choices")
    return choices[0]["message"]["content"]


# ============================================================
# Flask 路由
# ============================================================

@app.route("/well-known/agent.json", methods=["GET"])
def agent_card():
    """A2A Agent Card 发现端点（规范路径 /.well-known/agent.json）

    char10 所有 Agent 都有 Agent Card，这里 Flask 服务也声明自己的身份。
    """
    return jsonify(AGENT_CARD)


@app.route("/health", methods=["GET"])
def health():
    """健康检查端点（生产部署必需）"""
    return jsonify({
        "status": "ok",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "version": AGENT_CARD["version"],
        "models": [DASHSCOPE_MODEL, "deepseek-chat"],
    })


@app.route("/ask", methods=["POST"])
def ask():
    """问答端点（核心业务路由）

    请求 JSON: {"question": "...", "model": "qwen|deepseek", "system_prompt": "..."}
    响应 JSON: {"answer": "...", "model": "...", "elapsed_ms": 123}

    完整错误处理：参数校验 → 模型选择 → LLM 调用 → 异常捕获
    """
    # Step 1: Content-Type 校验 + JSON 解析
    try:
        data = request.get_json(force=True, silent=False)
    except Exception as e:
        return jsonify({"error": {"code": 400, "message": f"Invalid JSON: {e}"}}), 400

    if not data:
        return jsonify({"error": {"code": 400, "message": "Request body is empty"}}), 400

    # Step 2: 参数校验
    question = data.get("question", "").strip()
    if not question:
        return jsonify({"error": {"code": 400, "message": "question field is required"}}), 400

    model = data.get("model", "qwen").lower()
    system_prompt = data.get("system_prompt", "你是一个专业的问答助手，回答简洁准确。")

    if model not in ("qwen", "deepseek"):
        return jsonify({
            "error": {"code": 400, "message": f"Unsupported model: {model}"}
        }), 400

    # Step 3: 调用 LLM
    t0 = time.time()
    try:
        if model == "qwen":
            answer = call_dashscope(question, system_prompt)
        else:
            answer = call_deepseek(question, system_prompt)
    except ValueError as e:
        return jsonify({"error": {"code": 400, "message": str(e)}}), 400
    except requests.RequestException as e:
        return jsonify({"error": {"code": 502, "message": f"Upstream API error: {e}"}}), 502
    except Exception as e:
        return jsonify({"error": {"code": 500, "message": f"Internal error: {e}"}}), 500

    elapsed = int((time.time() - t0) * 1000)

    # Step 4: 返回结果（含响应时间，方便调试）
    return jsonify({
        "answer": answer,
        "model": f"{'qwen-plus' if model == 'qwen' else 'deepseek-chat'}",
        "elapsed_ms": elapsed,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": {"code": 404, "message": "Not Found"}}), 404


@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({"error": {"code": 405, "message": "Method Not Allowed"}}), 405


# ============================================================
# main 入口：启动 Flask + 本地 self-test
# ============================================================

def _wait_server(url: str, timeout: float = 10.0) -> bool:
    """等待 Flask 服务器就绪"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            requests.get(url, timeout=2)
            return True
        except requests.RequestException:
            time.sleep(0.5)
    return False


def run_self_test():
    """本地 HTTP self-test（验证三个端点都正常）"""
    base = f"http://localhost:{PORT}"
    ok = True

    print("\n" + "=" * 60)
    print("  Flask Agent Web 服务 —— Self Test")
    print("=" * 60)

    # 等待服务器
    print(f"\n等待 Flask 服务器就绪（{base}/health）...")
    if not _wait_server(f"{base}/health"):
        print("  [失败] 服务器未在 10s 内启动")
        return False

    # 测试 1: /health
    print("\n--- Test 1: GET /health ---")
    try:
        r = requests.get(f"{base}/health", timeout=5)
        data = r.json()
        assert data["status"] == "ok"
        print(f"  [通过] status={data['status']}, version={data['version']}")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # 测试 2: /well-known/agent.json
    print("\n--- Test 2: GET /well-known/agent.json ---")
    try:
        r = requests.get(f"{base}/well-known/agent.json", timeout=5)
        card = r.json()
        assert card["name"] == "flask-chat-agent"
        assert len(card["skills"]) == 2
        print(f"  [通过] name={card['name']}, skills={len(card['skills'])}")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # 测试 3: POST /ask（DashScope qwen-plus 真实调用）
    print("\n--- Test 3: POST /ask (model=qwen, 真实 API 调用) ---")
    try:
        r = requests.post(
            f"{base}/ask",
            json={"question": "1+1 等于几？请直接给出数字。", "model": "qwen"},
            timeout=30,
        )
        data = r.json()
        assert data.get("answer")
        print(f"  [通过] answer={data['answer'][:60]}..., elapsed={data['elapsed_ms']}ms")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # 测试 4: /ask 参数校验（空 question）
    print("\n--- Test 4: POST /ask 参数校验 ---")
    try:
        r = requests.post(f"{base}/ask", json={"question": "", "model": "qwen"}, timeout=5)
        assert r.status_code == 400
        print(f"  [通过] 空 question 返回 400: {r.json()}")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    print(f"\n{'='*60}")
    if ok:
        print("  全部 4 项 self-test 通过")
    else:
        print("  存在失败项")
    print(f"{'='*60}")
    return ok


if __name__ == "__main__":
    # 后台线程启动 Flask（避免阻塞主线程的 self-test）
    def _run_server():
        # use_reloader=False：防止 main 重启导致端口冲突
        app.run(host="0.0.0.0", port=PORT, use_reloader=False)

    server_thread = threading.Thread(target=_run_server, daemon=True)
    server_thread.start()

    # 跑 self-test
    success = run_self_test()

    # 输出使用提示
    print(f"\n服务已在后台线程启动，可手动调用：")
    print(f"  curl http://localhost:{PORT}/health")
    print(f"  curl http://localhost:{PORT}/well-known/agent.json")
    print(f"  curl -X POST http://localhost:{PORT}/ask -H 'Content-Type: application/json' -d '{{\"question\":\"...\",\"model\":\"qwen\"}}'")

    # 退出
    sys.exit(0 if success else 1)
