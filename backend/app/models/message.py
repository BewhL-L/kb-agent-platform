"""消息模型"""
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship

from ..database import Base
from ..timeutil import utc_now


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False, comment="角色: user/assistant")
    content = Column(Text, nullable=False, comment="消息内容")
    sources = Column(Text, default="", comment="来源引用(JSON)")
    feedback = Column(Integer, default=0, comment="反馈: 0无 1点赞 -1点踩")
    created_at = Column(DateTime, default=utc_now)

    # 取历史消息：WHERE conversation_id=? ORDER BY id DESC LIMIT 12
    __table_args__ = (
        Index("ix_messages_conv_id", "conversation_id", "id"),
    )

    conversation = relationship("Conversation", back_populates="messages")


class Feedback(Base):
    """用户反馈表"""
    __tablename__ = "feedbacks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    message_id = Column(Integer, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True)
    feedback_type = Column(Integer, nullable=False, comment="1点赞 -1点踩")
    comment = Column(Text, default="", comment="反馈意见")
    created_at = Column(DateTime, default=utc_now)

    __table_args__ = (Index("idx_user_message", "user_id", "message_id"),)
