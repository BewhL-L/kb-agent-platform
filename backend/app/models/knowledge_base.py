"""知识库模型"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from ..database import Base
from ..timeutil import utc_now


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, comment="知识库名称")
    description = Column(Text, default="", comment="知识库描述")
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True, comment="所属用户")
    embed_code = Column(String(20), unique=True, index=True, comment="嵌入代码标识")
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # 关系
    user = relationship("User", back_populates="knowledge_bases")
    documents = relationship("Document", back_populates="knowledge_base", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="knowledge_base", cascade="all, delete-orphan")
    # 被邀请的协作者（创建者不在其中，见 models/kb_member.py 的说明）
    members = relationship("KbMember", back_populates="knowledge_base", cascade="all, delete-orphan")
