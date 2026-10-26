"""GraphRAG 请求/响应 schema"""
from typing import List, Optional

from pydantic import BaseModel, Field


class GraphSearchRequest(BaseModel):
    """图谱检索请求"""
    question: str = Field(..., min_length=1, max_length=2000)


class GraphBuildRequest(BaseModel):
    """图谱构建请求（doc_ids 为空则构建整个知识库）"""
    doc_ids: Optional[List[int]] = None
