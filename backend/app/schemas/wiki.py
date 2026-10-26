"""LLM Wiki 相关 Schema"""
from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class WikiPageResponse(BaseModel):
    """Wiki 页面响应"""
    id: int
    title: str
    content: str
    summary: str
    entity_type: str
    kb_id: int
    source_doc_ids: List[int] = []
    related_page_ids: List[int] = []
    conflict_flags: List[Any] = []
    status: str
    version: int
    error_msg: str = ""
    compiled_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WikiPageListItem(BaseModel):
    """Wiki 页面列表项（不含正文，减少传输）"""
    id: int
    title: str
    summary: str
    entity_type: str
    kb_id: int
    conflict_count: int = 0
    status: str
    version: int
    compiled_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class WikiGraphNode(BaseModel):
    """图谱节点"""
    id: int
    title: str
    entity_type: str


class WikiGraphEdge(BaseModel):
    """图谱边"""
    source: int
    target: int


class WikiGraphResponse(BaseModel):
    """Wiki 关联图谱"""
    nodes: List[WikiGraphNode]
    edges: List[WikiGraphEdge]


class WikiRecompileResponse(BaseModel):
    """重编译结果"""
    message: str
    created: int = 0
    updated: int = 0
    failed: int = 0


class WikiPageEditRequest(BaseModel):
    """人工编辑页面请求"""
    content: str = Field(..., description="编辑后的 Markdown 正文")
    summary: Optional[str] = Field(None, description="可选：更新摘要")


class WikiVersionResponse(BaseModel):
    """页面历史版本响应"""
    id: int
    page_id: int
    version: int
    title: str
    content: str
    summary: str
    change_source: str
    editor_id: Optional[int] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class WikiRollbackResponse(BaseModel):
    """回滚结果"""
    message: str
    current_version: int
