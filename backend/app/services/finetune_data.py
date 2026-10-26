"""
微调数据准备服务
================================================
把知识库中已有的"高质量问答"导出为模型微调数据：
- SFT（监督微调）：问题 -> 标准答案
    来源：golden_qa 评测集、历史对话中的 user/assistant 配对
- DPO（偏好优化）：同一问题的 好答案(chosen) vs 差答案(rejected)
    来源：用户点赞/点踩的反馈

输出为标准 JSONL，可直接喂给 transformers / LLaMA-Factory / unsloth 等。
"""
import json
import os
from typing import Dict, List

from sqlalchemy.orm import Session

from ..config import settings
from ..models.conversation import Conversation
from ..models.message import Message
from ..utils.logger import get_logger

logger = get_logger(__name__)


SFT_SYSTEM = "你是企业知识库助手，基于知识库内容准确、简洁地回答问题。"


class FinetuneDataService:
    """微调数据导出"""

    def build_sft_dataset(
        self, db: Session, kb_id: int = None, include_history: bool = True
    ) -> List[Dict]:
        """
        构建 SFT 数据集（messages 格式）。
        数据量越大、质量越高，微调效果越好。
        """
        dataset: List[Dict] = []
        seen = set()

        # 1. golden_qa 评测集（人工标注，质量最高）
        golden = self._load_golden()
        for case in golden:
            if kb_id and case.get("kb_id") != kb_id:
                continue
            q = case.get("question", "").strip()
            a = case.get("reference_answer", "").strip()
            if not q or not a or q in seen:
                continue
            seen.add(q)
            dataset.append({
                "messages": [
                    {"role": "system", "content": SFT_SYSTEM},
                    {"role": "user", "content": q},
                    {"role": "assistant", "content": a},
                ]
            })

        # 2. 历史对话配对（真实问答，需过滤）
        if include_history:
            convs = db.query(Conversation)
            if kb_id:
                convs = convs.filter(Conversation.kb_id == kb_id)
            for conv in convs.all():
                msgs = (
                    db.query(Message)
                    .filter(Message.conversation_id == conv.id)
                    .order_by(Message.id)
                    .all()
                )
                for i in range(len(msgs) - 1):
                    if msgs[i].role != "user" or msgs[i + 1].role != "assistant":
                        continue
                    q = msgs[i].content.strip()
                    a = msgs[i + 1].content.strip()
                    # 过滤：答案太短、"无法回答"、已存在
                    if (
                        not q or not a or len(a) < 10
                        or q in seen
                        or "无法回答" in a
                    ):
                        continue
                    seen.add(q)
                    dataset.append({
                        "messages": [
                            {"role": "system", "content": SFT_SYSTEM},
                            {"role": "user", "content": q},
                            {"role": "assistant", "content": a},
                        ]
                    })

        return dataset

    def build_dpo_dataset(
        self, db: Session, kb_id: int = None
    ) -> List[Dict]:
        """
        构建 DPO 偏好数据集。
        对同一问题，找出"被点赞的好答案"和"被点踩的差答案"。
        """
        # 收集每个问题（取 user 消息）的好/差答案
        # key: user 问题文本；value: {"chosen": [...], "rejected": [...]}
        pool: Dict[str, Dict[str, List[str]]] = {}

        convs = db.query(Conversation)
        if kb_id:
            convs = convs.filter(Conversation.kb_id == kb_id)

        for conv in convs.all():
            msgs = (
                db.query(Message)
                .filter(Message.conversation_id == conv.id)
                .order_by(Message.id)
                .all()
            )
            # 找最近的 user 问题
            last_question = None
            for m in msgs:
                if m.role == "user":
                    last_question = m.content.strip()
                elif m.role == "assistant" and last_question and m.feedback:
                    bucket = pool.setdefault(
                        last_question, {"chosen": [], "rejected": []}
                    )
                    if m.feedback == 1:
                        bucket["chosen"].append(m.content.strip())
                    elif m.feedback == -1:
                        bucket["rejected"].append(m.content.strip())

        dataset = []
        for prompt, bucket in pool.items():
            if not bucket["chosen"] or not bucket["rejected"]:
                continue
            dataset.append({
                "prompt": [
                    {"role": "system", "content": SFT_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                "chosen": [
                    {"role": "assistant", "content": bucket["chosen"][0]}
                ],
                "rejected": [
                    {"role": "assistant", "content": bucket["rejected"][0]}
                ],
            })
        return dataset

    def export_jsonl(self, dataset: List[Dict], path: str) -> str:
        """把数据集写为 JSONL 文件"""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for item in dataset:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        logger.info(f"导出 {len(dataset)} 条到 {path}")
        return path

    def _load_golden(self) -> List[Dict]:
        path = settings.EVAL_DATASET_PATH
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f).get("cases", [])
        except (json.JSONDecodeError, OSError):
            return []


finetune_data_service = FinetuneDataService()
