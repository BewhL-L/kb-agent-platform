"""
把 golden QA（或人工整理的高质量问答）转换为 OpenAI 兼容的微调 jsonl。
在 scripts/finetune 目录下运行：
  python prepare_finetune_data.py \
    --golden ../../app/evaluation/data/golden_qa.json \
    --out finetune_train.jsonl
"""
import argparse
import json

SYSTEM_CONTENT = "你是企业知识库助手，依据资料准确作答，语气专业简洁。"


def from_golden(path: str):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    rows = []
    for c in data.get("cases", []):
        if c.get("reference_answer"):
            rows.append({
                "messages": [
                    {"role": "system", "content": SYSTEM_CONTENT},
                    {"role": "user", "content": c["question"]},
                    {"role": "assistant", "content": c["reference_answer"]},
                ]
            })
    return rows


def main():
    p = argparse.ArgumentParser(description="生成微调训练数据")
    p.add_argument("--golden", required=True, help="golden_qa.json 路径")
    p.add_argument("--out", default="finetune_train.jsonl")
    args = p.parse_args()

    rows = from_golden(args.golden)
    with open(args.out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"已写出 {len(rows)} 条训练样本到 {args.out}")


if __name__ == "__main__":
    main()
