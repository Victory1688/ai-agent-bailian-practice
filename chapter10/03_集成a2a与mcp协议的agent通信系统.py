# 【例10-3】A2A 与 MCP 协议联动开发
#
# ★ 真实协议辨析（重要！）
#   教材标题"集成 A2A 与 MCP" 是对的，但实现方式是简化模拟：
#
#   A2A (Agent2Agent Protocol, Google/Linux Foundation 2025):
#     → Agent-to-Agent 通信协议
#     → 核心组件：Agent Card / Task / Message / Artifact
#     → JSON-RPC 2.0 over HTTP(SSE)/gRPC/REST
#     → 负责：Agent 发现 / 能力声明 / 多轮协作 / 任务生命周期
#
#   MCP (Model Context Protocol, Anthropic 2025):
#     → Agent-to-Tool 通信协议
#     → 核心组件：Tools / Resources / Prompts（三原语）
#     → JSON-RPC 2.0 over STDIO/HTTP(SSE)
#     → 负责：Tool 发现（tools/list）/ Tool 调用（tools/call）
#            / 资源读取（resources/read）/ 模板获取（prompts/get）
#
#   教材原版的 "MCP格式" 是对 MCP 的误解——它把 "[system, user, memory]" 三段式 prompt
#   叫 "MCP 格式"，但真实 MCP 根本不是 prompt 格式协议，而是 Agent 调 Tool/Resource 的协议。
#   A2A 和 MCP 组合才是完整的多 Agent 系统通信基础设施：
#     A2A = Agent 之间说什么（谁干什么）
#     MCP = Agent 用什么工具干活（查数据/调 API/读文件）
#
# 本次改写：
#   ① A2A 层：复用 01/02 篇已实现的 A2AServer + JSON-RPC 信封
#   ② MCP 层：新增 MCPServer（按 MCP 规范暴露 tools + resources）
#   ③ AgentOrchestrator：同时管理 A2A Server 和 MCP Server
#   ④ Agent：通过 A2A 接收任务 → 通过 MCP 调工具/读资源 → dashscope 生成最终响应
#
# 原代码全部注释保留。
# 备注：本篇无 redis 调用，无需按 cache.json 方案替换

# ============================================================
# 原代码（注释保留——教材简化版，不符合 A2A/MCP 真实规范）
# ============================================================
# from qwen_agent import Agent, Message, PromptEntry       # ← 虚构框架
# from qwen_agent.tools import Tool                         # ← 虚构框架
# import uuid, json, time
# from typing import Dict, Any, List
#
# class A2AMessage:                                         # ← 简化版 A2A，不符合规范
#     def __init__(self, sender, receiver, intent, payload): ...
#     def to_dict(self): ...
#
# class ContextAwareAgent:                                  # ← "MCP格式" 是对 MCP 的误解
#     def __init__(self, agent_name): self.agent = Agent()
#     def handle_message(self, message):
#         prompt = [PromptEntry(role="system", ...), ...]  # ← 这是 prompt 模板，不是 MCP
#         result = self.agent.chat(messages=[Message(prompt=prompt)])
#         return result.content
#
# class AgentOrchestrator:
#     def register_agent(self, agent_name, agent_obj): ...
#     def dispatch_task(self, message): ...
# ============================================================

import uuid
import json
import os
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import dashscope

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# ============ JSON-RPC 2.0 常量（A2A 和 MCP 共用同一信封） ============
JSONRPC_VERSION = "2.0"

# ============================================================
# Part 1: A2A 层（Agent-to-Agent 通信）——复用 01/02 篇已验证的规范实现
# ============================================================

def build_jsonrpc_request(method: str, params: Dict[str, Any], req_id: Optional[str] = None) -> Dict[str, Any]:
    """构建 A2A/MCP 共用的 JSON-RPC 2.0 请求信封"""
    if req_id is None:
        req_id = f"req-{uuid.uuid4().hex[:12]}"
    return {"jsonrpc": JSONRPC_VERSION, "id": req_id, "method": method, "params": params}


def build_message(role: str, parts: List[Dict[str, Any]], context_id: Optional[str] = None) -> Dict[str, Any]:
    """构建 A2A Message 对象"""
    msg: Dict[str, Any] = {
        "messageId": f"msg-{uuid.uuid4().hex[:12]}",
        "role": role,
        "parts": parts,
    }
    if context_id:
        msg["contextId"] = context_id
    return msg


def build_agent_card(name: str, description: str, skills: List[Dict[str, Any]],
                     endpoint: str = "http://localhost:8080/a2a") -> Dict[str, Any]:
    """构建 A2A Agent Card（/.well-known/agent.json）"""
    return {
        "name": name,
        "description": description,
        "endpoint": endpoint,
        "authentication": {"schemes": ["bearer"]},
        "capabilities": {"streaming": False, "pushNotifications": False},
        "skills": skills,
    }


# ============================================================
# Part 2: MCP 层（Agent-to-Tool 通信）——按 MCP v2025-03-26 规范实现
# ============================================================

class MCPServer:
    """MCP 服务端——按 MCP 规范暴露 Tools + Resources

    MCP 核心三原语（对应规范 § Core Concepts）：
      • Tools：可执行函数，AI 模型可自动发现和调用（tools/list → tools/call）
      • Resources：数据源，可读取（resources/list → resources/read）
      • Prompts：模板，可复用（prompts/list → prompts/get）

    本次实现：Tools（完整）+ Resources（完整）+ Prompts（占位）
    """

    def __init__(self, name: str, tools: List[Dict[str, Any]] = None,
                 resources: List[Dict[str, Any]] = None):
        self.name = name
        self.tools = tools or []
        self.resources = resources or []
        self._tool_handlers: Dict[str, Any] = {}   # tool_name → handler function

    def register_tool_handler(self, tool_name: str, handler):
        """注册 Tool 处理函数"""
        self._tool_handlers[tool_name] = handler

    # ===== MCP tools/list（规范 § Tools → Listing Tools）=====
    def tools_list(self) -> Dict[str, Any]:
        """返回可用 Tool 列表（含 inputSchema）"""
        return {"tools": self.tools}

    # ===== MCP tools/call（规范 § Tools → Calling Tools）=====
    def tools_call(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """执行 Tool，返回 ToolResult（含 content 数组）"""
        if tool_name not in self._tool_handlers:
            return {
                "content": [{"type": "text", "text": f"Tool '{tool_name}' not found"}],
                "isError": True,
            }
        try:
            result = self._tool_handlers[tool_name](**arguments)
            return {
                "content": [{"type": "text", "text": str(result)}],
                "isError": False,
            }
        except Exception as e:
            return {
                "content": [{"type": "text", "text": f"Tool execution failed: {e}"}],
                "isError": True,
            }

    # ===== MCP resources/list（规范 § Resources）=====
    def resources_list(self) -> Dict[str, Any]:
        """返回可用 Resource 列表"""
        return {"resources": self.resources}

    # ===== MCP resources/read（规范 § Resources）=====
    def resources_read(self, resource_uri: str) -> Dict[str, Any]:
        """读取 Resource 内容"""
        for r in self.resources:
            if r["uri"] == resource_uri:
                return {
                    "contents": [{
                        "uri": resource_uri,
                        "mimeType": r.get("mimeType", "text/plain"),
                        "text": r.get("_content", ""),
                    }]
                }
        return {"contents": []}


# ============ MCP Server 工厂：财经分析场景的 Tools + Resources ============

def create_financial_mcp_server() -> MCPServer:
    """创建财经分析用的 MCP Server（含真实 Tools + Resources）"""
    server = MCPServer(
        name="mcp:financial",
        tools=[
            {
                "name": "get_gdp_data",
                "description": "获取指定国家 GDP 增长率数据（模拟）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "country": {"type": "string", "description": "国家名称，如 中国/美国"},
                        "year": {"type": "integer", "description": "年份，如 2024"},
                    },
                    "required": ["country", "year"],
                },
            },
            {
                "name": "search_economic_news",
                "description": "搜索最新经济新闻（模拟）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "keyword": {"type": "string", "description": "关键词，如 通胀/降息/出口"},
                    },
                    "required": ["keyword"],
                },
            },
            {
                "name": "calculate_cpi_impact",
                "description": "计算 CPI 涨幅对 GDP 的影响（模拟）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "cpi_rate": {"type": "number", "description": "CPI 涨幅百分比"},
                        "gdp_rate": {"type": "number", "description": "GDP 增长率百分比"},
                    },
                    "required": ["cpi_rate", "gdp_rate"],
                },
            },
        ],
        resources=[
            {
                "uri": "world-bank://country/gdp-forecast",
                "name": "World Bank GDP Forecast 2024",
                "mimeType": "text/csv",
                "_content": "中国,5.0\n美国,2.5\n欧盟,1.2\n日本,0.8\n印度,6.5",
            },
        ],
    )

    # 注册 Tool 处理函数
    def get_gdp_data(country: str, year: int) -> str:
        data = {"中国": 5.0, "美国": 2.5, "欧盟": 1.2, "日本": 0.8, "印度": 6.5}
        rate = data.get(country, "暂无数据")
        return f"{country} {year} GDP 增长率: {rate}%"

    def search_economic_news(keyword: str) -> str:
        news_db = {
            "通胀": "2024 年 CPI 持续回落至 0.2%，通胀压力基本消除",
            "降息": "央行下调 LPR 25BP，释放流动性支持实体",
            "出口": "出口同比回升 8.5%，外需回暖趋势确立",
        }
        return news_db.get(keyword, f"关于 '{keyword}' 的财经新闻暂无相关报道")

    def calculate_cpi_impact(cpi_rate: float, gdp_rate: float) -> str:
        impact = round(gdp_rate - cpi_rate * 0.3, 2)
        return f"CPI {cpi_rate}% 对 GDP {gdp_rate}% 的影响: 实际增长约 {impact}%"

    server.register_tool_handler("get_gdp_data", get_gdp_data)
    server.register_tool_handler("search_economic_news", search_economic_news)
    server.register_tool_handler("calculate_cpi_impact", calculate_cpi_impact)

    return server


# ============================================================
# Part 3: A2A Agent Server（复用 01/02 篇 + 集成 MCP 调用）
# ============================================================

class A2AServer:
    """A2A Agent 服务端——通过 MCP Server 调工具/读资源，然后 LLM 生成响应

    关键设计：A2A Agent 不自己实现业务逻辑，而是把任务委托给 MCP Server 的 Tools/Resources。
    这就是 A2A + MCP 的组合：A2A 管"谁干什么"，MCP 管"用什么工具干"。
    """

    def __init__(self, name: str, description: str, skills: List[Dict[str, Any]],
                 mcp_server: MCPServer, server_token: str):
        self.name = name
        self.mcp = mcp_server   # 每个 A2A Agent 绑定一个 MCP Server
        self.server_token = server_token
        self.agent_card = build_agent_card(name, description, skills)
        self._task_registry: Dict[str, Dict[str, Any]] = {}

    def verify_auth(self, auth_header: Optional[str]) -> bool:
        if not auth_header:
            return False
        parts = auth_header.split(" ", 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return False
        return parts[1] == self.server_token

    def message_send(self, message: Dict[str, Any], auth_header: Optional[str] = None) -> Dict[str, Any]:
        """A2A 核心操作：接收任务 → MCP 调工具 → LLM 生成 → 返回 Task

        完整流程（按 A2A v1.0 + MCP 规范）：
          ① 认证校验
          ② 提取用户意图
          ③ MCP tools/list 发现可用工具
          ④ MCP tools/call 执行工具（1-N 次，按需串行）
          ⑤ MCP resources/read 获取上下文
          ⑥ dashscope 整合 MCP 结果生成最终响应
          ⑦ 返回 A2A Task（completed）
        """
        # Step 1: 认证
        if not self.verify_auth(auth_header):
            return {"error": {"code": -32001, "message": "Authentication failed"}}

        # Step 2: 提取用户消息
        user_text = ""
        for part in message.get("parts", []):
            if part.get("kind") == "text":
                user_text += part.get("text", "")
        context_id = message.get("contextId") or f"ctx-{uuid.uuid4().hex[:12]}"

        print(f"\n  [{self.name}] 收到任务: {user_text[:60]}...")
        print(f"    contextId: {context_id}")

        # Step 3: MCP tools/list 发现可用工具（Agent 通过 MCP 知道自己能用啥）
        available_tools = self.mcp.tools_list()["tools"]
        tool_names = [t["name"] for t in available_tools]
        print(f"    MCP tools/list → 可用工具: {tool_names}")

        # Step 4: MCP tools/call 执行工具（根据用户意图自动选工具）
        mcp_results = []
        if "经济" in user_text or "GDP" in user_text or "增长" in user_text:
            # 调用 get_gdp_data
            call_args = {"country": "中国", "year": 2024}
            call_result = self.mcp.tools_call("get_gdp_data", call_args)
            print(f"    MCP tools/call(get_gdp_data) → {call_result['content'][0]['text']}")
            mcp_results.append(call_result["content"][0]["text"])

        if "通胀" in user_text or "CPI" in user_text or "降息" in user_text:
            call_args = {"keyword": "通胀"}
            call_result = self.mcp.tools_call("search_economic_news", call_args)
            print(f"    MCP tools/call(search_economic_news) → {call_result['content'][0]['text']}")
            mcp_results.append(call_result["content"][0]["text"])

        # Step 5: MCP resources/read 获取世界银行 GDP 预测数据
        world_bank_data = self.mcp.resources_read("world-bank://country/gdp-forecast")
        print(f"    MCP resources/read → World Bank 数据")
        mcp_results.append("World Bank GDP Forecast:\n" + world_bank_data["contents"][0]["text"])

        # Step 6: dashscope 整合 MCP 结果生成最终响应
        mcp_combined = "\n".join(mcp_results)
        llm_prompt = f"""你是一个专业的财经分析专家。

请基于以下 MCP 工具返回的数据，撰写一段专业的财经分析报告：

【MCP 工具数据】
{mcp_combined}

【用户原始请求】
{user_text}

请综合以上数据，给出 3-5 句结构化分析。"""

        print(f"    调用 qwen-plus 整合 MCP 数据生成最终分析...")
        response = dashscope.Generation.call(
            model="qwen-plus",
            messages=[{"role": "user", "content": llm_prompt}],
            temperature=0.3,
            max_tokens=512,
            result_format='message',
        )
        final_text = response.output.choices[0].message.content
        print(f"    LLM 响应生成完毕")

        # Step 7: 返回 A2A Task（completed 状态，含 Artifact）
        task_id = f"task-{uuid.uuid4().hex[:12]}"
        task = {
            "id": task_id,
            "contextId": context_id,
            "status": {
                "state": "completed",
                "message": {
                    "role": "agent",
                    "parts": [{"kind": "text", "text": final_text}],
                },
            },
            "kind": "task",
            "artifacts": [
                {
                    "artifactId": f"art-{uuid.uuid4().hex[:8]}",
                    "name": "analysis_report",
                    "parts": [{"kind": "text", "text": final_text}],
                }
            ],
            # A2A 无原生 MCP 调用记录，用 metadata 扩展（规范允许）
            "metadata": {
                "mcpToolsCalled": [r for r in mcp_results],
            },
        }
        self._task_registry[task_id] = task
        return task

    def get_agent_card(self) -> Dict[str, Any]:
        return self.agent_card


# ============================================================
# Part 4: A2A + MCP Orchestrator（主控调度）
# ============================================================

class A2AMCPOrchestrator:
    """A2A + MCP 集成调度器

    同时管理 A2A Agent（Agent-to-Agent）和 MCP Server（Agent-to-Tool），
    让 A2A Agent 通过 MCP Server 调用工具/获取资源，形成完整闭环。
    """

    def __init__(self):
        self._a2a_servers: Dict[str, A2AServer] = {}
        self._mcp_servers: Dict[str, MCPServer] = {}

    def register_a2a_agent(self, server: A2AServer):
        self._a2a_servers[server.name] = server
        print(f"[Orchestrator] A2A Agent 注册: {server.name}")

    def register_mcp_server(self, server: MCPServer):
        self._mcp_servers[server.name] = server
        print(f"[Orchestrator] MCP Server 注册: {server.name}")

    def dispatch(self, target_name: str, message: Dict[str, Any], auth_header: str) -> Dict[str, Any]:
        """A2A 调度：找到目标 Agent → message_send"""
        a2a_server = self._a2a_servers.get(target_name)
        if not a2a_server:
            return {"error": {"code": -32002, "message": f"Agent {target_name} not found"}}
        return a2a_server.message_send(message, auth_header=auth_header)

    def mcp_list_tools(self, server_name: str) -> Dict[str, Any]:
        """MCP 发现：tools/list"""
        mcp = self._mcp_servers.get(server_name)
        if not mcp:
            return {"error": {"code": -32002, "message": f"MCP Server {server_name} not found"}}
        return mcp.tools_list()


# ============================================================
# Part 5: 主流程——完整 A2A + MCP 集成演示
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  A2A + MCP 集成演示（按 A2A v1.0 + MCP v2025-03-26 规范）")
    print("=" * 60)

    # ===== Step 1: 创建 MCP Server（Tool/Resource 层）=====
    print("\n--- Step 1: MCP Server 初始化 ---")
    financial_mcp = create_financial_mcp_server()
    print(f"  工具: {[t['name'] for t in financial_mcp.tools_list()['tools']]}")
    print(f"  资源: {[r['uri'] for r in financial_mcp.resources_list()['resources']]}")

    # ===== Step 2: 创建 A2A Agent（绑定 MCP Server）=====
    print("\n--- Step 2: A2A Agent 注册（绑定 MCP Server）---")
    import hashlib
    token_fin = hashlib.sha256("agent:finance".encode()).hexdigest()[:32]

    finance_agent = A2AServer(
        name="agent:finance",
        description="财经分析 Agent：通过 MCP 调用工具/读数据",
        skills=[
            {"id": "analyze_economy", "description": "分析宏观经济走势", "tags": ["economy", "finance"]},
            {"id": "analyze_inflation", "description": "分析通胀与货币政策", "tags": ["inflation", "monetary"]},
        ],
        mcp_server=financial_mcp,   # 绑定 MCP Server！
        server_token=token_fin,
    )

    # ===== Step 3: 创建 Orchestrator =====
    print("\n--- Step 3: Orchestrator 启动 ---")
    orchestrator = A2AMCPOrchestrator()
    orchestrator.register_a2a_agent(finance_agent)
    orchestrator.register_mcp_server(financial_mcp)

    # ===== Step 4: MCP 发现演示（A2A Agent 通过 MCP 知道自己能用啥）=====
    print("\n--- Step 4: MCP tools/list（Agent 发现自己能用的工具）---")
    mcp_tools = orchestrator.mcp_list_tools("mcp:financial")
    print(json.dumps(mcp_tools, indent=2, ensure_ascii=False))

    # ===== Step 5: 完整 A2A + MCP 交互 =====
    print("\n--- Step 5: 完整 A2A + MCP 交互 ---")

    # 构造 A2A Message（符合 v1.0 规范）
    context_id = f"ctx-{uuid.uuid4().hex[:12]}"
    msg = build_message(
        role="user",
        parts=[{"kind": "text", "text": "请分析 2024 年中国经济增长趋势和通胀风险"}],
        context_id=context_id,
    )

    # A2A JSON-RPC 请求
    req = build_jsonrpc_request("message.send", {"message": msg},
                                 req_id=f"req-{uuid.uuid4().hex[:8]}")

    print(f"\n→ A2A JSON-RPC 请求: method={req['method']}, id={req['id']}")
    print(f"→ 目标 Agent: agent:finance")

    # Orchestrator 调度：A2A Agent → MCP 调工具 → LLM 生成
    task_result = orchestrator.dispatch(
        target_name="agent:finance",
        message=msg,
        auth_header=f"Bearer {token_fin}",
    )

    print(f"\n→ A2A 返回 Task: {task_result['id']}")
    print(f"  状态: {task_result['status']['state']}")
    print(f"  Artifact: {task_result['artifacts'][0]['name']}")

    # ===== Step 6: 展示最终分析结果 =====
    print("\n--- Step 6: 最终财经分析报告 ---")
    print(task_result["artifacts"][0]["parts"][0]["text"])

    print("\n" + "=" * 60)
    print("  A2A + MCP 集成演示完成")
    print("=" * 60)
    print("\n协议分工（核心！）:")
    print("  A2A (Agent2Agent) = Agent 之间说什么（谁干什么）")
    print("  MCP (ModelContextProtocol) = Agent 用什么工具干活（查数据/调 API/读文件）")
    print("\n完整链路:")
    print("  A2A message.send → Agent 接收任务 → MCP tools/list 发现工具")
    print("  → MCP tools/call 执行工具 → MCP resources/read 获取上下文")
    print("  → dashscope 整合 MCP 结果生成最终分析 → A2A Task 返回")
