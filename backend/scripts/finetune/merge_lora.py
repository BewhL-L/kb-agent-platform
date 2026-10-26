"""
合并 LoRA 适配器到基础模型并导出完整模型
================================================
微调得到的是很小的"适配器"，合并后得到可独立部署的完整模型
（也可被 vLLM 直接加载）。

【运行】（在 backend 目录下）
  python scripts/finetune/merge_lora.py \
      --base Qwen/Qwen2.5-1.5B-Instruct \
      --adapter ./lora_out --merged ./merged_model
"""
import argparse


def main():
    p = argparse.ArgumentParser(description="合并 LoRA 适配器")
    p.add_argument("--base", required=True, help="基础模型名或路径")
    p.add_argument("--adapter", required=True, help="LoRA 适配器路径")
    p.add_argument("--merged", required=True, help="合并后输出路径")
    args = p.parse_args()

    try:
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError as e:
        raise SystemExit(
            "缺少依赖：pip install torch transformers peft\n"
            f"原始错误：{e}"
        )

    model = AutoModelForCausalLM.from_pretrained(
        args.base, torch_dtype=torch.bfloat16, device_map="cpu",
        trust_remote_code=True,
    )
    model = PeftModel.from_pretrained(model, args.adapter)
    model = model.merge_and_unload()

    model.save_pretrained(args.merged, safe_serialization=True)
    tokenizer = AutoTokenizer.from_pretrained(args.base, trust_remote_code=True)
    tokenizer.save_pretrained(args.merged)
    print(f"合并完成，完整模型已导出到 {args.merged}")


if __name__ == "__main__":
    main()
