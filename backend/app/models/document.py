"""文档模型"""
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship

from ..database import Base
from ..timeutil import utc_now


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    kb_id = Column(Integer, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True, comment="知识库ID")
    filename = Column(String(255), nullable=False, comment="原始文件名")
    stored_filename = Column(String(255), nullable=False, comment="存储文件名")
    file_path = Column(String(500), nullable=False, comment="文件路径")
    file_size = Column(BigInteger, default=0, comment="文件大小(字节)")
    file_type = Column(String(20), default="", comment="文件类型")
    status = Column(String(20), default="processing", comment="状态: processing/completed/failed")
    chunk_count = Column(Integer, default=0, comment="切片数量")
    error_msg = Column(Text, default="", comment="错误信息")
    created_at = Column(DateTime, default=utc_now)

    # 文档列表：WHERE kb_id=? ORDER BY created_at DESC；统计：WHERE kb_id=? AND status=?
    __table_args__ = (
        Index("ix_documents_kb_created", "kb_id", "created_at"),
        Index("ix_documents_kb_status", "kb_id", "status"),
    )

    # 关系
    knowledge_base = relationship("KnowledgeBase", back_populates="documents")
