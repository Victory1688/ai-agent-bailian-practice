# tests/ —— TDD 测试套件

> **项目**：AI Agent 开发：零基础构建复合智能体（阿里百炼平台改写版）
> **测试框架**：pytest 9.1.1
> **运行环境**：`D:/MyCode/.venv/Scripts/python.exe`

---

## 快速开始

```bash
cd D:/AiWorkOut/aiAgentCode

# 日常回归：只跑纯函数测试（约 46 秒，零 API 成本）★ 最常用
D:/MyCode/.venv/Scripts/python.exe -m pytest tests/ -m "not live"

# 单章
D:/MyCode/.venv/Scripts/python.exe -m pytest tests/test_ch13_08_agent_core.py -v

# 真实 API 测试（消耗 token，约 40 秒）
D:/MyCode/.venv/Scripts/python.exe -m pytest tests/ -m "live and not slow"

# 全部（含压测，最慢）
D:/MyCode/.venv/Scripts/python.exe -m pytest tests/
```

**前置条件**：环境变量 `DASHSCOPE_API_KEY` 必须已设置（live 测试依赖）。

---

## 目录结构

```
tests/
├── conftest.py                          # 核心：动态加载器 + 共享 fixture
├── README.md                            # 本文件
├── test_ch13_01_interface.py            # 接口层：Message / Context / Adapter
├── test_ch13_02_intent.py               # 意图识别：extract_json 三步清洗
├── test_ch13_03_safe_eval.py            # 工具链：AST 白名单安全边界
├── test_ch13_04_state_machine.py        # 状态机：迁移白名单穷举
├── test_ch13_05_rag.py                  # RAG：cosine / 分块 / 缓存
├── test_ch13_06_mcp.py                  # MCP：JSON-RPC 协议层
├── test_ch13_07_a2a.py                  # A2A：AgentCard / Message / Task
├── test_ch13_08_agent_core.py           # 主控链条：工具循环 + 主备回退
├── test_ch13_09_accuracy.py             # 正确率框架：三项比对函数
├── test_ch13_10_metrics.py              # 压测：分位数 / 指标 / 串话检测
└── test_ch13_11_judge.py                # 幻觉评估：裁判清洗 / 相似度
```

---

## 为什么需要 conftest.py

本项目源文件命名形如 `01_先定义标准的Agent接口层和数据结构.py`：

1. **以数字开头** → 不是合法 Python 标识符，`import` 直接 SyntaxError
2. **含中文** → 常规 import 机制无法处理
3. **各章大量重名** → 同一 package 会冲突

因此所有测试通过**文件路径动态加载**（`importlib.util`）：

```python
from conftest import load_chapter_module

mod = load_chapter_module(13, "08")     # 加载 chapter13/08_*.py
agent = mod.AgentCore()
```

也可用 fixture（推荐）：

```python
def test_something(ch13_08):
    agent = ch13_08.AgentCore()
```

---

## 测试标记（markers）

| 标记 | 含义 | 何时跑 |
|------|------|-------|
| （无） | 纯函数测试，确定性、零成本 | 每次改动 |
| `live` | 真实调用 DashScope API（消耗 token） | 提交前 |
| `slow` | 耗时长（并发压测、批量评估） | 发布前 |

```bash
pytest -m "not live"          # 只跑纯函数
pytest -m live                # 只跑真实调用
pytest -m "live and not slow" # 真实调用但跳过慢测试
pytest -m "not (live or slow)" # 最快的子集
```

---

## 设计原则

1. **纯函数全量断言**：状态机、AST 白名单、JSON 清洗、指标计算——输入输出确定，穷举边界
2. **真实调用打标记**：本项目采用"全部真实调用"策略（不 mock），用 `live` 标记控制成本
3. **断言契约不断言实现**：如 `assert set(result.keys()) == {"success", "answer", "sources"}`
4. **临时状态必还原**：改 `MODEL_REGISTRY` 后 `finally` 还原，避免污染后续测试
5. **防退化断言**：专门写测试锁定"教材 bug 不被重新引入"（如正确率恒 0%）

---

## 为其他章补 TDD

`conftest.py` 的 `load_chapter_module(N, "XX")` 支持任意章，补测试只需三步：

1. 在 `conftest.py` 加对应 fixture（如 `ch07_01`）
2. 新建 `tests/test_chNN_XX_主题.py`
3. 按「纯函数全量断言 + `@pytest.mark.live` 真实调用」模式写

**优先级**：先补纯函数密集的章（ch03 工具链、ch07 上下文处理），LLM 调用密集的章放后。

---

## 统计

```
纯函数测试（-m "not live"）：279 passed · 约 46 秒
真实 API（-m live）          ： 26 passed · 约 40 秒
─────────────────────────────────────────────
合计                         ：305 tests
```
