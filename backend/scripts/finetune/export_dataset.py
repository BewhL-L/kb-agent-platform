"""
从运行中的数据库导出 SFT / DPO 微调数据集（JSONL）。
在 backend 目录下运行：
  python scripts/finetune/export_dataset.py --type sft --kb-id 1 --out sft.jsonl
  python scripts/finetune/export_dataset.py --type dpo --kb-id 1 --out dpo.jsonl

数据来源：
  sft：golden_qa + 历史高质量问答
  dpo：用户点赞/点踩反馈
"""
import argparse
import os
import sys

# 允许从 backend 根目录导入 app
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.database import SessionLocal
from app.services.finetune_data import finetune_data_service


def main():
    p = argparse.ArgumentParser(description="导出微调数据集")
    p.add_argument("--type", choices=["sft", "dpo"], default="sft")
    p.add_argument("--kb-id", type=int, default=None, help="限定知识库")
    p.add_argument("--out", required=True, help="输出 jsonl 路径")
    args = p.parse_args()

    db = SessionLocal()
    try:
        if args.type == "sft":
            dataset = finetune_data_service.build_sft_dataset(db, args.kb_id)
        else:
            dataset = finetune_data_service.build_dpo_dataset(db, args.kb_id)
    finally:
        db.close()

    path = finetune_data_service.export_jsonl(dataset, args.out)
    print(f"已导出 {len(dataset)} 条 {args.type.upper()} 样本到 {path}")


if __name__ == "__main__":
    main()
