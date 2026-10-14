# chapter01 规范（Spec）—— 大模型与智能体技术基础

> **文件性质**：SDD（Specification-Driven Development）规范文档
> **对应源码**：`chapter01/` 下 6 个 `.py` 文件（共 260 行）
> **编写依据**：逐文件通读源码后提炼，契约字段均来自代码事实，未臆造
> **状态**：v1.0 ｜ 2026-10-14

---

# 上篇：意图与学习路径

## 1. 本章意图（Why）

第 1 章是全书打底章。它要回答一个问题：**LLM 为什么可以作为 Agent 的大脑，以及如何用最朴素的 API 调用证明这件事**。

本章不给任何框架，只用最原始的 `dashscope.Generation.call` 打通链路。目的是让学习者在接触 LangChain / LangGraph 之前，先看清"提示词进、文本出"这条最小闭环——后面所有框架都是在这条闭环上做工程化。

> 📌 与全书的关系：本章对应五模块架构的**接口模块**（模型 API 调用）与**认知模块**的雏形（提示词驱动）。第 2 章才开始拆解完整的四大模块运行机制。

## 2. 学习路径（按源码顺序）

| 顺序 | 文件 | 学什么 | 掌握后应该能回答 |
|---|---|---|---|
| 1 | `01_文本摘要_textSummarization.py` | 最小调用闭环：提示词模板 + `messages` 结构 + 响应取值 | 一次 API 调用的完整链路有哪几段？ |
| 2 | `02_提示词驱动的Agent.py` | LangChain 1.x 的 LCEL 管道写法 vs 已废弃的 `LLMChain` | `PromptTemplate \| LLM \| Parser` 这条管道在做什么？ |
| 3 | `03_生成SQL语句的任务建模.py` | 任务建模：把"用户指令"翻译成"结构化产出要求" | 为什么要在提示词里规定输出格式？ |
| 4 | `04_文本抽取任务建模.py` | 信息抽取：从非结构化文本中抽出指定字段 | 抽取任务的提示词与生成任务有何差别？ |
| 5 | `05_接口模式设计.py` | 多消息角色（system + user）+ 生成参数控制 | `system` 角色的作用是什么？`temperature` 影响什么？ |
| 6 | `06_通过上下文的行为引导LLM.py` | 上下文引导：用"已知上下文"驱动分阶段任务 | 如何让模型理解"当前处于第几步"？ |

**建议学习方式**：每读完一个文件，把提示词改一句再跑一次，观察输出变化。本章的价值在"手感"，不在记忆 API。

## 3. 本章的工程主线：一次彻底的代码改写

本章所有文件都是**教材原版代码的改写版**，原代码以注释形式完整保留在文件头部。改写遵循统一的四条规则（这是本章最有价值的工程知识点）：

| # | 改写规则 | 原版问题 | 改写方案 |
|---|---|---|---|
| 1 | **模型接入** | `OpenAI()` 未配 `api_key` / `base_url`，直接调用必失败 | 统一走阿里云百炼 `dashscope` 原生协议，`model='qwen-plus'` |
| 2 | **响应取值** | `response.choices[0].message.content`（OpenAI 结构） | `response.output.choices[0].message.content`（dashscope 结构） |
| 3 | **必需的格式参数** | 无 | 必须传 `result_format='message'`，否则取不到 `.message` |
| 4 | **废弃 API 替换** | `langchain.llms` / `LLMChain` / `langchain.prompts` 在 1.x 已移除或迁移 | 换 `langchain_core.prompts` + LCEL 管道 `template \| llm \| StrOutputParser()` |

> ⚠️ **最值得记住的一条**：`result_format='message'`。dashscope 默认返回 text 格式，此时 `response.output` 是字符串而非对象，写 `.choices[0]` 会直接报错。这是本章 5 个文件全部依赖的隐式契约。

## 4. 学习检查清单

- [ ] 能独立跑通 `01_文本摘要_textSummarization.py` 并拿到中文摘要
- [ ] 能说清 `result_format='message'` 不传会发生什么
- [ ] 能解释为什么 `02` 要先 `from langchain_core.prompts import PromptTemplate`
- [ ] 能指出 `04` 提示词里的 `{{` `}}` 是干什么用的
- [ ] 能自己改一版提示词，让 `03` 输出的 SQL 带上 `WHERE` 条件

---

# 下篇：契约与验收

## 5. 统一技术约束（Global Constraints）

本章 6 个文件共享同一套硬约束，任一文件偏离即为违约：

```
C-01  模型接入协议：dashscope 原生协议（非 OpenAI 兼容模式）
C-02  模型名：qwen-plus
C-03  密钥来源：环境变量 DASHSCOPE_API_KEY，禁止硬编码
C-04  必需参数：result_format='message'
C-05  响应路径：response.output.choices[0].message.content
C-06  运行前置：DASHSCOPE_API_KEY 已设置，dashscope 包已安装
```

统一调用骨架（5 个文件的实际形态）：

```python
import os
import dashscope

dashscope.api_key = os.environ.get('DASHSCOPE_API_KEY')

def get_response(messages):
    response = dashscope.Generation.call(
        model='qwen-plus',
        messages=messages,
        result_format='message'
    )
    return response

response = get_response([{"role": "user", "content": prompt}])
print(response.output.choices[0].message.content)
```

## 6. 逐文件契约

### F-01 `01_文本摘要_textSummarization.py`

| 项 | 契约 |
|---|---|
| **意图** | 提示词设计示例：中文技术文档摘要 |
| **输入** | `document`：待摘要文本（模块内硬编码字符串） |
| **处理** | `prompt.format(document)` 拼装 → 单轮 user 消息 → 调用模型 |
| **输出** | `stdout` 打印摘要正文（中文） |
| **验收标准** | ① 输出为通顺中文；② 保留技术要点；③ **控制在 100 字以内**（提示词明确要求，实测 93 字符合） |
| **提示词要点** | 角色设定（中文技术文档撰写专家）+ 任务（简洁准确摘要）+ 约束（通顺 / 保留要点 / ≤100 字） |
| **已知风险** | 🔴 无 `status_code` 校验：失败时 `response.output` 为 `None`，第 38 行抛 `AttributeError`，真实错误码被掩盖 |

### F-02 `02_提示词驱动的Agent.py`

| 项 | 契约 |
|---|---|
| **意图** | 展示 LangChain 1.x 中"提示词驱动"的正确写法（对比已废弃的 `LLMChain`） |
| **输入** | `{"question": "什么是实体消歧？"}`（invoke 字典） |
| **处理** | `PromptTemplate` → `ChatTongyi` → `StrOutputParser`，LCEL 管道 `\|` 串联 |
| **输出** | `stdout` 打印字符串结果 |
| **验收标准** | ① 管道 `template \| llm \| StrOutputParser()` 无异常执行；② 输出为知识图谱相关回答；③ 回答含判断依据 |
| **依赖要点** | `PromptTemplate` 来自 `langchain_core.prompts`（非 `langchain.prompts`）；`ChatTongyi` 来自 `langchain_community.chat_models.tongyi` |
| **⚠️ 技术债** | 使用 `ChatTongyi`（社区包 `langchain-community` 官方已停止维护）。本章作为教学可保留；生产建议换 `ChatOpenAI` + 兼容端点 |

### F-03 `03_生成SQL语句的任务建模.py`

| 项 | 契约 |
|---|---|
| **意图** | 任务建模示例：自然语言指令 → SQL 语句 |
| **输入** | `user_instruction = "我想查询所有注册时间在2023年之后的用户姓名和邮箱"` |
| **处理** | f-string 拼装提示词 → 单轮 user 消息 → 调用模型 |
| **输出** | 模型返回 JSON 文本，字段含 `sql` 与 `explanation` |
| **提示词约束（4 条）** | ① 表名 `users`；② 字段 `name` / `email`；③ 标准 SQL 语法；④ 输出格式 JSON，含 `sql` 和 `explanation` |
| **验收标准** | ① 输出可解析出 `sql` 字段；② SQL 含 `WHERE` 时间过滤条件；③ 表名字段名符合约束 |
| **已知风险** | 🟠 未要求模型"仅输出 JSON"，实际输出可能带 markdown 围栏，直接 `json.loads` 会失败（第 13 章 13-02 有专门的 `extract_json` 清洗方案可回看） |

### F-04 `04_文本抽取任务建模.py`

| 项 | 契约 |
|---|---|
| **意图** | 信息抽取示例：从文本抽取企业名与地址 |
| **输入** | `instruction`：含"浙江橙龙科技有限公司位于杭州市余杭区五常街道五常大道100号"的文本 |
| **处理** | f-string 拼装（含输出格式示例）→ 单轮 user 消息 → 调用模型 |
| **输出** | 模型返回 JSON 文本：`{"company": "...", "address": "..."}` |
| **验收标准** | ① 抽出 `company` = 浙江橙龙科技有限公司；② 抽出 `address` = 杭州市余杭区五常街道五常大道100号；③ 输出为合法 JSON 结构 |
| **实现要点** | 提示词中的 `{{` `}}` 是 **f-string 转义**，渲染后为单个 `{` `}`——这是"给模型看的 JSON 示例"的标准写法，若写成单层花括号会触发 f-string 解析错误 |
| **已知风险** | 🟠 同 F-03，无输出清洗 |

### F-05 `05_接口模式设计.py`

| 项 | 契约 |
|---|---|
| **意图** | 接口模式设计示例：多角色消息序列 + 生成参数控制 |
| **输入** | `messages`：`[{"role": "system", ...}, {"role": "user", ...}]` 两元素列表 |
| **处理** | 直接传入消息序列 → 调用模型（带生成参数） |
| **输出** | `stdout` 打印表格形式的债券/股票对比回答 |
| **生成参数（本条独有）** | `temperature=0.3`（低随机性）、`max_tokens=512`（输出上限） |
| **验收标准** | ① `system` 角色生效（回答符合"金融知识专家"设定）；② 输出含表格结构；③ 未超 `max_tokens` 被截断 |
| **教学要点** | 这是本章唯一演示**参数传递**的文件。`temperature` / `max_tokens` 与原 OpenAI 写法的语义一致，dashscope 同样支持 |

### F-06 `06_通过上下文的行为引导LLM.py`

| 项 | 契约 |
|---|---|
| **意图** | 上下文引导示例：用"已知上下文"驱动分阶段任务 |
| **输入** | `prompt`：含任务目标 + 已知上下文（身份验证已完成 / 已完成步骤"查询账单日=每月15日" / 当前阶段"继续查询还款日"） |
| **处理** | 单轮 user 消息（无 system 角色）→ 调用模型 |
| **输出** | 模型给出"用户当前还需了解的信息 + 下一步行为指导" |
| **验收标准** | ① 输出识别出当前阶段是"查询还款日"；② 输出给出下一步行为建议；③ 不重复询问已完成的账单日 |
| **教学要点** | 这是"认知模块"最早的雏形——把**任务状态显式写进提示词**，让无状态模型表现出"知道自己在哪一步"的行为。第 5 章 LangGraph 的状态机就是这条思路的工程化 |
| **已知风险** | 🟡 上下文以中文自然语言描述（非结构化），模型需自行解析；生产应改结构化 JSON 上下文段（第 7 章主题） |

## 7. 全章验收清单

| # | 验收项 | 判定方式 |
|---|---|---|
| V-01 | 6 个文件均可独立执行（`python <file>`） | 无 ImportError / NameError |
| V-02 | 均使用 `qwen-plus` + `result_format='message'` | 静态检查源码 |
| V-03 | 密钥均来自 `os.environ.get('DASHSCOPE_API_KEY')` | 静态检查，无硬编码 |
| V-04 | 均能从 `response.output.choices[0].message.content` 取到非空文本 | 实跑观察 |
| V-05 | `02` 的 LCEL 管道可执行 | 实跑观察 |
| V-06 | `03` 输出含 SQL 且带时间过滤 | 实跑观察 |

## 8. 已知缺口（Gap Analysis）

本章作为"最小闭环"章节，**刻意未包含**以下能力，它们是后续章节的主题，不应在本章补齐：

| 缺口 | 属哪章 |
|---|---|
| 错误处理 / `status_code` 校验 / 超时重试 | 第 13 章（13-01 起全面加固） |
| JSON 输出的安全清洗（替代裸 `json.loads`） | 第 13 章 13-02 `extract_json` |
| 工具调用（function calling） | 第 2 章起 |
| 多轮对话记忆 | 第 6 / 8 章 |
| 自动化测试（self-test） | 第 13 章 |

> 📌 **写作纪律**：本章 spec 不为"补全"这些问题而修改代码。第 1 章的教学目标是"看清最小闭环"，加入工程加固反而会干扰认知。

---

**版本记录**

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-10-14 | 首版：6 文件全覆盖，上篇意图/学习路径 + 下篇契约/验收 |
