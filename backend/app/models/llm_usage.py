"""
LLM 调用记录模型（成本监控）
- 记录每次大模型调用的模型、用途、token 数与估算费用
- 用于成本统计、用量分析、按功能/用户/知识库拆分
"""
from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, String

from ..database import Base
from ..timeutil import utc_now


class LLMUsage(Base):
    """LLM 调用与费用记录"""

    __tablename__ = "llm_usages"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="调用用户",
    )
    kb_id = Column(
        Integer, ForeignKey("knowledge_bases.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="关联知识库",
    )
    model = Column(String(100), default="", index=True, comment="模型名")
    # 用途：chat=问答；compile=Wiki编译；rerank=重排；rewrite=查询改写；
    # memory=记忆压缩；judge=评测打分；other
    purpose = Column(String(30), default="chat", index=True, comment="调用用途")
    # 如 rag_system@2026-10-26.1；为空表示该调用未绑定 Prompt（如直接拼消息）
    prompt_version = Column(String(64), default="", comment="Prompt 版本")
    prompt_tokens = Column(Integer, default=0, comment="输入 token 数")
    completion_tokens = Column(Integer, default=0, comment="输出 token 数")
    total_tokens = Column(Integer, default=0, comment="总 token 数")
    cost = Column(Float, default=0.0, comment="估算费用（元）")
    created_at = Column(DateTime, default=utc_now, index=True, comment="调用时间")

    # 成本报表：按时间区间过滤 + 按 model/purpose 聚合
    __table_args__ = (
        Index("ix_llm_usages_created_model", "created_at", "model"),
        Index("ix_llm_usages_created_purpose", "created_at", "purpose"),
    )
