"""文档相关 Schema"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentResponse(BaseModel):
    """文档响应"""
    id: int
    kb_id: int
    filename: str
    file_size: int
    file_type: str
    status: str
    chunk_count: int
    error_msg: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentListResponse(BaseModel):
    """文档列表响应"""
    total: int
    items: list[DocumentResponse]
