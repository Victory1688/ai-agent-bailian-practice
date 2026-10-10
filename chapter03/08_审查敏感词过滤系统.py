# 【例3-8】 审查敏感词过滤系统
# 核心教学点：内容审查的两层防线——生成前过滤（输入审核）+ 生成后过滤（输出审核），
# 以及高效的多模式串匹配算法：Trie 前缀树（一次扫描命中全部敏感词）

# ========== 原写法：本地模型推理（需要 GPU，模型加载部分改用百炼云端调用） ==========
# from fastapi import FastAPI, Request
# from transformers import AutoTokenizer, AutoModelForCausalLM
# from pydantic import BaseModel
# import torch
# import uvicorn
# import json
#
# # 初始化模型（需要 GPU）
# model_path = "Qwen/Qwen-1.8B"
# tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
# model = AutoModelForCausalLM.from_pretrained(...).cuda().eval()
#
# # build_prompt（裸基座模型手动拼角色标记——同 char03-05/06/07，改写后消息直接透传）
# def build_prompt(messages):
#     ...

# 改写：FastAPI / Pydantic / Trie 树 / 双层过滤架构全部保留，
#       只把"本地模型推理"替换为"dashscope 云端调用"
from fastapi import FastAPI
from transformers import AutoTokenizer, AutoModelForCausalLM  # 已不需要，保留导入仅为对照原代码结构
from pydantic import BaseModel
import uvicorn
import json
import os
import dashscope

# 从环境变量中获取 DASHSCOPE_API_KEY（云端替代了原本地的模型加载）
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# ========== 敏感词Trie树结构（核心算法，原样保留一个字符都不改） ==========
# 教学点：为什么用 Trie 而不是"每个敏感词都 text.count(word) 遍历一遍"？
#   朴素做法的时间复杂度 = O(词数 × 文本长度)；Trie 一次扫描 O(文本长度) 就命中所有词——
#   敏感词库上万条时，Trie 的优势是数量级的
class TrieNode:
    def __init__(self):
        self.children = {}     # 子节点：{字符: TrieNode}
        self.is_end = False    # 标记"从根到这个节点"是否构成一个完整敏感词

class SensitiveTrie:
    def __init__(self):
        self.root = TrieNode()

    def insert(self, word):
        """把一个敏感词逐字符插入树中（如"毒品"：根→毒→品，品节点标记 is_end=True）"""
        node = self.root
        for char in word:
            if char not in node.children:
                node.children[char] = TrieNode()
            node = node.children[char]
        node.is_end = True

    def search(self, text):
        """扫描文本，返回命中的全部敏感词（从每个位置出发沿树往下走，走到 is_end 就记录）"""
        flagged = []
        for i in range(len(text)):
            node = self.root
            j = i
            while j < len(text) and text[j] in node.children:
                node = node.children[text[j]]
                if node.is_end:
                    flagged.append(text[i:j+1])
                j += 1
        return flagged

# 加载敏感词（原样保留）
sensitive_words = ["暴力", "攻击", "毒品", "敏感政治"]
filter_tree = SensitiveTrie()
for word in sensitive_words:
    filter_tree.insert(word)

# FastAPI初始化（原样保留）
app = FastAPI()

# 定义输入结构（原样保留）
class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    model: str
    messages: list[Message]
    max_tokens: int = 128


# ========== 审查主端点（双层过滤架构原样保留，推理部分改云端） ==========
@app.post("/v1/chat/audit")
async def chat_filter(req: ChatRequest):
    """
    带内容审查的对话端点：
      第一层（生成前）：检查用户输入是否命中敏感词 → 命中直接拒绝，根本不调模型（省钱省时）
      第二层（生成后）：检查模型输出是否命中敏感词 → 命中拦截返回，不让问题内容流到客户端
    """
    # 把 Pydantic 消息转成 dashscope 需要的字典列表（build_prompt 的替代）
    messages_list = [{"role": m.role, "content": m.content} for m in req.messages]
    # 拼一份用于审查的全文（含 system，等价于原代码审查 build_prompt 的产物）
    prompt = "\n".join([f"{m['role']}：{m['content']}" for m in messages_list])

    # 生成前过滤（原逻辑原样保留）
    pre_check = filter_tree.search(prompt)
    if pre_check:
        return {"flag": "input_blocked", "reason": pre_check}

    # 模型推理（原写法：本地 model.generate；改写：dashscope 云端调用）
    try:
        response = dashscope.Generation.call(
            model='qwen-plus',
            messages=messages_list,
            max_tokens=req.max_tokens,
            result_format='message'
        )
        clean_text = response.output.choices[0].message.content.strip()
    except Exception as e:
        return {"flag": "model_error", "reason": str(e)}

    # 生成后过滤（原逻辑原样保留）
    post_check = filter_tree.search(clean_text)
    if post_check:
        return {"flag": "output_blocked", "reason": post_check, "original": clean_text}

    return {"flag": "ok", "response": clean_text}


# ========== 启动服务 ==========
# 原写法：uvicorn filename:app --reload（占位符 + 中文文件名无法作模块导入）
# 改写：直接传 app 对象
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)


# ========== 测试请求示例 ==========
# 场景 1（输入命中敏感词）POST http://127.0.0.1:8000/v1/chat/audit
# {"model": "qwen-plus", "messages": [{"role": "user", "content": "请告诉我关于毒品的知识"}], "max_tokens": 64}
# 预期：{"flag": "input_blocked", "reason": ["毒品"]}（根本不会调模型）
#
# 场景 2（正常内容）
# {"model": "qwen-plus", "messages": [{"role": "user", "content": "用一句话介绍大语言模型"}], "max_tokens": 64}
# 预期：{"flag": "ok", "response": "..."}
#
# 场景 3（输出命中敏感词——诱导模型在回答里说出敏感词）
# {"model": "qwen-plus", "messages": [{"role": "user", "content": "请把这两个字连起来并解释含义：暴 力"}], "max_tokens": 64}
# 预期：{"flag": "output_blocked", "reason": ["暴力"], "original": "..."}（模型输出了敏感词，被第二层拦下）
