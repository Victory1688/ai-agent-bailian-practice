# chapter13 · TDD 指南（测试驱动开发）

> **本章主题**：从零实现一个复合智能体系统 —— 如何用 TDD 守住 11 篇代码的契约
> **配套文档**：[spec.md](spec.md)（规格契约）｜ [arch_汇总说明.md](arch_汇总说明.md)（架构总览）
> **测试代码**：`../tests/test_ch13_*.py`（11 个文件，305 个测试）
> **运行环境**：`D:/MyCode/.venv/Scripts/python.exe`（pytest 9.1.1 + dashscope 1.27.2）
> **生成日期**：2026-10-14

---

## 一、为什么 chapter13 特别需要 TDD

chapter13 是全书的收官章，也是**教材 bug 最密集的一章**。它最大的特殊性在于：

> **这一章的 09/10/11 三个文件本身就是"测试框架"，而教材的测试逻辑本身是坏的。**

| 教材测试 bug | 后果 | 本 TDD 如何守住 |
|---|---|---|
| 09：`if expected_tool in output` 文本匹配 | 工具名永不出现在自然语言回复里 → **正确率永远 0%** | `test_rates_not_all_zero` 断言 `overall > 0` |
| 10：共享 AgentExecutor 实例 | 多用户并发**串话** | `_detect_cross_talk` 纯函数 + 独立实例断言 |
| 11：`difflib` 相似度冒充事实检测 | 正确回答被 **100% 误判** | `judge_answer` 的 None/False 口径分离 |

所以 chapter13 的 TDD 有个特殊使命：**不只是测业务代码，还要测"测试框架"本身**，防止教材的死逻辑被"改写后看起来对、其实还是错"地伪装修复。

---

## 二、TDD 与 spec.md 的关系

```
spec.md（契约来源）         tdd.md（本篇）              tests/*.py（可执行）
──────────────────         ──────────────             ──────────────────
F-xx 逐文件契约      →      测什么 / 为什么    →       test_xxx() 断言
"这个函数应该..."           "如何验证它确实..."        "断言其确实如此"
```

**契约来自 spec，验证落在 test。** 比如 spec 里 F-08 写"`execute_tool` 永不抛出"，TDD 里的 `test_execute_tool_never_raises` 就穷举坏输入证明它确实不抛。

---

## 三、核心工程约束（TDD-xx）

| 编号 | 约束 | 原因 |
|------|------|------|
| TDD-01 | **只能用文件路径动态加载** | 源文件以数字开头 + 中文名，`import 01_xxx` 是语法错误 |
| TDD-02 | **测试文件命名 `test_chNN_XX_*.py`** | 13 章有大量重名（如 `01_*.py`），前缀区分避免冲突 |
| TDD-03 | **加载走 `conftest.load_chapter_module()`** | 统一缓存，避免模块级副作用（`logging.basicConfig`）重复执行 |
| TDD-04 | **纯函数测试必须确定性** | 不调 API、不依赖时间/随机，秒级完成，可反复跑 |
| TDD-05 | **LLM 调用打 `@pytest.mark.live`** | 本项目采用"全部真实调用"策略，用标记而非 mock 来控制成本 |
| TDD-06 | **临时改 `MODEL_REGISTRY` 必须 `finally` 还原** | 否则污染后续测试（源码 self-test 同款纪律） |
| TDD-07 | **断言契约而非实现** | 如断言"返回 dict 含 success 字段"，不断言具体措辞 |
| TDD-08 | **非确定行为分路径验契约** | 如月球场景"调工具"或"直答"都合理，只验 `success is True` |

---

## 四、11 篇 × 测试映射表

| 篇目 | 被测文件 | 测试文件 | 测试数 | 纯函数重点 | live 重点 |
|------|---------|---------|-------|-----------|----------|
| 01 | 标准 Agent 接口层 | `test_ch13_01_interface.py` | 25 | Message 校验 / 适配器池 | 跨模型共享上下文 |
| 02 | 用户意图识别 | `test_ch13_02_intent.py` | 38 | **extract_json 三步清洗** / schema 校验 | 真实意图识别 |
| 03 | 工具调用链与回退 | `test_ch13_03_safe_eval.py` | 43 | **safe_eval 安全边界** | 工具链执行 |
| 04 | 子状态管理与调度 | `test_ch13_04_state_machine.py` | 27 | **状态机全迁移穷举** | 任务派发 |
| 05 | RAG 检索问答 | `test_ch13_05_rag.py` | 26 | cosine / split_text / JSONCache | 嵌入缓存命中 |
| 06 | MCP 上下文路由器 | `test_ch13_06_mcp.py` | 21 | **JSON-RPC 协议层** | ask_knowledge |
| 07 | A2A 消息协议注入 | `test_ch13_07_a2a.py` | 20 | **AgentCard / Message / Task** | 技能执行 |
| 08 | 通用 Agent 主控链条 | `test_ch13_08_agent_core.py` | 33 | 工具函数 / 错误回填 | **主备回退** |
| 09 | 工具调用正确率框架 | `test_ch13_09_accuracy.py` | 27 | **三项比对函数** | 正确率实测 |
| 10 | 并发测试与压测 | `test_ch13_10_metrics.py` | 22 | **分位数 / 指标 / 串话检测** | 小并发压测 |
| 11 | 幻觉率与满意度评估 | `test_ch13_11_judge.py` | 23 | **裁判输出清洗 / 相似度** | LLM-as-a-Judge |

**合计 305 个测试**（279 个纯函数 + 26 个 live）。

---

## 五、运行方式

```bash
cd D:/AiWorkOut/aiAgentCode

# 【推荐】日常快速回归：只跑纯函数测试（约 45 秒，零 API 成本）
D:/MyCode/.venv/Scripts/python.exe -m pytest tests/ -m "not live"

# 单章测试
D:/MyCode/.venv/Scripts/python.exe -m pytest tests/test_ch13_08_agent_core.py -v

# 单个测试
D:/MyCode/.venv/Scripts/python.exe -m pytest \
  "tests/test_ch13_09_accuracy.py::test_rates_not_all_zero" -v

# 真实 API 测试（消耗 token，约 40 秒）
D:/MyCode/.venv/Scripts/python.exe -m pytest tests/ -m "live and not slow"

# 全部测试（含压测，最慢）
D:/MyCode/.venv/Scripts/python.exe -m pytest tests/
```

**环境变量**：`DASHSCOPE_API_KEY` 必须已设置（live 测试依赖）。

---

## 六、TDD 怎么"驱动"开发（不只是"测试"）

本项目的 TDD 实践遵循 **Red → Green → Refactor** 循环，以 09 篇的正确率 bug 为例：

### ① Red —— 先写会失败的测试
```python
def test_rates_not_all_zero(ch13_09):
    """修复验证：正确率不应恒为 0（教材 bug 的终极证据）"""
    m = ch13_09.run_tool_test("qwen-plus")
    assert m["overall"] > 0, "正确率恒为 0 —— 教材死逻辑未被修复"
```
**如果用的还是教材原逻辑（文本包含匹配），这个测试必然失败。**

### ② Green —— 实现到测试通过
改写为 `steps` 轨迹结构化比对后，测试转绿。

### ③ Refactor —— 在测试保护下重构
比如把 `_check_tool_name` 从"简单相等"重构为"序列比对"，测试仍然保护行为不变。

### 关键：测试先行的"先行"体现在哪
本项目的实践是**契约先行**——先读 spec.md 明确"这个函数应该怎样"，再写测试断言，最后核验实现。这是 AI 时代 TDD 的变体：**LLM 帮你写实现，但你用测试锁住契约**。

---

## 七、AI 时代的 TDD 心法（本章实践总结）

### 7.1 LLM 生成的代码，必须用测试锁住
AI 写代码快，但**会自信地写出错误的测试**——教材 09 篇就是最典型的例子（测试逻辑本身是坏的）。TDD 的价值在 AI 时代不降反升：**它是对 LLM 输出的独立验证层。**

### 7.2 测试点必须来自"代码事实"，不能来自"想象"
本 TDD 的每个断言都来自逐行读源码：
- `Message` 确实在白名单校验？→ 读 153 行确认 → 写断言
- `result` 确实 `[:120]` 截断？→ 读 323 行确认 → 写 `len(s["result"]) <= 120`

**臆造契约 = 写出永远绿的假测试。**

### 7.3 纯函数密度决定 TDD 收益
本章 TDD 的投入产出比排序：
```
状态机(04) > safe_eval(03) > JSON 清洗(02/11) > 指标计算(10) > 协议层(06/07)
```
这些都是**输入输出确定、无副作用**的模块——TDD 在这里**零成本穷举边界**，收益最大。

### 7.4 "全部真实调用"策略的取舍
本项目选择 live 测试而非 mock，理由是：**Agent 系统的失败大多发生在真实调用边界**（协议不符、参数格式、限流）。mock 会掩盖这些。代价是：
- 慢（40 秒 vs 1 秒）
- 花钱（每次消耗 token）
- 非确定（LLM 输出浮动）

**应对**：用 `-m "not live"` 做日常回归，用 `-m live` 做发布前验收。这也是 TDD-05 的设计意图。

---

## 八、已固化的三条"防退化"断言

这三条测试是本章 TDD 的灵魂——它们专门防"改写后看起来对、其实退回教材错误"：

| 测试 | 防的是什么 |
|------|-----------|
| `test_rates_not_all_zero`（09） | 防止正确率比对退回文本匹配 → 恒 0% |
| `test_execute_tool_never_raises`（08） | 防止工具错误重新炸穿链路 |
| `test_adapter_pool_returns_same_instance`（01） | 防止适配器退回"每轮 new" |

---

## 九、测试统计

```
纯函数测试（-m "not live"）：279 passed  · 约 46 秒 · 零成本
真实 API 测试（-m live）    ： 26 passed   · 约 40 秒 · 消耗 token
────────────────────────────────────────────────
合计                        ：305 tests
```

**执行顺序**：日常 `-m "not live"` 秒级回归 → 提交前 `-m live` 全量验收。

---

## 十、延伸：如何为其他 12 章补 TDD

本章的 `tests/conftest.py` 是**全书通用**的（`load_chapter_module(N, "XX")` 支持任意章），为其他章补 TDD 只需三步：

1. 在 `conftest.py` 加对应 fixture（如 `ch07_01`）
2. 新建 `tests/test_chNN_XX_主题.py`
3. 按「纯函数全量断言 + live 标记真实调用」的模式写

**优先级建议**：先补纯函数密集的章（如 ch07 上下文处理、ch03 工具链），LLM 调用密集的章放后。
