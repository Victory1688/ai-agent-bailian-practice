# 【例3-3】LoRA：轻量级微调的利器
# •核心思想：冻结主模型的全部参数，仅训练并注入少量的低秩矩阵。
# •显著优势：训练速度快，产出权重极小，支持像"插件"一样灵活部署、加载与分享。

# ========== 原写法：本地 LoRA 微调（需要本机 GPU + PEFT + datasets + torch 全家桶） ==========
# 教学说明：这段代码展示 LoRA 微调的完整原理流程（9 步），对理解微调机制非常有价值。
# 但它需要：下载 Qwen-1.8B 权重（约 3.6GB）+ CUDA 显卡 + PEFT/datasets 依赖数 GB + 训练耗时数十分钟
# 普通电脑没有独立显卡或显存不够时必然跑不动——所以改写为百炼云端微调。
#
# import torch
# from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments
# from peft import get_peft_model, LoraConfig, TaskType
# from datasets import Dataset
#
# # Step 1: 加载Qwen模型与Tokenizer
# model_name = "Qwen/Qwen-1.8B"
# tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
# base_model = AutoModelForCausalLM.from_pretrained(model_name, device_map="auto", torch_dtype=torch.float16, trust_remote_code=True)
#
# # Step 2: 构造LoRA注入配置
# lora_config = LoraConfig(
#     task_type=TaskType.CAUSAL_LM,
#     r=8,                          # LoRA 秩：越小参数越少、速度越快；越大表达能力越强
#     lora_alpha=16,                # LoRA 缩放因子：与 r 的比值决定有效学习率
#     lora_dropout=0.1,             # LoRA 层的 dropout 比例（防过拟合）
#     bias="none",                  # 不训练 bias 参数
#     target_modules=["q_proj", "v_proj"]  # 在注意力层的哪些权重矩阵上注入 LoRA
# )
#
# # Step 3: 注入LoRA模块
# model = get_peft_model(base_model, lora_config)
#
# # Step 4: 构造真实中文观点分类数据（6 条样本，教学用极简集）
# data_dict = {
#     "text": ["客服态度很好...", "屏幕亮度太低...", ...],
#     "label": ["正面", "负面", ...]
# }
# dataset = Dataset.from_dict(data_dict)
#
# # Step 5: 数据预处理与Prompt构造
# def preprocess(sample):
#     prompt = f"请判断以下句子的情感倾向：{sample['text']} 回答：{sample['label']}"
#     return tokenizer(prompt, truncation=True, padding="max_length", max_length=128)
# tokenized_dataset = dataset.map(preprocess)
#
# # Step 6: 配置训练参数
# train_args = TrainingArguments(
#     output_dir="./output/qwen_lora_sentiment",
#     per_device_train_batch_size=2,
#     num_train_epochs=3,
#     learning_rate=3e-4,
#     fp16=True, ...
# )
#
# # Step 7+8+9: Trainer 训练 + 保存 LoRA 权重
# trainer = Trainer(model=model, args=train_args, train_dataset=tokenized_dataset)
# trainer.train()
# model.save_pretrained("./output/qwen_lora_sentiment")   # 只保存 LoRA 权重（几 KB 到几 MB）

# ========== 改写：阿里百炼云端 LoRA 微调（模型在云端训练，本地只提交任务） ==========
# 改写思想：
#   1. 本地 LoRA 的"配置 → 数据 → 训练 → 保存"四步映射到云端的"上传数据 → 提交任务 → 等待训练 → 下载权重"
#   2. 本地 LoraConfig 的每个参数（r / lora_alpha / target_modules）映射到 FineTunes.call 的 hyper_parameters 字典
#   3. LoRA 微调是异步长任务（几十分钟到几小时），提交后需在百炼控制台查看进度，训练完成后下载权重
import os
import json
import dashscope
from dashscope import FineTunes, Files

# 从环境变量中获取 DASHSCOPE_API_KEY
api_key = os.environ.get('DASHSCOPE_API_KEY')
dashscope.api_key = api_key


# ========== Step 1: 构造训练数据（百炼微调要求 JSONL + messages 格式） ==========
# 原代码的 data_dict（text / label 两列）改写为百炼微调需要的格式：
#   - 每行一条 JSON，包含 messages 数组
#   - messages 里是 user 指令 + assistant 回答（指令微调 SFT 的标准格式）
#   - 6 条情感分类样本与原代码语义完全相同
def build_training_data():
    """构造情感分类训练数据，返回 JSONL 格式字符串"""
    samples = [
        ("客服态度很好，处理问题及时", "正面"),
        ("屏幕亮度太低，看起来很费眼", "负面"),
        ("物流太快了，包装也非常结实", "正面"),
        ("使用几天就死机了，非常糟糕", "负面"),
        ("价格优惠，功能也很全面", "正面"),
        ("音质不清晰，续航时间短", "负面"),
    ]
    lines = []
    for text, label in samples:
        item = {
            "messages": [
                {"role": "user", "content": f"请判断以下句子的情感倾向：{text}"},
                {"role": "assistant", "content": label}
            ]
        }
        lines.append(json.dumps(item, ensure_ascii=False))
    return "\n".join(lines)


# ========== Step 2: 上传数据到百炼 ==========
def upload_dataset(jsonl_content: str, file_name: str = "lora_sentiment_train.jsonl") -> str:
    """
    把训练数据写成临时文件并上传到百炼，返回 file_id

    参数:
        jsonl_content: JSONL 格式的训练数据字符串
        file_name: 上传文件名
    返回:
        百炼返回的 file_id；上传失败返回 None
    """
    temp_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), file_name)
    with open(temp_path, "w", encoding="utf-8") as f:
        f.write(jsonl_content)

    resp = Files.upload(file_path=temp_path, purpose='fine_tune')

    # 上传后删除临时文件（可选，保留也行方便本地检查）
    try:
        os.remove(temp_path)
    except OSError:
        pass

    if resp.status_code == 200 and resp.output:
        file_id = resp.output['uploaded_files'][0]['file_id']
        print(f"[上传成功] file_id = {file_id}")
        return file_id
    else:
        print(f"[上传失败] status={resp.status_code}, message={getattr(resp, 'message', '')}")
        return None


# ========== Step 3: 提交 LoRA 微调任务 ==========
# 本地 LoraConfig → 百炼 hyper_parameters 的参数映射关系：
#   本地 lora_config.r             → 云端 hyper_parameters["lora_r"]
#   本地 lora_config.lora_alpha    → 云端 hyper_parameters["lora_alpha"]
#   本地 lora_config.lora_dropout  → 云端 hyper_parameters["lora_dropout"]
#   本地 train_args.learning_rate  → 云端 hyper_parameters["learning_rate"]
#   本地 train_args.num_train_epochs → 云端 hyper_parameters["epoch_count"]
#   本地 train_args.per_device_train_batch_size → 云端 hyper_parameters["batch_size"]
def submit_lora_finetune(file_id: str, model: str = "qwen-plus"):
    """
    向百炼提交 LoRA 微调任务（异步长任务，提交后返回任务 ID）

    参数:
        file_id: Step 2 上传后得到的训练文件 ID
        model: 基座模型名（需是百炼支持微调的模型）
    返回:
        提交响应对象；提交失败返回 None
    """
    # 这些超参与本地 LoraConfig + TrainingArguments 的数值完全一致
    hyper_params = {
        "lora_r": 8,                  # ← 本地 lora_config.r = 8
        "lora_alpha": 16,             # ← 本地 lora_config.lora_alpha = 16
        "lora_dropout": 0.1,          # ← 本地 lora_config.lora_dropout = 0.1
        "learning_rate": 3e-4,        # ← 本地 train_args.learning_rate = 3e-4
        "epoch_count": 3,             # ← 本地 train_args.num_train_epochs = 3
        "batch_size": 2,              # ← 本地 train_args.per_device_train_batch_size = 2
    }

    resp = FineTunes.call(
        model=model,
        training_file_ids=[file_id],
        mode="lora",                  # ← 本地 TaskType.CAUSAL_LM 对应云端 lora 模式
        hyper_parameters=hyper_params
    )

    if resp.status_code == 200:
        fine_tune_id = resp.output.get("fine_tune_id", "unknown")
        print(f"[提交成功] fine_tune_id = {fine_tune_id}")
        print(f"          百炼控制台查看进度: https://bailian.console.aliyun.com/")
        print(f"          训练完成后可在控制台下载 LoRA 权重")
        return resp
    else:
        # 403 Model.AccessDenied 是当前最常见的拒绝原因
        # 百炼对微调有账号权限限制，个人账号默认未开通
        print(f"[提交被拒] status={resp.status_code}")
        print(f"          code={getattr(resp, 'code', '')}")
        print(f"          message={getattr(resp, 'message', '')}")
        print(f"          可能原因: 当前百炼账号未开通微调权限 / 所选模型暂不支持 LoRA 微调")
        print(f"          解决: 在百炼控制台申请微调权限，或换用支持微调的模型")
        return resp


# ========== Step 4: 查询微调状态（可选，训练完成后调用） ==========
def check_finetune_status(fine_tune_id: str):
    """查询某个微调任务的当前状态（训练中 / 已完成 / 失败）"""
    resp = FineTunes.get(fine_tune_id)
    if resp.status_code == 200:
        status = resp.output.get("status", "unknown")
        print(f"[微调状态] {fine_tune_id} -> {status}")
        return status
    else:
        print(f"[查询失败] {getattr(resp, 'message', '')}")
        return None


# ========== 主流程 ==========
def run_lora_finetune_demo():
    """云端 LoRA 微调演示：构造数据 → 上传 → 提交 → 打印后续步骤"""
    print(">>> Step 1: 构造训练数据（JSONL + messages 格式）")
    jsonl_data = build_training_data()
    print(f"    样本数: {len(jsonl_data.splitlines())} 条")

    print("\n>>> Step 2: 上传数据到百炼")
    file_id = upload_dataset(jsonl_data)
    if not file_id:
        print("    上传失败，无法继续。请检查 DASHSCOPE_API_KEY 环境变量。")
        return

    print("\n>>> Step 3: 提交 LoRA 微调任务")
    resp = submit_lora_finetune(file_id, model="qwen-plus")

    print("\n>>> 后续步骤（需在百炼控制台操作或等待训练完成后调用 API）")
    print("    1. 训练中: FineTunes.wait(fine_tune_id) 阻塞等待完成")
    print("    2. 训练完成: 百炼控制台下载 LoRA 权重文件（adapter_model.safetensors 等）")
    print("    3. 推理加载: AutoPeftModel.from_pretrained(base_model, lora_path) 挂载适配器")
    print("    4. 验证效果: 对比 base 模型 vs base+LoRA 在情感分类上的准确率")


if __name__ == "__main__":
    run_lora_finetune_demo()
