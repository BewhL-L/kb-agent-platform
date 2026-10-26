"""对话历史路由"""
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Conversation, Message, User
from ..schemas import (
    ConversationCreate,
    ConversationDetail,
    ConversationResponse,
    ConversationUpdate,
    MessageResponse,
)
from ..utils.deps import get_current_user, require_kb_role

router = APIRouter(tags=["对话历史"])


@router.post("/conversations", response_model=ConversationResponse, summary="创建对话")
def create_conversation(
    data: ConversationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_kb_role(db, data.kb_id, current_user, "viewer")
    conv = Conversation(
        user_id=current_user.id,
        kb_id=data.kb_id,
        title=data.title,
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return _to_response(conv, 0)


@router.get("/conversations", summary="对话列表")
def list_conversations(
    kb_id: int = Query(None, description="按知识库筛选"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Conversation).filter(Conversation.user_id == current_user.id)
    if kb_id:
        query = query.filter(Conversation.kb_id == kb_id)
    total = query.count()
    convs = query.order_by(Conversation.updated_at.desc()) \
        .offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for conv in convs:
        msg_count = db.query(func.count(Message.id)) \
            .filter(Message.conversation_id == conv.id).scalar()
        items.append(_to_response(conv, msg_count).model_dump())
    return {"total": total, "items": items}


@router.get("/conversations/{conv_id}", response_model=ConversationDetail, summary="对话详情（含消息）")
def get_conversation(
    conv_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conv = _get_owned_conv(db, conv_id, current_user.id)
    msg_count = len(conv.messages)
    resp = ConversationDetail(
        **_to_response(conv, msg_count).model_dump(),
        messages=[_message_to_response(m) for m in conv.messages],
    )
    return resp


@router.put("/conversations/{conv_id}", response_model=ConversationResponse, summary="更新对话标题")
def update_conversation(
    conv_id: int,
    data: ConversationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conv = _get_owned_conv(db, conv_id, current_user.id)
    if data.title is not None:
        conv.title = data.title
    db.commit()
    db.refresh(conv)
    return _to_response(conv, len(conv.messages))


@router.delete("/conversations/{conv_id}", summary="删除对话")
def delete_conversation(
    conv_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conv = _get_owned_conv(db, conv_id, current_user.id)
    db.delete(conv)
    db.commit()
    return {"message": "删除成功"}


def _get_owned_conv(db: Session, conv_id: int, user_id: int) -> Conversation:
    conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")
    if conv.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权操作该对话")
    return conv


def _to_response(conv: Conversation, msg_count: int) -> ConversationResponse:
    return ConversationResponse(
        id=conv.id,
        kb_id=conv.kb_id,
        title=conv.title,
        message_count=msg_count,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


def _message_to_response(msg: Message) -> MessageResponse:
    sources = []
    if msg.sources:
        try:
            sources = json.loads(msg.sources)
        except json.JSONDecodeError:
            sources = []
    return MessageResponse(
        id=msg.id,
        conversation_id=msg.conversation_id,
        role=msg.role,
        content=msg.content,
        sources=sources,
        feedback=msg.feedback or 0,
        created_at=msg.created_at,
    )
