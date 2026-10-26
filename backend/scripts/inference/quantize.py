"""
模型量化脚本（AWQ / GPTQ）
================================================
量化把模型权重从 16bit 压缩到 4bit，显著降低显存占用、提升速度，
精度损失通常很小。

- AWQ：激活感知量化，通用、效果好（推荐）
- GPTQ：基于二阶信息的逐层量化，生态成熟

【环境准备】
  # AWQ
  pip install autoawq
  # 或 GPTQ
  pip install optimum auto-gptq

【运行】（在 backend 目录下）
  python scripts/inference/quantize.py \
      --model Qwen/Qwen2.5-1.5B-Instruct \
      --method awq --out ./quantized_awq

量化后的模型可直接被 vLLM 加载：
  vllm serve ./quantized_awq --quantization awq
"""
import argparse


def make_calib_texts():
    """校准数据：用领域文本让量化"看到"真实分布，减小精度损失。
    可替换为你知识库中的典型句子。"""
    return [
        "这是一份企业知识库文档，包含产品说明、售后政策和操作流程。",
        "用户可以通过检索增强生成，从知识库中快速找到所需答案。",
        "退款在商家确认后的 3-7 个工作日内原路退回支付账户。",
    ]


def main():
    args = parse_args()

    if args.method == "awq":
        quantize_awq(args)
    elif args.method == "gptq":
        quantize_gptq(args)


def quantize_awq(args):
    try:
        from awq import AutoAWQForCausalLM
        from transformers import AutoTokenizer
    except ImportError:
        raise SystemExit("缺少依赖：pip install autoawq")

    model = AutoAWQForCausalLM.from_pretrained(
        args.model, trust_remote_code=True
    )
    tokenizer = AutoTokenizer.from_pretrained(
        args.model, trust_remote_code=True
    )
    quant_cfg = {"zero_point": True, "q_group_size": 128,
                 "w_bit": 4, "version": "GEMM"}
    model.quantize(
        tokenizer, quant_config=quant_cfg,
        calib_data=make_calib_texts(),
    )
    model.save_quantized(args.out)
    tokenizer.save_pretrained(args.out)
    print(f"AWQ 量化模型已保存到 {args.out}")


def quantize_gptq(args):
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, GPTQConfig
    except ImportError:
        raise SystemExit("缺少依赖：pip install optimum auto-gptq")

    tokenizer = AutoTokenizer.from_pretrained(
        args.model, trust_remote_code=True
    )
    cfg = GPTQConfig(
        bits=4, dataset=make_calib_texts(), tokenizer=tokenizer,
    )
    model = AutoModelForCausalLM.from_pretrained(
        args.model, quantization_config=cfg,
        torch_dtype=torch.bfloat16, trust_remote_code=True,
    )
    model.save_pretrained(args.out)
    tokenizer.save_pretrained(args.out)
    print(f"GPTQ 量化模型已保存到 {args.out}")


def parse_args():
    p = argparse.ArgumentParser(description="模型量化")
    p.add_argument("--model", required=True)
    p.add_argument("--method", choices=["awq", "gptq"], default="awq")
    p.add_argument("--out", default="./quantized_model")
    return p.parse_args()


if __name__ == "__main__":
    main()
