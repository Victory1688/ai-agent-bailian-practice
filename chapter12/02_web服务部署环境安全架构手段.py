# 【例 12-2】Web 服务部署环境安全架构手段
#
# ★ 教材简化 vs 生产级改写
#
# 教材原版问题（已注释保留）：
#   ① torch.time.time() bug（与例 12-1 同款）—— torch 没有 time 模块
#   ② 本地加载 Qwen/Qwen3-7B + .cuda() —— 需要本地 GPU，普通开发机无法运行
#   ③ SSL 证书 cert.pem/key.pem 凭空出现 —— 教材没给生成方式，直接运行
#      必报 FileNotFoundError；改写用 Flask 内置 adhoc 自签名证书
#   ④ ProxyFix(app.wsgi_app) 无参数调用 —— 默认全 0 不修正任何头，写了等于没写
#   ⑤ 没有任何认证机制 —— API 裸奔，任何人拿到地址就能白嫖你的 LLM 额度；
#      认证是安全第一道防线，比限流和加密优先级更高
#   ⑥ 没有安全响应头 —— 缺 X-Content-Type-Options 等基础防护
#   ⑦ 没有 /health、没有 main self-test —— 无法验证安全配置是否真的生效
#
# 本次改写（安全纵深防御四层，由外到内）：
#   ① 第 1 层 传输加密：HTTPS（Flask adhoc 自签名证书，生产替换为正式证书）
#   ② 第 2 层 认证鉴权：API Key 校验（X-API-Key 头，缺失/错误返回 401）
#   ③ 第 3 层 速率限制：flask-limiter 按 IP 限流（超限返回 429）
#   ④ 第 4 层 安全响应头：X-Content-Type-Options / X-Frame-Options / CSP
#   ⑤ LLM 后端改 dashscope API（前 10 章统一模式），修复 torch.time bug
#   ⑥ main 入口：HTTPS 启动 + 4 项安全 self-test（含 401/429 验证）
#
# 关于 flask-limiter 存储：教材未配置 storage_uri，默认用内存存储（进程内
# 计数，重启清零）——单机教学场景够用。生产多实例部署时应配置 Redis 集中
# 计数（storage_uri="redis://..."）；本项目环境无 Redis，遵循内存存储。

# ============================================================
# 原代码（注释保留——教材简化版，无认证 + 证书缺失 + 本地 GPU 推理）
# ============================================================
# import os, ssl, logging
# from flask import Flask, request, jsonify
# from flask_limiter import Limiter
# from flask_limiter.util import get_remote_address
# from werkzeug.middleware.proxy_fix import ProxyFix
# from transformers import AutoTokenizer, AutoModelForCausalLM
# import torch
#
# app = Flask(__name__)
# app.wsgi_app = ProxyFix(app.wsgi_app)              # ← 无参数，等于没生效
# limiter = Limiter(app, key_func=get_remote_address,
#                   default_limits=["100 per minute"])
#
# MODEL_NAME = "Qwen/Qwen3-7B"                       # ← 本地 GPU 推理
# model = AutoModelForCausalLM.from_pretrained(...).cuda()
#
# @app.route('/v1/chat/completions', methods=['POST'])
# @limiter.limit("10 per minute")
# def chat_completions():
#     # ← 没有任何认证检查，API 裸奔
#     created = int(torch.time.time())               # ← bug
#     ...
#
# if __name__ == '__main__':
#     context = ssl.SSLContext(ssl.PROTOCOL_TLS)
#     context.load_cert_chain('cert.pem', 'key.pem')  # ← 证书文件不存在，必报错
#     app.run(host='0.0.0.0', port=443, ssl_context=context)
# ============================================================

import os
import sys
import time
import uuid
import secrets
import threading
import logging
from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix
import dashscope

# ===== dashscope 统一配置（前 10 章模式）=====
dashscope.api_key = os.environ.get("DASHSCOPE_API_KEY")

# ===== 日志：控制台 + 文件双输出（沿用例 12-1）=====
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_secure.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout),
              logging.FileHandler(LOG_FILE, encoding="utf-8")],
)
logger = logging.getLogger(__name__)

# ===== Flask 应用 =====
app = Flask(__name__)

# ProxyFix 正确用法：显式声明信任代理转发的头数量（教材漏了，等于没生效）
# x_for=1 表示信任 1 层代理的 X-Forwarded-For，get_remote_address 才能拿到真实客户端 IP
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# ===== API Key（认证凭据）=====
# 演示场景：环境变量优先，未设置则随机生成并打印（每次运行都变，模拟临时凭据）
API_KEY = os.environ.get("AGENT_API_KEY") or secrets.token_hex(16)

# ===== 速率限制（内存存储，进程内计数）=====
limiter = Limiter(
    get_remote_address,          # flask-limiter 3.x 推荐传 key_func 为第一参数
    app=app,
    default_limits=["60 per minute"],   # 全局兜底限流
    storage_uri="memory://",            # 显式声明内存存储；生产多实例改 redis://
)

# ===== 常量 =====
PORT = 8443                        # HTTPS 演示端口（生产用 443，最小权限只开必要端口）
DASHSCOPE_MODEL = "qwen-plus"


# ============================================================
# 第 4 层防御：安全响应头（所有响应统一附加）
# ============================================================

@app.after_request
def add_security_headers(response):
    """为所有响应附加安全响应头，防嗅探/防点击劫持/限缩引用泄露"""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'none'"
    return response


# ============================================================
# 第 2 层防御：API Key 认证装饰器
# ============================================================

def require_api_key(func):
    """API Key 校验装饰器：缺失或错误返回 401

    支持两种凭据传递方式：
    - 请求头 X-API-Key: <key>
    - 请求头 Authorization: Bearer <key>（与 A2A bearer 方案对齐）
    """
    import functools

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        key = request.headers.get("X-API-Key") or ""
        if not key:
            auth = request.headers.get("Authorization") or ""
            if auth.startswith("Bearer "):
                key = auth[7:]
        if not key or not secrets.compare_digest(key, API_KEY):
            # 用 secrets.compare_digest 做恒时比较，防时序攻击逐位猜 Key
            logger.warning(f"认证失败 ip={get_remote_address()}")
            return jsonify({"error": {"code": 401, "message": "Invalid or missing API Key"}}), 401
        return func(*args, **kwargs)
    return wrapper


# ============================================================
# /health 健康检查（豁免认证——探活端点必须无凭据可访问）
# ============================================================

@app.route("/health", methods=["GET"])
def health():
    """健康检查：不暴露敏感信息，仅状态与协议"""
    return jsonify({"status": "ok", "https": True, "auth": "api-key", "model": DASHSCOPE_MODEL})


# ============================================================
# 核心业务路由：认证 + 限流 + HTTPS 三层防护叠加
# ============================================================

@app.route("/v1/chat/completions", methods=["POST"])
@limiter.limit("5 per minute")     # 第 3 层：按 IP 限流（教学值设小，方便验证 429）
@require_api_key                   # 第 2 层：认证
def chat_completions():
    """OpenAI 兼容 Chat API（安全加固版）"""
    request_id = uuid.uuid4().hex[:8]

    # 输入校验（防滥用：限制 messages 长度）
    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({"error": {"code": 400, "message": "Invalid JSON body"}}), 400

    messages = data.get("messages", [])
    max_tokens = min(data.get("max_tokens", 512), 1024)   # 上限截断，防资源滥用
    temperature = data.get("temperature", 0.7)

    if not messages or len(messages) > 20:
        return jsonify({"error": {"code": 400, "message": "messages 为空或超过 20 条"}}), 400

    logger.info(f"[{request_id}] 认证+限流通过，开始处理")

    # LLM 调用（dashscope API 替代教材本地 GPU 推理）
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
        usage = {
            "prompt_tokens": response.usage.input_tokens,
            "completion_tokens": response.usage.output_tokens,
            "total_tokens": response.usage.total_tokens,
        }
    except Exception as e:
        logger.error(f"[{request_id}] LLM 调用失败: {e}")
        return jsonify({"error": {"code": 502, "message": f"Upstream LLM error: {e}"}}), 502

    logger.info(f"[{request_id}] 完成 耗时={int((time.time()-t0)*1000)}ms")

    # OpenAI 兼容响应（修复教材 torch.time bug）
    return jsonify({
        "id": f"chatcmpl-{request_id}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": DASHSCOPE_MODEL,
        "choices": [{"index": 0,
                     "message": {"role": "assistant", "content": content},
                     "finish_reason": "stop"}],
        "usage": usage,
    })


# ============================================================
# main 入口：HTTPS(adhoc) 启动 + 4 项安全 self-test
# ============================================================

def _wait_server(url: str, timeout: float = 10.0) -> bool:
    """等待 HTTPS 服务器就绪（verify=False 忽略自签名证书告警）"""
    import requests, urllib3
    urllib3.disable_warnings()
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            requests.get(url, timeout=2, verify=False)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def run_self_test():
    """验证四层防御：HTTPS 可达 / 401 认证 / 正常调用 / 429 限流"""
    import requests, urllib3
    urllib3.disable_warnings()
    base = f"https://localhost:{PORT}"
    headers = {"X-API-Key": API_KEY}
    ok = True

    print("\n" + "=" * 60)
    print("  Flask 安全加固服务 —— Self Test")
    print(f"  本轮 API Key: {API_KEY[:8]}...（环境变量可固定）")
    print("=" * 60)

    if not _wait_server(f"{base}/health"):
        print("  [失败] 服务器未在 10s 内启动")
        return False

    # Test 1: HTTPS 可达（传输加密验证）
    print("\n--- Test 1: HTTPS 可达（adhoc 自签名证书）---")
    try:
        r = requests.get(f"{base}/health", timeout=5, verify=False)
        assert r.json()["status"] == "ok"
        print("  [通过] HTTPS 握手成功，/health 正常")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 2: 无凭据访问 → 401（认证层验证）
    print("\n--- Test 2: 无 API Key 访问 → 期待 401 ---")
    try:
        r = requests.post(f"{base}/v1/chat/completions", timeout=5, verify=False,
                          json={"messages": [{"role": "user", "content": "hi"}]})
        assert r.status_code == 401, f"期待 401 实际 {r.status_code}"
        print(f"  [通过] 401 Invalid or missing API Key")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 3: 带正确 Key → 200（真实 LLM 调用）
    print("\n--- Test 3: 带正确 API Key（真实 DashScope 调用）---")
    try:
        r = requests.post(f"{base}/v1/chat/completions", timeout=30, verify=False,
                          headers=headers,
                          json={"messages": [{"role": "user", "content": "1+1 等于几？只回答数字。"}],
                                "max_tokens": 64})
        data = r.json()
        assert r.status_code == 200 and data["choices"][0]["message"]["content"]
        print(f"  [通过] answer={data['choices'][0]['message']['content'][:20]}")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    # Test 4: 连续请求触发限流 → 429（限流层验证）
    # 限流 5/min，Test 2/3 已消耗 2 次（401 也计数），再连发 5 次必触发 429
    print("\n--- Test 4: 连发 5 次触发限流 → 期待出现 429 ---")
    try:
        codes = []
        for _ in range(5):
            r = requests.post(f"{base}/v1/chat/completions", timeout=30, verify=False,
                              headers=headers,
                              json={"messages": [{"role": "user", "content": "ping"}],
                                    "max_tokens": 16})
            codes.append(r.status_code)
        has_429 = 429 in codes
        print(f"  状态码序列: {codes}")
        assert has_429, "未触发限流"
        print("  [通过] 限流生效，出现 429 Too Many Requests")
    except Exception as e:
        print(f"  [失败] {e}"); ok = False

    print(f"\n{'=' * 60}")
    print(f"  {'全部 4 项 self-test 通过' if ok else '存在失败项'}")
    print(f"{'=' * 60}")
    return ok


if __name__ == "__main__":
    # 后台线程启动 HTTPS 服务
    # ssl_context="adhoc"：Flask 内置自动生成临时自签名证书（需 cryptography 库）
    # 教材的 load_cert_chain('cert.pem','key.pem') 在证书不存在时直接崩溃；
    # 生产环境替换为正式证书路径即可
    threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=PORT,
                               ssl_context="adhoc", use_reloader=False),
        daemon=True,
    ).start()

    success = run_self_test()

    print(f"\n手动调用示例（自签名证书需 -k 跳过校验）：")
    print(f"  curl -k https://localhost:{PORT}/health")
    print(f"  curl -k -X POST https://localhost:{PORT}/v1/chat/completions \\")
    print(f"       -H 'X-API-Key: <your-key>' -H 'Content-Type: application/json' \\")
    print(f"       -d '{{\"messages\":[{{\"role\":\"user\",\"content\":\"你好\"}}]}}'")

    sys.exit(0 if success else 1)
