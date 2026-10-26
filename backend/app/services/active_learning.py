"""
主动学习服务
- 分析用户点踩（负反馈）的回答，定位失败原因
- 统计失败模式：检索没命中 / 命中了但答错 / 资料缺失
- 自动给出优化建议（补文档 / 调切片 / 调阈值）

这是"系统自我迭代"的闭环：
    用户反馈 -> 归因分析 -> 优化建议 -> 人工/自动改进 -> 再验证
"""
from datetime import timedelta
from typing import Dict, List

from sqlalchemy.orm import Session

from ..models.conversation import Conversation
from ..models.document import Document
from ..models.knowledge_base import KnowledgeBase
from ..models.message import Message
from ..timeutil import utc_now
from ..utils.logger import get_logger

logger = get_logger(__name__)


class ActiveLearningService:
    """主动学习与负反馈归因"""

    def analyze(
        self,
        db: Session,
        user_id: int,
        days: int = 30,
    ) -> Dict:
        """
        分析最近 N 天的负反馈，归因并给出建议。
        """
        since = utc_now() - timedelta(days=days)

        # 所有 assistant 消息（含反馈）
        rows = (
            db.query(Message, Conversation, KnowledgeBase)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .join(KnowledgeBase, Conversation.kb_id == KnowledgeBase.id)
            .filter(
                Conversation.user_id == user_id,
                Message.role == "assistant",
                Message.created_at >= since,
            )
            .all()
        )

        total = len(rows)
        positive = sum(1 for m, _, _ in rows if m.feedback == 1)
        negative = sum(1 for m, _, _ in rows if m.feedback == -1)

        # 对每条负反馈归因
        issues = []
        for msg, conv, kb in rows:
            if msg.feedback != -1:
                continue
            # 找到该问题对应的用户提问（上一条消息）
            user_question = (
                db.query(Message)
                .filter(
                    Message.conversation_id == conv.id,
                    Message.role == "user",
                    Message.id < msg.id,
                )
                .order_by(Message.id.desc())
                .first()
            )
            question = user_question.content if user_question else ""
            root_cause = self._attribute_root_cause(
                db, kb.id, question, msg.content
            )
            issues.append({
                "question": question,
                "kb_name": kb.name,
                "kb_id": kb.id,
                "root_cause": root_cause["cause"],
                "suggestion": root_cause["suggestion"],
            })

        # 按原因聚合
        cause_counts: Dict[str, int] = {}
        for item in issues:
            cause_counts[item["root_cause"]] = (
                cause_counts.get(item["root_cause"], 0) + 1
            )

        # 总体优化建议
        recommendations = self._build_recommendations(cause_counts, issues)

        return {
            "days": days,
            "total_answers": total,
            "positive_feedback": positive,
            "negative_feedback": negative,
            "satisfaction_rate": round(positive / total, 3) if total else 0,
            "negative_rate": round(negative / total, 3) if total else 0,
            "root_cause_distribution": cause_counts,
            "issues": issues,
            "recommendations": recommendations,
        }

    def _attribute_root_cause(
        self,
        db: Session,
        kb_id: int,
        question: str,
        answer: str,
    ) -> Dict:
        """
        对单条负反馈归因：
        - missing_knowledge：检索不到相关资料（知识库缺文档）
        - poor_retrieval：文档存在但没检索到（切片/阈值问题）
        - poor_generation：检索到了但生成质量差（提示词问题）
        这里用启发式判断，不额外调用 LLM（省成本）。
        """
        if not question:
            return {
                "cause": "unknown",
                "suggestion": "无法定位问题，建议人工复查",
            }

        # 重新检索，看是否能找到资料
        try:
            from ..services.rag_service import rag_service
            sources = rag_service.retrieve(kb_id, question)
        except Exception:
            sources = []

        if not sources:
            # 检索不到
            # 进一步判断：知识库是否真的没有相关文档
            doc_count = (
                db.query(Document)
                .filter(Document.kb_id == kb_id, Document.status == "completed")
                .count()
            )
            if doc_count == 0:
                return {
                    "cause": "missing_knowledge",
                    "suggestion": "知识库没有文档，请先上传相关资料",
                }
            return {
                "cause": "poor_retrieval",
                "suggestion": "文档可能存在但未检索到，建议降低相似度阈值、优化切片或改写查询",
            }

        # 检索到了，可能是生成质量问题
        # 检查答案是否包含"无法回答"类兜底
        if answer and ("无法回答" in answer or "暂时无法" in answer):
            return {
                "cause": "poor_retrieval",
                "suggestion": "检索片段与问题匹配度低，建议检查切片质量或启用查询改写",
            }
        return {
            "cause": "poor_generation",
            "suggestion": "已检索到资料但回答不理想，建议优化系统提示词或降低温度",
        }

    def _build_recommendations(
        self,
        cause_counts: Dict[str, int],
        issues: List[Dict],
    ) -> List[str]:
        """根据归因分布生成总体建议"""
        recs = []
        if cause_counts.get("missing_knowledge", 0) > 0:
            recs.append(
                f"有 {cause_counts['missing_knowledge']} 个问题因知识库缺资料无法回答，建议补充对应文档"
            )
        if cause_counts.get("poor_retrieval", 0) > 0:
            recs.append(
                f"有 {cause_counts['poor_retrieval']} 个问题文档存在但未检索到，建议：降低 SIMILARITY_THRESHOLD、启用 Self-RAG、检查父子分块"
            )
        if cause_counts.get("poor_generation", 0) > 0:
            recs.append(
                f"有 {cause_counts['poor_generation']} 个问题检索正常但生成质量差，建议优化提示词"
            )
        if not recs:
            recs.append("暂无明显负反馈，保持当前配置")
        return recs


active_learning_service = ActiveLearningService()
