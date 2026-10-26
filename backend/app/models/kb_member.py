"""
知识库成员模型（RBAC）
=====================
一张中间表解决「多对多」：一个用户在 A 库是 owner、在 B 库可能是 viewer。
- 创建者不写入本表，直接在 knowledge_bases.user_id 上体现，权限函数里视作 owner
- 本表只记录被邀请的成员：editor（可上传/问答）/ viewer（只读+问答）
"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from ..database import Base
from ..timeutil import utc_now


class KbMember(Base):
    __tablename__ = "kb_members"
    __table_args__ = (
        # 同一用户在同一知识库只能有一条成员记录，靠数据库约束兜底
        UniqueConstraint("kb_id", "user_id", name="uq_kb_member"),
    )

    id = Column(Integer, primary_key=True, index=True)
    kb_id = Column(
        Integer,
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = Column(String(16), nullable=False, default="viewer", comment="editor / viewer")
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    knowledge_base = relationship("KnowledgeBase", back_populates="members")
    user = relationship("User")
