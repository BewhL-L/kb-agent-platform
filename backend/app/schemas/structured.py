"""结构化回答相关 Schema

三种模板的 JSON 契约（前后端必须一致，改这里要同步改
frontend/src/utils/structured_parse.ts）：

bullets     -> {"title": str, "bullets": [str, ...]}
comparison  -> {"title": str, "headers": [str, ...], "rows": [[str, ...], ...]}
timeline    -> {"title": str, "events": [{"time": str, "title": str, "detail": str}, ...]}
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field

AnswerTemplate = Literal["bullets", "comparison", "timeline"]


class StructuredRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000, description="要回答的问题")
    template: AnswerTemplate = Field("bullets", description="输出模板")
    kb_id: Optional[int] = Field(
        None, description="传入则先检索该知识库再把资料喂给模型；不传则纯生成"
    )


class StructuredResponse(BaseModel):
    template: str
    result: dict = Field(..., description="已按模板规范化后的结果")
    raw: str = Field("", description="模型原始输出，便于排查解析失败")
    degraded: bool = Field(
        False, description="true 表示模型没返回合法 JSON，已降级为要点列表"
    )
