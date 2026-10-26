"""
知识蒸馏数据生成（Data Distillation）
================================================
用一个强大的"教师模型"（Teacher，如 GPT-4o / deepseek-r1）在你的知识库上
批量生成高质量问答，再用这些数据训练一个便宜的"学生模型"（Student，
如 1.5B 小模型）。学生模型由此"学会"教师的能力，部署成本却低得多。

这是"用大模型养小模型"的落地方式，也是 RAG 应用降低成本的常用手段。

【运行】（在 backend 目录下，需配置有效的教师模型 LLM_API_KEY）
  python scripts/inference/distill.py \
      --kb-id 1 --out distill_sft.jsonl \
      --questions-per-doc 5

流程：
  文档切片 -> 教师生成问题 -> 教师生成答案 -> 输出 SFT jsonl
  -> 用 train_lora.py 训练学生模型
"""
import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.database import SessionLocal
from app.models.document import Document
from app.services.document_parser import parse_document
from app.services.llm_service import LLMService
from app.services.text_splitter import split_text

GEN_QUESTION_PROMPT = """请基于以下资料内容，生成 {n} 个用户可能会问的问题。
只输出 JSON：{{"questions": ["问题1", "问题2"]}}
资料：{content}"""

GEN_ANSWER_PROMPT = """请严格依据以下资料回答问题，准确简洁。
问题：{question}
资料：{content}"""

SFT_SYSTEM = "你是企业知识库助手，基于知识库内容准确、简洁地回答问题。"


async def main():
    args = parse_args()
    db = SessionLocal()
    llm = LLMService()
    dataset = []

    try:
        query = db.query(Document).filter(
            Document.kb_id == args.kb_id, Document.status == "completed"
        )
        docs = query.all()
        for doc in docs:
            text = parse_document(doc.file_path)
            chunks = split_text(text)
            # 取前若干个内容较充实的切片做蒸馏
            candidates = [c for c in chunks if len(c) > 100][:3]
            for chunk in candidates:
                questions = await _gen_questions(llm, chunk, args.questions_per_doc)
                for q in questions:
                    a = await llm.chat(
                        [{"role": "user", "content": GEN_ANSWER_PROMPT.format(
                            question=q, content=chunk)}],
                        temperature=0.2, purpose="chat",
                    )
                    if a and "无法回答" not in a:
                        dataset.append({
                            "messages": [
                                {"role": "system", "content": SFT_SYSTEM},
                                {"role": "user", "content": q},
                                {"role": "assistant", "content": a},
                            ]
                        })
    finally:
        db.close()

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for item in dataset:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"蒸馏数据 {len(dataset)} 条已保存到 {args.out}")
    print("接下来用 scripts/finetune/train_lora.py 训练学生模型。")


async def _gen_questions(llm, content, n):
    try:
        raw = await llm.chat(
            [{"role": "user", "content": GEN_QUESTION_PROMPT.format(
                n=n, content=content[:2000])}],
            temperature=0.7, purpose="chat",
        )
        s, e = raw.find("{"), raw.rfind("}")
        if s != -1 and e != -1:
            d = json.loads(raw[s:e + 1])
            return [q for q in d.get("questions", []) if q.strip()][:n]
    except Exception:
        pass
    return []


def parse_args():
    p = argparse.ArgumentParser(description="知识蒸馏数据生成")
    p.add_argument("--kb-id", type=int, required=True)
    p.add_argument("--out", default="distill_sft.jsonl")
    p.add_argument("--questions-per-doc", type=int, default=5)
    return p.parse_args()


if __name__ == "__main__":
    asyncio.run(main())
