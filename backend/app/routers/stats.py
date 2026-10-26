"""数据统计路由"""
from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Conversation, Document, KnowledgeBase, Message, User
from ..timeutil import utc_now
from ..utils.deps import get_current_user

router = APIRouter(tags=["数据统计"])


@router.get("/stats", summary="获取数据看板统计")
def get_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 知识库数量
    kb_count = db.query(func.count(KnowledgeBase.id)) \
        .filter(KnowledgeBase.user_id == current_user.id).scalar()

    # 文档数量（已处理完成的）
    doc_count = db.query(func.count(Document.id)) \
        .join(KnowledgeBase, Document.kb_id == KnowledgeBase.id) \
        .filter(KnowledgeBase.user_id == current_user.id,
                Document.status == "completed").scalar()

    # 对话数量
    conv_count = db.query(func.count(Conversation.id)) \
        .filter(Conversation.user_id == current_user.id).scalar()

    # AI 回答数量（assistant 消息数）
    qa_count = db.query(func.count(Message.id)) \
        .join(Conversation, Message.conversation_id == Conversation.id) \
        .filter(Conversation.user_id == current_user.id,
                Message.role == "assistant").scalar()

    # 近 7 天问答趋势
    seven_days_ago = utc_now() - timedelta(days=7)
    daily = db.query(
        func.date(Message.created_at).label("day"),
        func.count(Message.id).label("count"),
    ).join(Conversation, Message.conversation_id == Conversation.id) \
        .filter(
        Conversation.user_id == current_user.id,
        Message.role == "assistant",
        Message.created_at >= seven_days_ago,
    ).group_by(func.date(Message.created_at)).all()

    # 补齐 7 天数据
    trend = []
    daily_map = {str(row.day): row.count for row in daily}
    for i in range(6, -1, -1):
        date = (utc_now() - timedelta(days=i)).strftime("%Y-%m-%d")
        trend.append({"date": date, "count": daily_map.get(date, 0)})

    # 各知识库文档占比
    kb_dist = db.query(
        KnowledgeBase.name,
        func.count(Document.id).label("doc_count"),
    ).outerjoin(Document, Document.kb_id == KnowledgeBase.id) \
        .filter(KnowledgeBase.user_id == current_user.id) \
        .group_by(KnowledgeBase.id).all()

    return {
        "overview": {
            "kb_count": kb_count,
            "doc_count": doc_count,
            "conversation_count": conv_count,
            "qa_count": qa_count,
        },
        "weekly_trend": trend,
        "kb_distribution": [
            {"name": row.name, "doc_count": row.doc_count} for row in kb_dist
        ],
    }


@router.get("/stats/cost", summary="LLM 成本与用量统计")
def get_cost_stats(
    days: int = 30,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前用户最近 N 天的 LLM 调用费用、token、按用途/模型拆分"""
    from ..services.usage_service import usage_service

    return usage_service.get_summary(
        db, days=days, user_id=current_user.id
    )


@router.get("/stats/active-learning", summary="主动学习：负反馈归因与优化建议")
def active_learning_stats(
    days: int = 30,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """分析点踩回答的失败原因，给出优化建议"""
    from ..services.active_learning import active_learning_service

    return active_learning_service.analyze(
        db, current_user.id, days=days
    )
