"""
提交 OpenAI 兼容的微调任务（平台需支持 fine-tuning，如 OpenAI；部分国产平台另有微调入口）。
在 scripts/finetune 目录下运行：
  python run_finetune.py --train finetune_train.jsonl --model gpt-4o-mini-2024-07-18
通过环境变量 LLM_API_KEY / LLM_BASE_URL 提供凭证。
"""
import argparse
import os

from openai import OpenAI


def main():
    p = argparse.ArgumentParser(description="提交微调任务")
    p.add_argument("--train", required=True, help="训练 jsonl 路径")
    p.add_argument("--base-url", default=None)
    p.add_argument("--api-key", default=None)
    p.add_argument("--model", default="gpt-4o-mini-2024-07-18")
    p.add_argument("--suffix", default="kb-style")
    args = p.parse_args()

    client = OpenAI(
        api_key=args.api_key or os.getenv("LLM_API_KEY"),
        base_url=args.base_url or os.getenv("LLM_BASE_URL"),
    )

    with open(args.train, "rb") as f:
        uploaded = client.files.create(file=f, purpose="fine-tune")

    job = client.fine_tuning.jobs.create(
        training_file=uploaded.id,
        model=args.model,
        suffix=args.suffix,
    )
    print("已提交微调任务：", job.id)
    print("可用 client.fine_tuning.jobs.retrieve(job_id) 查看进度")


if __name__ == "__main__":
    main()
