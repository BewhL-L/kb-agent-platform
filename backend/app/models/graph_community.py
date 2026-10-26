"""
GraphRAG 社区模型
- 社区检测把密集相连的实体聚成若干"社区"
- 每个社区用 LLM 生成主题摘要，用于回答"全局理解型问题"
"""
from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text

from ..database import Base
from ..timeutil import utc_now


class GraphCommunity(Base):
    """GraphRAG 实体社区"""

    __tablename__ = "graph_communities"

    id = Column(Integer, primary_key=True, index=True)
    kb_id = Column(
        Integer, ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    community_index = Column(Integer, default=0, comment="社区编号")
    title = Column(String(200), default="", comment="社区主题")
    summary = Column(Text, default="", comment="社区摘要（LLM 生成）")
    entity_ids = Column(JSON, default=list, comment="社区包含的实体 ID")
    entity_count = Column(Integer, default=0)

    created_at = Column(DateTime, default=utc_now)
