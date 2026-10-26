"""
DPO 偏好对齐训练（Direct Preference Optimization）
================================================
SFT 教会模型"怎么答"，DPO 进一步教会模型"更偏好哪种答法"。
用用户点赞/点踩的真实反馈，让模型输出更符合人类偏好。

【环境准备】
  pip install torch transformers peft accelerate datasets trl

【运行】（在 backend 目录下）
  python scripts/finetune/train_dpo.py \
      --model Qwen/Qwen2.5-1.5B-Instruct \
      --data dpo.jsonl --out ./dpo_out

  若在 SFT 得到的 LoRA 上继续训练，--model 可传基础模型并用 --adapter
  加载 SFT 适配器。

【数据格式】JSONL，每行：
  {"prompt": [{"role":"user","content":"..."}],
   "chosen": [{"role":"assistant","content":"好答案"}],
   "rejected": [{"role":"assistant","content":"差答案"}]}
"""
import argparse


def parse_args():
    p = argparse.ArgumentParser(description="DPO 偏好训练")
    p.add_argument("--model", required=True, help="基础模型名或路径")
    p.add_argument("--data", required=True, help="DPO jsonl 路径")
    p.add_argument("--out", default="./dpo_out")
    p.add_argument("--adapter", default=None, help="已训练的 SFT LoRA 路径")
    p.add_argument("--epochs", type=float, default=1.0)
    p.add_argument("--lr", type=float, default=5e-6)
    p.add_argument("--beta", type=float, default=0.1, help="DPO 温度系数")
    p.add_argument("--batch", type=int, default=2)
    p.add_argument("--grad-accum", type=int, default=8)
    p.add_argument("--max-len", type=int, default=1024)
    return p.parse_args()


def main():
    args = parse_args()

    try:
        import torch
        from datasets import load_dataset
        from peft import LoraConfig, PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from trl import DPOConfig, DPOTrainer
    except ImportError as e:
        raise SystemExit(
            "缺少训练依赖，请先安装：\n"
            "  pip install torch transformers peft accelerate datasets trl\n"
            f"原始错误：{e}"
        )

    dataset = load_dataset("json", data_files=args.data, split="train")
    print(f"加载偏好样本：{len(dataset)} 条")

    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        args.model, torch_dtype=torch.bfloat16, device_map="auto",
        trust_remote_code=True,
    )
    # DPO 需要参考模型；用 LoRA 时参考模型即基础模型
    if args.adapter:
        model = PeftModel.from_pretrained(model, args.adapter, is_trainable=True)

    ref_model = None
    if not args.adapter:
        ref_model = AutoModelForCausalLM.from_pretrained(
            args.model, torch_dtype=torch.bfloat16, device_map="auto",
            trust_remote_code=True,
        )

    cfg = DPOConfig(
        output_dir=args.out,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        beta=args.beta,
        max_length=args.max_len,
        max_prompt_length=args.max_len // 2,
        logging_steps=10,
        save_strategy="epoch",
        bf16=True,
        report_to="none",
    )
    trainer = DPOTrainer(
        model=model, ref_model=ref_model, args=cfg,
        train_dataset=dataset, processing_class=tokenizer,
    )
    trainer.train()
    trainer.save_model(args.out)
    tokenizer.save_pretrained(args.out)
    print(f"DPO 训练完成，模型已保存到 {args.out}")


if __name__ == "__main__":
    main()
