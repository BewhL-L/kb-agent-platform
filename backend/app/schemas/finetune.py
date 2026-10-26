"""微调数据导出 schema"""
from typing import Optional

from pydantic import BaseModel, Field


class FinetuneExportRequest(BaseModel):
    """导出微调数据请求"""
    type: str = Field("sft", pattern="^(sft|dpo)$")
    kb_id: Optional[int] = None
