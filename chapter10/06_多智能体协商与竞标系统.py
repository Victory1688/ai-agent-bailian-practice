# 【例10-6】多智能体协商与竞标系统
#
# ★ 教材简化 vs 真实 A2A 规范
#
# 教材原版：
#   class BidMessage(sender, task, proposal, score)         # 自定义竞标消息
#   class CompetitiveAgent(name, expertise, capability_score)  # qwen_agent 虚构框架
#   class TaskOrchestrator(register, dispatch_task)
#     → dispatch_task() 里直接遍历 Agent 调 bid_for_task()，随机评分
#
# 真实 A2A v1.0 协议中的协商与竞标：
#
#   A2A 协议没有专门的"竞标"RPC 方法——竞标是在基本 message.send 之上
#   组合出的多 Agent 协作模式：
#
#   ① Orchestrator 侧（对应例 10-5 的 Publisher + 例 10-2 的 A2ARegistry）：
#     • 在 Agent Registry 注册所有参与 Agent
#     • broadcast task.submitted Notification（例 10-5 Pub/Sub）
#     • 收到多个 Agent 的 message.send 投标响应
#     • 评标（按 Agent Card skills 匹配度 + 投标内容质量）
#     • 通知中标者 → 中标者 process → Artifact 交付
#
#   ② 投标 Agent 侧（对应例 10-4 的 RequestAgent + 例 10-2 的 ResponderAgent）：
#     • subscribeToTask(taskId)（例 10-5）
#     • 收到 task.submitted Notification
#     • 评估自己是否有能力（Agent Card skills 匹配）
#     • 生成投标 proposal（dashscope 调用）
#     • message.send 投标（例 10-4 Request-Response）
#
#   核心区别：
#     教材：dispatch_task() 内部 for 循环 → 主动拉模式
#     A2A：broadcast Notification → Agent 主动投标 → 推模式
#     教材：evaluate_score() 用 random.uniform 模拟评分
#     A2A：评分基于 Agent Card skills 匹配度 + 可选的 LLM 评标
#
# 本次改写：
#   ① Orchestrator 用 Agent Registry 管理参与者 + Pub/Sub 广播
#   ② 投标 Agent 用 subscribeToTask 订阅 + message.send 投标
#   ③ 评分改用 Agent Card skills 匹配度（例 10-2 模式）
#   ④ 评标可调用 dashscope 做 LLM 评标

# ============================================================
# 原代码（注释保留——教材简化版，不符合 A2A 真实规范）
# ============================================================
# from qwen_agent import Agent, Message, PromptEntry       # ← 虚构框架
# import uuid, time, random
# from typing import Dict, List
#
# class BidMessage(sender, task, proposal, score):          # ← 自定义竞标消息
#
# class CompetitiveAgent(name, expertise, capability_score):
#     def bid_for_task(self, task_desc) -> BidMessage: ...  # ← qwen_agent 虚构框架
#     def evaluate_score(self, content) -> float:           # ← random.uniform 模拟评分
#         return round(self.capability_score + random.uniform(-0.3, 0.3), 2)
#
# class TaskOrchestrator:
#     def register(self, agent): ...
#     def dispatch_task(self, task_desc) -> str: ...        # ← for 循环拉模式
# ============================================================

import uuid
import os
import json
import hashlib
import random
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Callable
import dashscope

api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# ============ 复用前 01-05 篇已验证的构建器 ============
JSONRPC_VERSION = "2.0"

def build_request(method: str, params: Dict[str, Any], req_id: Optional[str] = None) -> Dict[str, Any]:
    """构建 JSON-RPC 2.0 Request"""
    if req_id is None:
        req_id = f"req-{uuid.uuid4().hex[:12]}"
    return {"jsonrpc": JSONRPC_VERSION, "id": req_id, "method": method, "params": params}

def build_notification(method: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """构建 JSON-RPC 2.0 Notification（无 id，单向广播）"""
    return {"jsonrpc": JSONRPC_VERSION, "method": method, "params": params}

def build_response(req_id: str, result: Dict[str, Any]) -> Dict[str, Any]:
    """构建 JSON-RPC 2.0 Response"""
    return {"jsonrpc": JSONRPC_VERSION, "id": req_id, "result": result}


# ============================================================
# Part 1: 投标 Agent（BidderAgent）——订阅 Task + 生成投标
# ============================================================

class BidderAgent:
    """投标 Agent——订阅 Orchestrator 广播的 Task，评估自己能力，生成投标方案

    A2A 协议映射：
      • 订阅: subscribeToTask(taskId)（业务方法调用）
      • 投标: message.send（发送 A2A Message，含 proposal + bid 分数）
      • 能力声明: Agent Card skills（例 10-2 模式）
    """

    def __init__(self, name: str, skills: List[Dict[str, Any]],
                 base_capability: float = 8.5):
        self.name = name
        self.base_capability = base_capability  # 基础能力分 7-9
        self.agent_card = {
            "name": name,
            "description": f"专业 Agent",
            "endpoint": "http://localhost:8080/a2a",
            "skills": skills,
        }

    def match_skill(self, task_description: str) -> float:
        """评估自己对某个 Task 的匹配度（Agent Card skills 匹配）

        返回 0.0-1.0 之间的匹配分数，0 表示不匹配，1 表示完全匹配。
        用关键词匹配（简化版，例 10-2 的三级匹配思路）。
        """
        text_lower = task_description.lower()
        matches = 0
        total = len(self.agent_card["skills"])
        if total == 0:
            return 0.0

        for skill in self.agent_card["skills"]:
            skill_id = skill.get("id", "").lower()
            desc = skill.get("description", "").lower()
            tags = " ".join(skill.get("tags", [])).lower()

            # 三级匹配（优先中文描述 → tags → skill_id）
            found = False
            for char in desc:
                if char.strip() and char in task_description:
                    found = True
                    break
            if not found:
                for tag in skill.get("tags", []):
                    if tag.lower() in text_lower or tag in task_description:
                        found = True
                        break
            if not found and skill_id and skill_id in text_lower:
                found = True

            if found:
                matches += 1

        return matches / total

    def generate_bid_proposal(self, task_description: str) -> str:
        """用 dashscope 生成投标方案"""
        skills_desc = "; ".join(
            f"{s.get('id', '')}({s.get('description', '')})"
            for s in self.agent_card["skills"]
        )
        prompt = f"""你是一名具备以下专长的 Agent: {skills_desc}

当前任务: {task_description}

请给出 2-3 句话的任务解决策略，突出你在该领域的专长优势。"""

        print(f"    [{self.name}] 调用 dashscope 生成投标方案...")
        response = dashscope.Generation.call(
            model="qwen-plus",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=256,
            result_format='message',
        )
        return response.output.choices[0].message.content

    def create_bid(self, task_id: str, task_description: str) -> Optional[Dict[str, Any]]:
        """生成一份完整投标（含匹配度评分 + LLM proposal）

        返回:
          {"bid_id", "bidder", "taskId", "proposal", "score", "match_score"}
          或 None（如果匹配度 < 阈值，该 Agent 选择不投标）
        """
        match_score = self.match_skill(task_description)
        # 匹配度 < 0.25 不投标（Agent 主动放弃）
        if match_score < 0.25:
            print(f"  [{self.name}] 匹配度 {match_score:.2f} < 阈值，放弃投标")
            return None

        # 综合分 = 基础能力 × 匹配度（模拟 Agent 自报评分）
        combined_score = round(self.base_capability * (0.5 + 0.5 * match_score), 2)

        # 生成 proposal
        proposal = self.generate_bid_proposal(task_description)

        bid = {
            "bid_id": f"bid-{uuid.uuid4().hex[:8]}",
            "bidder": self.name,
            "taskId": task_id,
            "proposal": proposal,
            "score": combined_score,
            "match_score": round(match_score, 2),
            "agentCard": self.agent_card,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        print(f"  [{self.name}] 投标 score={combined_score}, match={match_score:.2f}")
        return bid


# ============================================================
# Part 2: BidderRegistry（Agent 注册表——例 10-2 的 A2ARegistry 模式）
# ============================================================

class BidderRegistry:
    """投标者注册表——维护所有参与竞标 Agent 的 Agent Card"""

    def __init__(self):
        self._bidders: Dict[str, BidderAgent] = {}

    def register(self, bidder: BidderAgent):
        self._bidders[bidder.name] = bidder
        print(f"  [Registry] 注册 Agent: {bidder.name}")

    def all_bidders(self) -> List[BidderAgent]:
        return list(self._bidders.values())

    def get(self, name: str) -> Optional[BidderAgent]:
        return self._bidders.get(name)


# ============================================================
# Part 3: A2ANegotiationOrchestrator（协商调度器）
# ============================================================

class A2ANegotiationOrchestrator:
    """A2A 协商调度器——Pub/Sub 广播 Task → 收集投标 → 评标 → 通知中标

    完整链路（协议层 + 业务层）：
      ① Orchestrator 创建 Task + 广播 task.submitted Notification（例 10-5 Pub/Sub）
      ② 所有 BidderAgent 收到 Notification → 评估匹配度 → 生成投标
      ③ Orchestrator 收集所有投标 → 评标（可选 dashscope 辅助）
      ④ 广播 task.completed + winner Notification → 中标者处理 Task
    """

    def __init__(self):
        self.registry = BidderRegistry()
        self._subscriptions: Dict[str, List[BidderAgent]] = {}  # task_id → [BidderAgent]
        self._bids: Dict[str, List[Dict[str, Any]]] = {}       # task_id → [bid]

    def register_bidder(self, bidder: BidderAgent):
        self.registry.register(bidder)

    # ===== 核心：广播 Task + 收集投标 =====
    def run_negotiation(self, task_description: str,
                        dashscope_evaluation: bool = True) -> Dict[str, Any]:
        """完整协商流程

        参数:
          task_description: 任务描述文本
          dashscope_evaluation: 是否用 dashscope 辅助评标

        返回:
          {"task_id", "winner", "winner_bid", "all_bids", "evaluation"}
        """
        # Step 1: 构造 Task + 广播 submitted
        task_id = f"task-{uuid.uuid4().hex[:12]}"
        print(f"\n[Orchestrator] 创建 Task: {task_id}")
        print(f"  任务描述: {task_description}")

        print(f"\n[Step 1] 广播 task.submitted Notification")
        submitted_notif = build_notification(
            "task.submitted",
            {"taskId": task_id, "description": task_description},
        )

        # Step 2: 所有 BidderAgent 收到广播 → 生成投标
        print(f"\n[Step 2] 所有 BidderAgent 评估 + 生成投标")
        all_bids: List[Dict[str, Any]] = []
        for bidder in self.registry.all_bidders():
            bid = bidder.create_bid(task_id, task_description)
            if bid:
                all_bids.append(bid)

        self._bids[task_id] = all_bids
        self._subscriptions[task_id] = list(self.registry.all_bidders())

        if not all_bids:
            return {"task_id": task_id, "winner": None, "reason": "无有效投标"}

        # Step 3: 评标
        print(f"\n[Step 3] 评标（{len(all_bids)} 份投标）")
        winner_bid = self._evaluate_bids(all_bids, use_dashscope=dashscope_evaluation)

        # Step 4: 广播中标结果
        print(f"\n[Step 4] 广播 task.completed + winner Notification")
        winner_notif = build_notification(
            "task.winner",
            {"taskId": task_id, "winner": winner_bid["bidder"], "bid": winner_bid},
        )
        print(f"  中标者: {winner_bid['bidder']}")
        print(f"  中标分: {winner_bid['score']}")

        return {
            "task_id": task_id,
            "winner": winner_bid["bidder"],
            "winner_bid": winner_bid,
            "all_bids": all_bids,
        }

    # ===== 评标方法 =====
    def _evaluate_bids(self, bids: List[Dict[str, Any]],
                       use_dashscope: bool = True) -> Dict[str, Any]:
        """评标：默认按 score 排序，可选 dashscope 辅助评标"""
        if use_dashscope and len(bids) >= 2:
            print(f"  调用 dashscope 辅助评标...")
            bids_summary = "\n".join(
                f"[{i+1}] {b['bidder']}: score={b['score']}, match={b['match_score']}"
                for i, b in enumerate(bids)
            )
            prompt = f"""请对以下投标者做一句话综合评估（30 字以内），
推荐最优投标者编号。

投标者列表:
{bids_summary}"""

            try:
                response = dashscope.Generation.call(
                    model="qwen-plus",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=128,
                    result_format='message',
                )
                eval_text = response.output.choices[0].message.content
                print(f"  LLM 评标意见: {eval_text}")
            except Exception as e:
                print(f"  LLM 评标异常 {e}，退回 score 排序")

        # 按 score 降序取第一名
        return max(bids, key=lambda b: b["score"])


# ============================================================
# Part 4: 主流程——完整 A2A 协商与竞标演示
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  例 10-6: A2A 多智能体协商与竞标系统")
    print("  Pub/Sub 广播 + message.send 投标 + Agent Card 能力匹配")
    print("=" * 60)

    # ===== Step 1: 创建 3 个投标 Agent（各有不同 skills）=====
    print("\n--- Step 1: 注册 3 个 BidderAgent ---")
    orchestrator = A2ANegotiationOrchestrator()

    # Agent 1: 宏观经济 + 汇率分析
    agent_qwen = BidderAgent(
        name="agent:qwen_finance",
        base_capability=8.7,
        skills=[
            {"id": "macro_analysis", "description": "宏观经济形势分析",
             "tags": ["宏观", "GDP", "经济"]},
            {"id": "exchange_rate", "description": "汇率波动分析",
             "tags": ["汇率", "外贸", "外汇"]},
        ],
    )

    # Agent 2: 数据挖掘 + 预测
    agent_deepseek = BidderAgent(
        name="agent:deepseek_data",
        base_capability=8.4,
        skills=[
            {"id": "data_mining", "description": "数据挖掘与预测",
             "tags": ["数据", "挖掘", "预测"]},
            {"id": "trade_analysis", "description": "外贸数据分析",
             "tags": ["外贸", "数据", "分析"]},
        ],
    )

    # Agent 3: 舆情解读 + 政策分析
    agent_coze = BidderAgent(
        name="agent:coze_sentiment",
        base_capability=8.6,
        skills=[
            {"id": "sentiment", "description": "财经舆情解读",
             "tags": ["舆情", "解读", "政策"]},
            {"id": "risk_analysis", "description": "风险评估",
             "tags": ["风险", "评估", "波动"]},
        ],
    )

    for a in [agent_qwen, agent_deepseek, agent_coze]:
        orchestrator.register_bidder(a)

    # ===== Step 2: 运行协商 =====
    print("\n--- Step 2: Orchestrator 广播 Task + 收集投标 + 评标 ---")
    result = orchestrator.run_negotiation(
        task_description="请分析人民币汇率波动对外贸企业的影响，并提出缓解建议。",
        dashscope_evaluation=True,
    )

    # ===== Step 3: 展示结果 =====
    print(f"\n{'='*60}")
    print(f"  协商结果汇总")
    print(f"{'='*60}")
    print(f"  Task ID: {result['task_id']}")
    print(f"  中标者: {result['winner']}")

    print(f"\n--- 所有投标（按 score 排序）---")
    sorted_bids = sorted(result["all_bids"], key=lambda b: b["score"], reverse=True)
    for i, bid in enumerate(sorted_bids):
        marker = " ★ 中标" if bid["bidder"] == result["winner"] else ""
        print(f"  [{i+1}] {bid['bidder']}: score={bid['score']}, match={bid['match_score']}{marker}")

    print(f"\n--- 中标投标方案 ---")
    print(result["winner_bid"]["proposal"])

    print(f"\n{'='*60}")
    print(f"  A2A 协商与竞标系统完整演示完成")
    print(f"{'='*60}")
    print("\n关键对比:")
    print("  教材 dispatch_task():  for 循环 → 主动拉模式 → 随机评分")
    print("  A2A 协商流程:          Pub/Sub 广播 → Agent 主动投标 → skills 匹配评分")
    print("\n完整链路:")
    print("  Orchestrator 创建 Task → Pub/Sub broadcast task.submitted")
    print("  → 所有 BidderAgent subscribeToTask 收到 Notification")
    print("  → 评估 Agent Card skills 匹配度 → dashscope 生成 proposal")
    print("  → Orchestrator 收集投标 → 评标 → dashscope 辅助择优")
    print("  → 中标者收到 task.winner Notification → 执行 Task")
