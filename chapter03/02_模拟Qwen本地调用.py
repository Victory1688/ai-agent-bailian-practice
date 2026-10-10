# 【例3-2】 模拟Qwen本地调用，替换这个本地模型加载。
# 补充一下，因为我本地资源有限，没有办法安装大模型，还是要调用百炼平台的模型；需要更改模型加载部分。
# qwen3_local_deploy.py

# ========== 原写法：transformers 本地部署（需要本地算力，已被云端调用替换） ==========
# 教学说明：本地部署 = 把模型权重下载到本地显卡上跑推理。Qwen-235B 这种规模的模型
# 需要专业级多卡环境（数百 GB 显存），普通电脑装不下也跑不动——所以改用百炼云端调用。
#
# 第一步：安装依赖
# pip install torch torchvision transformers accelerate
# pip install -U qwen==1.0.3  # 确保qwen库为官方发布版本
#
# from transformers import AutoTokenizer, AutoModelForCausalLM
# import torch
#
# # 第二步：加载Qwen-235B模型（本地加载：从 HuggingFace 下载权重到显卡）
# print(">>> 正在加载Tokenizer与模型...")
# tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen-235B", trust_remote_code=True)
# model = AutoModelForCausalLM.from_pretrained(
#     "Qwen/Qwen-235B",
#     device_map="auto",              # 自动分配 GPU/CPU 设备
#     torch_dtype=torch.float16,      # 半精度加载，省显存
#     trust_remote_code=True
# )
# model.eval()
# print(">>> 模型加载完毕")
#
# # 第四步（原）：执行推理（本地 generate：模型在自己显卡上逐 token 生成）
# def run_inference(prompt: str, max_tokens: int = 128, temperature: float = 0.7):
#     inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
#     with torch.no_grad():
#         outputs = model.generate(
#             **inputs,
#             max_new_tokens=max_tokens,
#             do_sample=True,
#             temperature=temperature
#         )
#     decoded = tokenizer.decode(outputs[0], skip_special_tokens=True)
#     return decoded

# ========== 改写：阿里百炼云端调用（模型在云端，本地只发 HTTP 请求） ==========
# 改写思想：把"加载模型 + 本地推理"整体替换为"远程调用云端模型"，
#           但 build_prompt 的提示词构造、max_tokens/temperature 的参数语义、批量测试循环全部保留
import os
import dashscope

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# 第三步：构造输入（原 build_prompt 逻辑完全保留）
def build_prompt(user_input: str) -> str:
    return f"请解释以下中文成语的含义与出处：{user_input}"

# 第四步（改写）：执行推理（云端推理：dashscope 发请求，模型在百炼服务器上生成）
def run_inference(prompt: str, max_tokens: int = 128, temperature: float = 0.7):
    """
    远程调用百炼大模型推理

    参数:
        prompt: 提示词字符串
        max_tokens: 单次回复最大 token 数（与原 model.generate 的 max_new_tokens 语义一致）
        temperature: 生成温度，越低越确定性（与原 generate 的 temperature 语义一致）
    返回:
        模型回复文本字符串；调用失败时返回错误说明（永不抛异常）
    """
    try:
        response = dashscope.Generation.call(
            model='qwen-plus',           # 云端模型名（替换原本地 Qwen-235B）
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,       # 参数名与本地版一致，语义相同
            temperature=temperature,
            result_format='message'
        )
        return response.output.choices[0].message.content.strip()
    except Exception as e:
        return f"调用失败: {str(e)}"

# 第五步：批量测试（原逻辑完全保留，仅 idioms 列表不变）
idioms = ["画蛇添足", "纸上谈兵", "掩耳盗铃", "望梅止渴", "指鹿为马"]
print(">>> 开始批量推理任务")

for idiom in idioms:
    prompt = build_prompt(idiom)
    result = run_inference(prompt)
    print(f"\n【{idiom}】\n{result.strip()}\n")
