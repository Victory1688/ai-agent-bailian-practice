# 【例10-2】身份认证与能力声明
#
# 核心价值：
#   解决多智能体系统中的"信任问题"，防止恶意节点接入或越权操作。
#   通过标准化的能力声明，帮助调度中心实现任务与智能体的最佳匹配。
#
# ★ 重要改写说明：按 A2A Protocol v1.0 规范改写
#   教材原版是 AgentRegistry + 手动 token/signature + capabilities 列表，
#   这是 A2A v1.0 Agent Card 核心组件的教学简化版。
#   本次改写严格对齐 A2A v1.0 规范：
#
#   ① Agent Card 中的 authentication 字段（Bearer/Basic/ApiKey/JWT）
#   ② Agent Card 中的 skills 列表（id + description + tags）
#   ③ Agent Card 中的 capabilities 对象（streaming/pushNotifications）
#   ④ JSON-RPC 2.0 信封 + HTTP Authorization 头
#   ⑤ 能力自动匹配：客户端根据 Agent Card skills 自动路由
#
#   原代码全部注释保留。

# ============================================================
# 原代码（注释保留——教材简化版，不符合 A2A v1.0 规范）
# ============================================================
# import time
# import uuid
# import hashlib
# import json
# from typing import Dict, List, Any
#
# class AgentRegistry:
#     def __init__(self): self.agents = {}
#     def register_agent(self, name, token, signature, capabilities): ...
#     def is_authenticated(self, name, token, signature): ...
#     def has_capability(self, name, task): ...
#
# def build_secure_message(sender, receiver, task, params, token, signature): ...
# class Agent:
#     def __init__(self, name): self.name = name
#     def handle(self, message): ...
#
# # 模拟执行：手动注册 + 手动 dispatch + token/signature 校验 + capabilities 检查
# ============================================================

import uuid
import json
import hashlib
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

# ============ A2A v1.0 规范常量（与 01 篇保持一致） ============
JSONRPC_VERSION = "2.0"
PART_KINDS = Literal_ = ["text", "file", "data"]

# ============ A2A v1.0 Agent Card 构建器（完整规范） ============

def build_agent_card(
    name: str,
    description: str,
    skills: List[Dict[str, Any]],
    endpoint: str = "http://localhost:8080/a2a",
    auth_schemes: Optional[List[str]] = None,
    capabilities: Optional[Dict[str, bool]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """构建 A2A v1.0 Agent Card

    Agent Card 是 Agent 的"数字名片"，发布在 /.well-known/agent.json，
    让客户端自动发现 Agent 的身份、能力、认证方式和可用技能。
    对应规范：A2A v1.0 § Core Concepts → Agent Card
    """
    if auth_schemes is None:
        auth_schemes = ["bearer"]
    if capabilities is None:
        capabilities = {
            "streaming": False,
            "pushNotifications": False,
            "stateTransitionHistory": False,
        }
    card: Dict[str, Any] = {
        "name": name,
        "description": description,
        "endpoint": endpoint,
        "authentication": {
            "schemes": auth_schemes,
            # credentials 生产环境不应嵌入 Card；教学简化版展示声明格式
            "credentials": f"Bearer {hashlib.sha256(name.encode()).hexdigest()[:24]}",
        },
        "capabilities": capabilities,
        "skills": skills,
    }
    if metadata:
        card["metadata"] = metadata
    return card


def build_skill(
    skill_id: str,
    description: str,
    tags: Optional[List[str]] = None,
    input_modes: Optional[List[str]] = None,
    output_modes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """构建 A2A v1.0 Skill 对象（Agent Card 中的能力声明）

    对应规范：A2A v1.0 § Core Concepts → Skill
    注意：Skill 的 id 不是 task 名的简单匹配，而是语义描述，
    客户端可以基于 description + tags 做 LLM 语义匹配
    """
    if tags is None:
        tags = []
    if input_modes is None:
        input_modes = ["text"]
    if output_modes is None:
        output_modes = ["text"]
    return {
        "id": skill_id,
        "description": description,
        "tags": tags,
        "inputModes": input_modes,
        "outputModes": output_modes,
    }


# ============ A2A v1.0 消息构建器（JSON-RPC 2.0 信封） ============

def build_jsonrpc_request(
    method: str,
    message: Dict[str, Any],
    req_id: Optional[str] = None,
    auth_header: Optional[str] = None,
) -> Dict[str, Any]:
    """构建 A2A JSON-RPC 2.0 请求信封

    与教材 build_secure_message 的差异：
      ① 不用自定义 from/to/intent/payload/auth 字段
      ② 用 JSON-RPC 标准信封（jsonrpc/id/method/params）
      ③ 认证走 HTTP Authorization 头（不在 JSON body 里）
    """
    if req_id is None:
        req_id = f"req-{uuid.uuid4().hex[:12]}"
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": req_id,
        "method": method,   # "message.send" / "message/stream" / "tasks/get"
        "params": {
            "message": message,
        },
        # 真实 A2A 传输层里认证走 HTTP 头：
        # Authorization: Bearer <token>
        # 本次同进程模拟，auth_header 存在 params 里展示
        "_auth_header": auth_header,
    }


def build_message(role: str, parts: List[Dict[str, Any]],
                  context_id: Optional[str] = None) -> Dict[str, Any]:
    """构建 A2A Message 对象（与 01 篇一致）"""
    msg: Dict[str, Any] = {
        "messageId": f"msg-{uuid.uuid4().hex[:12]}",
        "role": role,
        "parts": parts,
    }
    if context_id:
        msg["contextId"] = context_id
    return msg


# ============ A2A v1.0 Agent Server（含认证 + 能力匹配） ============

class A2AServer:
    """A2A Agent 服务端

    职责：
      ① 发布 Agent Card（自动发现入口）
      ② 校验 Authorization 头（Bearer token）
      ③ 根据 skills 自动匹配请求
      ④ 返回 Task（有状态）或 Message（无状态）

    教材简化版：AgentRegistry 手动注册 + 手动 token/signature 校验 + if/elif capabilities 检查
    规范版：    Agent Card 自动发现 + HTTP Bearer 认证 + skills 语义匹配
    """

    def __init__(
        self,
        name: str,
        description: str,
        skills: List[Dict[str, Any]],
        server_token: str,
    ):
        self.name = name
        self.server_token = server_token   # Agent 自己的认证 token（生产用非对称签名）
        # 构建 Agent Card
        self.agent_card = build_agent_card(
            name=name,
            description=description,
            skills=skills,
            auth_schemes=["bearer"],
        )
        # 提取 skills 做快速匹配（生产用 LLM 语义匹配）
        self._skill_ids = {s["id"] for s in skills}

    # ===== 认证校验 =====

    def verify_auth(self, auth_header: Optional[str]) -> bool:
        """校验 HTTP Authorization 头（A2A v1.0 认证方式）

        教材简化版：比对 token == token 且 signature == signature
        规范版：    Bearer token 比对（生产用 JWT / 非对称签名验证）
        """
        if not auth_header:
            return False
        # 规范格式：Authorization: Bearer <token>
        parts = auth_header.split(" ", 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return False
        return parts[1] == self.server_token

    # ===== 能力匹配 =====

    def match_skill(self, user_text: str) -> Optional[str]:
        """根据 Agent skills 匹配用户请求（教学简化：关键词匹配；生产：LLM 语义匹配）

        匹配策略（按优先级）：
          ① skill description 中文关键词（"摘要"、"翻译"等直接命中）
          ② skill tags 关键词
          ③ skill id 的英文单词（兜底匹配英文请求）
        """
        user_lower = user_text.lower()

        # ① 先匹配 skill description 里的中文关键词（description 本身用中文写）
        for skill in self.agent_card["skills"]:
            desc = skill.get("description", "")
            # 中文：description 里的每个字/词都可能是命中点
            for char in desc:
                if char in user_text and char.strip():
                    return skill["id"]

        # ② 匹配 skill tags
        for skill in self.agent_card["skills"]:
            for tag in skill.get("tags", []):
                if tag.lower() in user_lower:
                    return skill["id"]

        # ③ 兜底：匹配 skill id 的英文单词
        for skill in self.agent_card["skills"]:
            skill_id = skill["id"].lower()
            words = skill_id.replace("_", " ").replace("-", " ").split()
            if any(w in user_lower for w in words if len(w) >= 3):
                return skill["id"]

        return None

    # ===== A2A message.send 实现 =====

    def message_send(self, message: Dict[str, Any], auth_header: Optional[str] = None) -> Dict[str, Any]:
        """实现 JSON-RPC message.send（A2A 核心操作）"""
        # Step 1: 认证校验
        if not self.verify_auth(auth_header):
            return {
                "error": {
                    "code": -32001,
                    "message": "Authentication failed",
                },
            }

        # Step 2: 提取用户消息
        user_text = ""
        for part in message.get("parts", []):
            if part.get("kind") == "text":
                user_text += part.get("text", "")

        # Step 3: 能力匹配（自动路由）
        skill_id = self.match_skill(user_text)
        if skill_id is None:
            # 能力不匹配 → 返回 A2A error（对应规范 § Error Handling）
            return {
                "error": {
                    "code": -32002,
                    "message": f"Agent {self.name} has no matching skill for: {user_text[:50]}",
                    "data": {
                        "availableSkills": [s["id"] for s in self.agent_card["skills"]],
                    },
                },
            }

        # Step 4: 执行匹配到的 skill（教学简化模拟）
        context_id = message.get("contextId") or f"ctx-{uuid.uuid4().hex[:12]}"
        response_text = f"[{self.name}] 执行 skill={skill_id}: 完成（规范版实现）"

        # Step 5: 返回 A2A Task（completed 状态）
        return {
            "id": f"task-{uuid.uuid4().hex[:12]}",
            "contextId": context_id,
            "status": {
                "state": "completed",
                "message": {
                    "role": "agent",
                    "parts": [{"kind": "text", "text": response_text}],
                },
            },
            "kind": "task",
            "artifacts": [
                {
                    "artifactId": f"art-{uuid.uuid4().hex[:8]}",
                    "name": f"{skill_id}_result",
                    "parts": [{"kind": "text", "text": response_text}],
                }
            ],
        }

    # ===== Agent Card 暴露 =====

    def get_agent_card(self) -> Dict[str, Any]:
        return self.agent_card


# ============ A2A Registry（按 Agent Card 自动发现） ============

class A2ARegistry:
    """A2A 注册中心——按 Agent Card 自动发现 + 能力查询

    教材简化版：手动 register_agent(name, token, signature, capabilities)
    规范版：    客户端发现 Agent Card → 按 skills 自动查询匹配
    """

    def __init__(self):
        self._agents: Dict[str, A2AServer] = {}

    def register(self, server: A2AServer):
        """注册 A2A Server（等价于"发布 Agent Card"）"""
        self._agents[server.name] = server
        card = server.get_agent_card()
        print(f"[Registry] 注册 Agent: {server.name}")
        print(f"  → endpoint: {card['endpoint']}")
        print(f"  → skills: {[s['id'] for s in card['skills']]}")
        print(f"  → auth schemes: {card['authentication']['schemes']}")

    def discover_by_skill(self, skill_keyword: str) -> List[A2AServer]:
        """按 skill 关键词自动发现 Agent（生产用 Agent Card HTTP 端点）"""
        result = []
        for server in self._agents.values():
            card = server.get_agent_card()
            for skill in card["skills"]:
                all_text = (skill["id"] + " " + skill["description"] + " " + " ".join(skill.get("tags", []))).lower()
                if skill_keyword.lower() in all_text:
                    result.append(server)
                    break
        return result

    def get(self, name: str) -> Optional[A2AServer]:
        return self._agents.get(name)


# ============ 主流程：完整 A2A v1.0 认证 + 能力匹配演示 ============

if __name__ == "__main__":
    print("=" * 60)
    print("  A2A v1.0 认证 + 能力声明演示（按 Google 2025 官方规范）")
    print("=" * 60)

    # ------ Step 1: 创建 A2A Server（按规范构建 Agent Card） ------
    print("\n--- Step 1: Agent 按 A2A v1.0 规范注册 ---")

    # 教材原版：手动 register_agent(name, token, signature, capabilities)
    # 规范版：  A2AServer 内置 Agent Card（含 auth + skills + capabilities）
    token_qwen = hashlib.sha256("agent:qwen3".encode()).hexdigest()[:32]
    token_deep = hashlib.sha256("agent:deepseek".encode()).hexdigest()[:32]

    qwen3 = A2AServer(
        name="agent:qwen3",
        description="Qwen3 多模态智能体，支持文本摘要和翻译",
        skills=[
            build_skill("text_summary", "对长文本进行压缩摘要", tags=["nlp", "summary", "text"]),
            build_skill("translate_text", "多语言文本翻译", tags=["nlp", "translate", "language"]),
        ],
        server_token=token_qwen,
    )

    deepseek = A2AServer(
        name="agent:deepseek",
        description="DeepSeek 翻译智能体，专注文本翻译",
        skills=[
            build_skill("translate_text", "中英互译", tags=["nlp", "translate"]),
        ],
        server_token=token_deep,
    )

    # 创建注册中心（按 Agent Card 自动发现）
    registry = A2ARegistry()
    registry.register(qwen3)
    registry.register(deepseek)

    # ------ Step 2: 展示 Agent Card（A2A 发现机制） ------
    print("\n--- Step 2: Agent Card 发布（/.well-known/agent.json） ---")
    print(f"\n[qwen3] Agent Card:")
    print(json.dumps(qwen3.get_agent_card(), indent=2, ensure_ascii=False))

    # ------ Step 3: 认证校验对比（教材版 vs 规范版） ------
    print("\n--- Step 3: 认证校验（Bearer token vs 教材 token+signature） ---")

    # 规范版：HTTP Bearer token（教学简化演示）
    auth_ok = f"Bearer {token_qwen}"
    auth_bad = "Bearer wrong-token"
    auth_no_header = None

    print(f"\n  ✅ 正确 Bearer token → 认证通过: {qwen3.verify_auth(auth_ok)}")
    print(f"  ❌ 错误 Bearer token → 认证失败: {qwen3.verify_auth(auth_bad)}")
    print(f"  ❌ 无 Authorization 头 → 认证失败: {qwen3.verify_auth(auth_no_header)}")

    # ------ Step 4: 能力匹配（Agent Card skills 自动路由） ------
    print("\n--- Step 4: 能力匹配（按 Agent Card skills 自动路由） ---")

    # 教材版：手动 dispatch → 手动 has_capability → 手动 Agent.handle
    # 规范版：registry.discover_by_skill(keyword) → 自动找到合适 Agent
    servers_for_summary = registry.discover_by_skill("summary")
    servers_for_translate = registry.discover_by_skill("translate")
    print(f"\n  匹配 'summary' → {[s.name for s in servers_for_summary]}")
    print(f"  匹配 'translate' → {[s.name for s in servers_for_translate]}")

    # ------ Step 5: 完整 A2A 交互演示 ------
    print("\n--- Step 5: 完整 A2A 交互（认证 + 能力匹配 + message.send） ---")

    # 场景 1：qwen3 有 text_summary skill，请求能通过
    msg1 = build_message("user", [{"kind": "text", "text": "请对这段长文本做摘要"}])
    req1 = build_jsonrpc_request("message.send", msg1, auth_header=f"Bearer {token_qwen}")
    print(f"\n  → 请求 qwen3 (summary 匹配):")
    print(f"    JSON-RPC id={req1['id']}, method={req1['method']}")
    result1 = qwen3.message_send(msg1, auth_header=req1["_auth_header"])
    print(f"    响应: {result1}")

    # 场景 2：deepseek 没有 text_summary skill → A2A error（-32002）
    msg2 = build_message("user", [{"kind": "text", "text": "请对这段长文本做摘要"}])
    req2 = build_jsonrpc_request("message.send", msg2, auth_header=f"Bearer {token_deep}")
    print(f"\n  → 请求 deepseek (summary 不匹配):")
    result2 = deepseek.message_send(msg2, auth_header=req2["_auth_header"])
    print(f"    响应: {json.dumps(result2, indent=4, ensure_ascii=False)}")

    # 场景 3：deepseek 认证失败
    req3 = build_jsonrpc_request("message.send", msg2, auth_header="Bearer wrong-token")
    print(f"\n  → 请求 deepseek (认证失败):")
    result3 = deepseek.message_send(msg2, auth_header=req3["_auth_header"])
    print(f"    响应: {json.dumps(result3, indent=4, ensure_ascii=False)}")

    print("\n" + "=" * 60)
    print("  A2A v1.0 认证 + 能力声明演示完成")
    print("=" * 60)
    print("\n教材简化 vs 规范版对比:")
    print("  • AgentRegistry → A2ARegistry（按 Agent Card 自动发现）")
    print("  • token+signature 比对 → Bearer token（A2A 标准认证）")
    print("  • capabilities 列表 → skills 对象（含 description/tags）")
    print("  • 自定义 auth payload → JSON-RPC + HTTP Authorization 头")
    print("  • if/elif 硬编码路由 → match_skill 自动匹配 + A2A error")
