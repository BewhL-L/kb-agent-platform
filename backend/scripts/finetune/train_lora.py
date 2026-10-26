"""
本地 LoRA / QLoRA 监督微调（SFT）
================================================
在自己的显卡上微调开源模型（如 Qwen2.5、Llama3），无需把数据传给平台。

- LoRA：只训练少量"低秩适配器"参数，显存占用小、速度快
- QLoRA：在 4bit 量化的基础上做 LoRA，单张 8-16G 显卡即可微调 7B 模型

【环境准备】（这些是可选依赖，不影响主项目运行）
  pip install torch transformers peft accelerate datasets bitsandbytes trl
  # 想要更快更省显存，可改用 unsloth（见文末注释）

【运行】（在 backend 目录下）
  python scripts/finetune/train_lora.py \
      --model Qwen/Qwen2.5-1.5B-Instruct \
      --data sft.jsonl \
      --out ./lora_out --qlora

【数据格式】JSONL，每行：
  {"messages": [{"role":"system","content":"..."},{"role":"user","content":"..."},{"role":"assistant","content":"..."}]}
"""
import argparse


def parse_args():
    p = argparse.ArgumentParser(description="LoRA / QLoRA 微调")
    p.add_argument("--model", required=True, help="基础模型名或本地路径")
    p.add_argument("--data", required=True, help="SFT jsonl 路径")
    p.add_argument("--out", default="./lora_out", help="输出目录")
    p.add_argument("--qlora", action="store_true", help="启用 4bit QLoRA")
    p.add_argument("--epochs", type=float, default=3.0)
    p.add_argument("--lr", type=float, default=2e-4)
    p.add_argument("--batch", type=int, default=2)
    p.add_argument("--grad-accum", type=int, default=8)
    p.add_argument("--max-len", type=int, default=1024)
    p.add_argument("--lora-r", type=int, default=16)
    p.add_argument("--lora-alpha", type=int, default=32)
    return p.parse_args()


def main():
    args = parse_args()

    # 延迟导入，未安装依赖时给出清晰提示
    try:
        import torch
        from datasets import load_dataset
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from trl import SFTConfig, SFTTrainer
    except ImportError as e:
        raise SystemExit(
            "缺少训练依赖，请先安装：\n"
            "  pip install torch transformers peft accelerate datasets "
            "bitsandbytes trl\n"
            f"原始错误：{e}"
        )

    # 1. 数据
    dataset = load_dataset("json", data_files=args.data, split="train")
    print(f"加载训练样本：{len(dataset)} 条")

    # 2. tokenizer
    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # 3. 模型（QLoRA 走 4bit 加载）
    if args.qlora:
        from transformers import BitsAndBytesConfig
        bnb = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )
        model = AutoModelForCausalLM.from_pretrained(
            args.model, quantization_config=bnb, device_map="auto",
            trust_remote_code=True,
        )
        model = prepare_model_for_kbit_training(model)
    else:
        model = AutoModelForCausalLM.from_pretrained(
            args.model, torch_dtype=torch.bfloat16, device_map="auto",
            trust_remote_code=True,
        )

    # 4. LoRA 配置
    lora_cfg = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
    )
    model = get_peft_model(model, lora_cfg)
    model.print_trainable_parameters()

    # 5. 训练
    cfg = SFTConfig(
        output_dir=args.out,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        max_length=args.max_len,
        logging_steps=10,
        save_strategy="epoch",
        bf16=True,
        report_to="none",
    )
    trainer = SFTTrainer(
        model=model, args=cfg, train_dataset=dataset,
        processing_class=tokenizer,
    )
    trainer.train()
    trainer.save_model(args.out)
    tokenizer.save_pretrained(args.out)
    print(f"训练完成，LoRA 适配器已保存到 {args.out}")
    print("可用 merge_lora.py 合并到基础模型，或直接加载适配器推理。")


if __name__ == "__main__":
    main()
