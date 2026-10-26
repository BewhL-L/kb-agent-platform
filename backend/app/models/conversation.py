"""对话模型"""
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship

from ..database import Base
from ..timeutil import utc_now


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True, comment="用户ID")
    kb_id = Column(Integer, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True, comment="知识库ID")
    title = Column(String(200), default="新对话", comment="对话标题")
    # 长期记忆：对更早对话的压缩摘要（短期记忆为最近 N 轮原文）
    long_memory = Column(Text, default="", comment="历史对话压缩摘要")
    # 已压缩到的消息 ID（避免重复压缩）
    memory_upto_msg_id = Column(Integer, default=0, comment="已压缩到的消息ID")
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # 对话列表：WHERE user_id=? ORDER BY updated_at DESC，复合索引可同时覆盖过滤与排序
    __table_args__ = (
        Index("ix_conversations_user_updated", "user_id", "updated_at"),
    )

    # 关系
    user = relationship("User", back_populates="conversations")
    knowledge_base = relationship("KnowledgeBase", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan",
                            order_by="Message.id")
