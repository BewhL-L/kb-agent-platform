"""对话与消息 Schema"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class Source(BaseModel):
    """来源引用"""
    document_name: str
    chunk_text: str
    score: float


class MessageResponse(BaseModel):
    """消息响应"""
    id: int
    conversation_id: int
    role: str
    content: str
    sources: list[Source] = []
    feedback: int = 0
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConversationCreate(BaseModel):
    """创建对话"""
    kb_id: int
    title: str = Field("新对话", max_length=200)


class ConversationUpdate(BaseModel):
    """更新对话"""
    title: Optional[str] = None


class ConversationResponse(BaseModel):
    """对话列表项"""
    id: int
    kb_id: int
    title: str
    message_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConversationDetail(ConversationResponse):
    """对话详情（含消息）"""
    messages: list[MessageResponse] = []


class ChatRequest(BaseModel):
    """问答请求"""
    kb_id: int
    question: str = Field(..., min_length=1, max_length=2000)
    conversation_id: Optional[int] = None
    use_agent: bool = False
    # 推理模式：true=强制推理；false=自动判断（简单问题走普通模型）
    use_reasoning: bool = False


class GlobalChatRequest(BaseModel):
    """跨知识库问答请求"""
    question: str = Field(..., min_length=1, max_length=2000)
    # 知识库 ID 列表；为空则检索当前用户的所有知识库
    kb_ids: List[int] = []


class FeedbackCreate(BaseModel):
    """反馈请求"""
    message_id: int
    feedback: int = Field(..., description="1点赞 -1点踩")
    comment: str = ""
