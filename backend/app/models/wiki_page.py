"""
LLM Wiki 页面模型
- 每个实体/概念对应一个结构化 Markdown 页面
- 页面由文档编译生成，可溯源到原始文档
- 维护页面间的双向链接与知识冲突标记
"""
from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship

from ..database import Base
from ..timeutil import utc_now


class WikiPage(Base):
    """LLM Wiki 编译生成的知识页面"""

    __tablename__ = "wiki_pages"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False, index=True, comment="页面标题（实体/概念名）")
    content = Column(Text, default="", comment="结构化 Markdown 正文")
    summary = Column(String(500), default="", comment="一句话摘要")
    entity_type = Column(
        String(30), default="concept", index=True,
        comment="实体类型: person/concept/tool/api/process/term/other",
    )
    kb_id = Column(
        Integer, ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属知识库",
    )
    # 来源文档 ID 列表（可溯源）
    source_doc_ids = Column(JSON, default=list, comment="来源文档ID列表")
    # 双向链接的关联页面 ID 列表
    related_page_ids = Column(JSON, default=list, comment="关联页面ID列表")
    # 知识冲突标记：[{"field": "...", "doc_id": ..., "detail": "..."}]
    conflict_flags = Column(JSON, default=list, comment="检测到的知识冲突")
    # 编译状态：compiled=已编译；stale=文档有更新待重编译；failed=编译失败
    status = Column(String(20), default="compiled", comment="编译状态")
    version = Column(Integer, default=1, comment="页面版本号")
    error_msg = Column(Text, default="", comment="最近一次编译错误")
    compiled_at = Column(DateTime, default=utc_now, comment="最近编译时间")
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # 页面列表：WHERE kb_id=? [AND entity_type=?] [AND status=?]
    __table_args__ = (
        Index("ix_wiki_pages_kb_type", "kb_id", "entity_type"),
    )

    # 关系
    knowledge_base = relationship("KnowledgeBase", backref="wiki_pages")
