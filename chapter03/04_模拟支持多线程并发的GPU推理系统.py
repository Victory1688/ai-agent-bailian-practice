# 【例3-4】 GPU资源调度与推理优化
# 模型并行：拆分大模型至多卡，突破单卡显存限制。多实例部署：多张GPU加载副本，提升吞吐能力。
# 异步与显存管理：多线程异步IO管理请求，动态释放资源。

# ========== 原写法：本地多 GPU 多实例推理（需要本机至少一块 CUDA 显卡） ==========
# 教学说明：这段代码展示"多实例部署 + 多线程调度"的完整架构，是理解推理服务并发的经典教材。
# 但它需要：本机有 CUDA 显卡（torch.cuda.device_count() >= 1）+ 下载 Qwen-1.8B 权重 + GPU 显存，
# 没有独立显卡的电脑在 Step 1 的 assert 就会中断——所以改写为云端并发调用。
#
# import torch
# import time
# import threading
# from transformers import AutoTokenizer, AutoModelForCausalLM, TextStreamer
#
# # Step 1: 自动检测GPU设备（本篇的硬件门槛所在）
# device_ids = [i for i in range(torch.cuda.device_count())]
# assert len(device_ids) >= 1, "需要至少一个可用GPU"
#
# # Step 2: 为每张GPU加载一个模型副本（"多实例部署"：N 张卡 = N 个独立推理实例）
# models = []
# tokenizers = []
# for device_id in device_ids:
#     print(f"正在初始化 GPU-{device_id} 上的模型副本...")
#     tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen-1.8B", trust_remote_code=True)
#     model = AutoModelForCausalLM.from_pretrained(
#         "Qwen/Qwen-1.8B",
#         trust_remote_code=True,
#         torch_dtype=torch.float16
#     ).to(f"cuda:{device_id}").eval()
#     models.append(model)
#     tokenizers.append(tokenizer)
# print("所有模型副本加载完成。")
#
# # Step 3: 定义异步推理函数（按 device_index 路由到对应 GPU 副本）
# def run_inference(device_index, input_text):
#     tokenizer = tokenizers[device_index]
#     model = models[device_index]
#     input_ids = tokenizer(input_text, return_tensors="pt").input_ids.to(f"cuda:{device_index}")
#     with torch.no_grad():
#         start = time.time()
#         output = model.generate(input_ids=input_ids, max_new_tokens=128,
#                                 do_sample=True, temperature=0.7)
#         end = time.time()
#     decoded = tokenizer.decode(output[0], skip_special_tokens=True)
#     print(f"[GPU-{device_index}] 推理耗时：{round(end - start, 2)}秒")
#     print(f"[GPU-{device_index}] 输出结果：{decoded}\n")
#     # 清理显存（GPU 推理的内存管理动作）
#     del input_ids, output
#     torch.cuda.empty_cache()
#
# # Step 4: 构造并发请求样本（原 prompts 列表，改写版原样保留）
# prompts = [
#     "请简述Transformer模型的核心机制。",
#     "什么是多模态大模型？其应用场景有哪些？",
#     "如何通过LoRA对大语言模型进行微调？",
#     "当前AI Agent的主要技术难点有哪些？"
# ]
#
# # Step 5: 多线程启动推理任务（idx % len(device_ids) 把请求轮询分发到各 GPU 副本）
# threads = []
# for idx, prompt in enumerate(prompts):
#     thread = threading.Thread(target=run_inference, args=(idx % len(device_ids), prompt))
#     threads.append(thread)
#     thread.start()
# for thread in threads:
#     thread.join()

# ========== 改写：云端并发推理（多线程架构原样保留，GPU 副本换成云端调用） ==========
# 改写思想（与原代码逐 Step 对应）：
#   Step 1 检测 GPU 数量    → 改写为定义"云端并发槽位"（模拟 N 个实例，无 GPU 限制）
#   Step 2 每卡加载模型副本 → 云端模型由平台托管，本地无需加载（这正是云端的优势）
#   Step 3 推理函数         → 函数签名 run_inference(instance_index, input_text) 不变，
#                             内部 model.generate 换成 dashscope.Generation.call
#   Step 4 请求样本         → 原样保留
#   Step 5 多线程分发+join  → 原样保留（本篇的灵魂：并发调度架构）
# 额外增加：串行版对照实验——用真实耗时证明"并发提升吞吐"，没有 GPU 也能看到效果。
import time
import threading
import os
import dashscope

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key

# Step 1（改写）：定义云端并发槽位
# 原写法检测有几张 GPU 就开几个实例；云端调用不受本地 GPU 限制，
# 这里用 2 个"实例槽位"模拟原代码的多实例部署（槽位只是请求的路由标签）
INSTANCE_IDS = [0, 1]

# Step 2（改写）：云端无需加载模型副本
# 原写法要为每张 GPU 下载权重并常驻显存；云端的多实例由百炼平台弹性管理——
# 本地代码里"加载模型"这一步整个消失了，这是两种部署形态最直观的差异
print("云端实例由百炼平台托管，本地无需加载模型副本。")

# Step 3（改写）：定义推理函数（函数签名与原版完全一致）
def run_inference(instance_index, input_text):
    """
    单实例推理：把请求路由到指定槽位，发起云端调用并打印耗时与结果

    参数:
        instance_index: 实例槽位编号（对应原版的 GPU 编号）
        input_text: 用户请求文本
    """
    start = time.time()
    try:
        response = dashscope.Generation.call(
            model='qwen-plus',
            messages=[{"role": "user", "content": input_text}],
            max_tokens=128,          # 与原版 max_new_tokens=128 语义一致
            temperature=0.7,         # 与原版 do_sample=True + temperature=0.7 语义一致
            result_format='message'
        )
        decoded = response.output.choices[0].message.content.strip()
        end = time.time()
        print(f"[实例-{instance_index}] 推理耗时：{round(end - start, 2)}秒")
        print(f"[实例-{instance_index}] 输出结果：{decoded[:60]}...\n")
        # 原写法这里的 del input_ids, output + torch.cuda.empty_cache()
        # 是 GPU 显存清理动作；云端调用无本地显存占用，无需清理
    except Exception as e:
        print(f"[实例-{instance_index}] 调用失败：{str(e)}\n")

# Step 4: 构造并发请求样本（原 prompts 原样保留）
prompts = [
    "请简述Transformer模型的核心机制。",
    "什么是多模态大模型？其应用场景有哪些？",
    "如何通过LoRA对大语言模型进行微调？",
    "当前AI Agent的主要技术难点有哪些？"
]


# ========== 对照实验 A：串行执行（一个接一个，作为"单实例"的基准线） ==========
def run_serial():
    print("=" * 60)
    print("实验 A：串行执行（单实例，一个请求完成后才发下一个）")
    print("=" * 60)
    start = time.time()
    for idx, prompt in enumerate(prompts):
        run_inference(0, prompt)          # 全部路由到同一个实例
    total = time.time() - start
    print(f">>> 串行总耗时：{round(total, 2)}秒\n")
    return total


# ========== 对照实验 B：多线程并发（原 Step 5 架构原样保留） ==========
def run_concurrent():
    print("=" * 60)
    print("实验 B：多线程并发（多实例轮询分发，4 个请求同时发出）")
    print("=" * 60)
    start = time.time()

    # Step 5: 多线程启动推理任务（与原代码逐行对应）
    threads = []
    for idx, prompt in enumerate(prompts):
        # idx % len(INSTANCE_IDS) 轮询分发——原代码用 device_ids，这里用云端槽位
        thread = threading.Thread(target=run_inference, args=(idx % len(INSTANCE_IDS), prompt))
        threads.append(thread)
        thread.start()

    # 等待所有线程执行完毕（join 是并发调度的收尾动作，原样保留）
    for thread in threads:
        thread.join()

    total = time.time() - start
    print(f">>> 并发总耗时：{round(total, 2)}秒\n")
    return total


if __name__ == "__main__":
    serial_time = run_serial()
    concurrent_time = run_concurrent()
    print("=" * 60)
    print(f"吞吐对比：串行 {round(serial_time, 2)}秒 vs 并发 {round(concurrent_time, 2)}秒")
    if concurrent_time > 0:
        print(f"并发加速比：约 {round(serial_time / concurrent_time, 1)} 倍")
    print("=" * 60)
