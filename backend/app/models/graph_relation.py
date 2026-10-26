"""
GraphRAG 关系边模型
- 知识图谱中的有向边：源实体 -> 目标实体
- relation_type 描述关系（如"依赖""属于""包含"）
- weight 记录共现/抽取次数，用于排序与社区检测
"""
from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint

from ..database import Base
from ..timeutil import utc_now


class GraphRelation(Base):
    """GraphRAG 关系边"""

    __tablename__ = "graph_relations"

    id = Column(Integer, primary_key=True, index=True)
    kb_id = Column(
        Integer, ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    source_entity_id = Column(
        Integer, ForeignKey("graph_entities.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    target_entity_id = Column(
        Integer, ForeignKey("graph_entities.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # 冗余名称，便于直接展示
    source_name = Column(String(200), default="")
    target_name = Column(String(200), default="")

    relation_type = Column(String(100), default="关联", comment="关系描述")
    weight = Column(Integer, default=1, comment="共现/抽取次数")
    source_doc_ids = Column(JSON, default=list)

    created_at = Column(DateTime, default=utc_now)

    # 同一对实体（无向）只保留一条边，避免重复
    __table_args__ = (
        UniqueConstraint(
            "kb_id", "source_entity_id", "target_entity_id",
            name="uq_graph_relation",
        ),
    )
