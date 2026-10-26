"""知识库相关 Schema"""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class KBCreate(BaseModel):
    """创建知识库"""
    name: str = Field(..., min_length=1, max_length=100, description="知识库名称")
    description: str = Field("", max_length=500, description="描述")


class KBUpdate(BaseModel):
    """更新知识库"""
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = Field(None, max_length=500)


class KBResponse(BaseModel):
    """知识库响应"""
    id: int
    name: str
    description: str
    embed_code: Optional[str] = None
    document_count: int = 0
    # 当前登录用户在该库的角色：owner / editor / viewer（前端据此控制按钮显隐）
    role: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class KBDetail(KBResponse):
    """知识库详情"""
    pass


# ============ RBAC 成员 ============

class KbMemberInvite(BaseModel):
    """邀请成员：只允许邀请为 editor 或 viewer，owner 唯一且不可转让"""
    username: str = Field(..., min_length=1, max_length=50, description="被邀请用户的用户名")
    role: Literal["editor", "viewer"] = Field("viewer", description="editor=可上传/问答；viewer=只读+问答")


class KbMemberResponse(BaseModel):
    """成员列表项。owner 是虚拟行（不存中间表），故 id 可能为 None"""
    id: Optional[int] = None
    user_id: int
    username: str
    role: str
    is_owner: bool = False
    created_at: Optional[datetime] = None


class KbMemberList(BaseModel):
    """成员列表 + 当前用户角色（一次请求拿到两件事，省一次往返）"""
    items: list[KbMemberResponse]
    my_role: str
