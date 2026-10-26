"""用户模型"""
from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.orm import relationship

from ..database import Base
from ..timeutil import utc_now


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True, comment="用户名")
    email = Column(String(100), unique=True, nullable=True, index=True, comment="邮箱")
    password_hash = Column(String(255), nullable=False, comment="密码哈希")
    is_active = Column(Boolean, default=True, comment="是否启用")
    # 系统级角色（admin/editor/viewer）；知识库内的角色在 kb_members 表，两套不要混淆
    role = Column(String(16), nullable=False, default="editor", comment="系统级角色")
    current_model = Column(String(100), default="", comment="当前选择的模型")
    created_at = Column(DateTime, default=utc_now, comment="创建时间")
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, comment="更新时间")

    # 关系
    knowledge_bases = relationship("KnowledgeBase", back_populates="user", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="user", cascade="all, delete-orphan")
