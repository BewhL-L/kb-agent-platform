"""
GraphRAG 实体节点模型
- 知识图谱中的节点：人物、概念、工具、流程、术语等
- 由文档抽取并合并（同名实体聚合）
- 每个实体可归属到一个社区（community_id）
"""
from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String, Text

from ..database import Base
from ..timeutil import utc_now


class GraphEntity(Base):
    """GraphRAG 实体节点"""

    __tablename__ = "graph_entities"

    id = Column(Integer, primary_key=True, index=True)
    kb_id = Column(
        Integer, ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属知识库",
    )
    name = Column(String(200), nullable=False, index=True, comment="实体名称")
    entity_type = Column(String(30), default="concept", comment="实体类型")
    summary = Column(Text, default="", comment="实体描述")

    # 来源文档 ID 列表
    source_doc_ids = Column(JSON, default=list, comment="来源文档")
    # 所属社区 ID
    community_id = Column(Integer, ForeignKey("graph_communities.id"), nullable=True, index=True)
    # 度数（关系数量，用于衡量实体重要性）
    degree = Column(Integer, default=0, comment="关系度数")

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # 构图时按 (kb_id, name) 查重/合并同名实体
    __table_args__ = (
        Index("ix_graph_entities_kb_name", "kb_id", "name"),
    )
