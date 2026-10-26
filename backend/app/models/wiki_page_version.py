"""
LLM Wiki 页面历史版本模型
- 每次页面内容被更新（AI 重编译 / 人工编辑）前，保存一份旧内容快照
- 支持查看历史、对比、回滚到任意版本
"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from ..database import Base
from ..timeutil import utc_now


class WikiPageVersion(Base):
    """Wiki 页面历史版本快照"""

    __tablename__ = "wiki_page_versions"

    id = Column(Integer, primary_key=True, index=True)
    page_id = Column(
        Integer, ForeignKey("wiki_pages.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属页面",
    )
    # 该快照对应的版本号（保存时页面的旧 version）
    version = Column(Integer, nullable=False, comment="快照版本号")
    title = Column(String(200), default="", comment="该版本的标题")
    content = Column(Text, default="", comment="该版本的正文")
    summary = Column(String(500), default="", comment="该版本的摘要")
    # 变更来源：compile=AI重编译；manual=人工编辑；rollback=回滚
    change_source = Column(String(20), default="compile", comment="变更来源")
    editor_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="人工编辑者（AI 编译时为空）",
    )
    created_at = Column(DateTime, default=utc_now, comment="快照生成时间")

    page = relationship("WikiPage", backref="versions")
