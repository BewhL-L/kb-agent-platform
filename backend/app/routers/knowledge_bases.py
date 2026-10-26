"""知识库管理路由（含 RBAC 成员管理）"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Document, KbMember, KnowledgeBase, User
from ..schemas import (
    KBCreate,
    KbMemberInvite,
    KbMemberList,
    KbMemberResponse,
    KBResponse,
    KBUpdate,
)
from ..services import document_service
from ..utils.deps import get_current_user, require_kb_role

router = APIRouter(prefix="/kb", tags=["知识库"])


@router.post("", response_model=KBResponse, summary="创建知识库")
def create_kb(
    data: KBCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    kb = KnowledgeBase(
        name=data.name,
        description=data.description,
        user_id=current_user.id,
        embed_code=uuid.uuid4().hex[:16],
    )
    db.add(kb)
    db.commit()
    db.refresh(kb)
    return _to_response(kb, 0, "owner")


@router.get("", summary="知识库列表（我的 + 共享给我的，分页）")
def list_kb(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str = Query(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    列表口径从「只看自己创建的」改为「自己创建的 + 被邀请协作的」。
    子查询先取 id，再统一分页，避免 join 之后 distinct 去重带来的分页错位。
    """
    owned_ids = select(KnowledgeBase.id).where(
        KnowledgeBase.user_id == current_user.id
    )
    shared_ids = select(KbMember.kb_id).where(KbMember.user_id == current_user.id)

    query = db.query(KnowledgeBase).filter(
        or_(KnowledgeBase.id.in_(owned_ids), KnowledgeBase.id.in_(shared_ids))
    )
    if keyword:
        query = query.filter(KnowledgeBase.name.contains(keyword))
    total = query.count()
    kbs = query.order_by(KnowledgeBase.updated_at.desc()) \
        .offset((page - 1) * page_size).limit(page_size).all()

    # 一次取出我在这批库里的成员角色，避免循环里 N 次查询
    role_map = dict(
        db.query(KbMember.kb_id, KbMember.role)
        .filter(KbMember.user_id == current_user.id)
        .all()
    )

    items = []
    for kb in kbs:
        doc_count = db.query(func.count(Document.id)) \
            .filter(Document.kb_id == kb.id, Document.status == "completed").scalar()
        role = "owner" if kb.user_id == current_user.id else role_map.get(kb.id, "viewer")
        items.append(_to_response(kb, doc_count, role).model_dump())
    return {"total": total, "items": items}


@router.get("/{kb_id}", response_model=KBResponse, summary="知识库详情")
def get_kb(
    kb_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    kb, role = require_kb_role(db, kb_id, current_user, "viewer")
    doc_count = db.query(func.count(Document.id)) \
        .filter(Document.kb_id == kb_id, Document.status == "completed").scalar()
    return _to_response(kb, doc_count, role)


@router.put("/{kb_id}", response_model=KBResponse, summary="更新知识库")
def update_kb(
    kb_id: int,
    data: KBUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 改名/改描述属于写操作，editor 及以上
    kb, role = require_kb_role(db, kb_id, current_user, "editor")
    if data.name is not None:
        kb.name = data.name
    if data.description is not None:
        kb.description = data.description
    db.commit()
    db.refresh(kb)
    doc_count = db.query(func.count(Document.id)) \
        .filter(Document.kb_id == kb_id, Document.status == "completed").scalar()
    return _to_response(kb, doc_count, role)


@router.delete("/{kb_id}", summary="删除知识库")
def delete_kb(
    kb_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    kb, _ = require_kb_role(db, kb_id, current_user, "owner")
    # 先删向量库
    document_service.delete_kb_vectors(kb_id)
    db.delete(kb)
    db.commit()
    return {"message": "删除成功"}


@router.get("/{kb_id}/embed-code", summary="获取嵌入代码")
def get_embed_code(
    kb_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 嵌入码一旦泄露就是把库对外公开，只允许 owner 查看
    kb, _ = require_kb_role(db, kb_id, current_user, "owner")
    return {
        "embed_code": kb.embed_code,
        "iframe_code": f'<iframe src="/embed/{kb.embed_code}" width="400" height="600" frameborder="0"></iframe>',
        "script_code": f'<script src="/embed/{kb.embed_code}.js" async></script>',
    }


# ============ RBAC：成员管理 ============

@router.get("/{kb_id}/members", response_model=KbMemberList, summary="成员列表")
def list_members(
    kb_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    返回 owner（虚拟行）+ 中间表里的成员，并附带 my_role。
    前端用 my_role 决定「邀请 / 移除」按钮是否显示，不必再算一遍权限。
    """
    kb, role = require_kb_role(db, kb_id, current_user, "viewer")

    owner = db.query(User).filter(User.id == kb.user_id).first()
    items = [
        KbMemberResponse(
            id=None,
            user_id=owner.id,
            username=owner.username,
            role="owner",
            is_owner=True,
            created_at=kb.created_at,
        )
    ]

    rows = (
        db.query(KbMember, User)
        .join(User, User.id == KbMember.user_id)
        .filter(KbMember.kb_id == kb_id)
        .order_by(KbMember.id)
        .all()
    )
    for member, user in rows:
        items.append(
            KbMemberResponse(
                id=member.id,
                user_id=user.id,
                username=user.username,
                role=member.role,
                is_owner=False,
                created_at=member.created_at,
            )
        )
    return KbMemberList(items=items, my_role=role)


@router.post("/{kb_id}/members", response_model=KbMemberResponse, summary="邀请成员")
def add_member(
    kb_id: int,
    data: KbMemberInvite,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    kb, _ = require_kb_role(db, kb_id, current_user, "owner")

    target = db.query(User).filter(User.username == data.username).first()
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    if target.id == kb.user_id:
        raise HTTPException(status_code=400, detail="该用户已是知识库所有者")

    exists = (
        db.query(KbMember)
        .filter(KbMember.kb_id == kb_id, KbMember.user_id == target.id)
        .first()
    )
    if exists:
        raise HTTPException(status_code=400, detail="该用户已是成员")

    member = KbMember(kb_id=kb_id, user_id=target.id, role=data.role)
    db.add(member)
    db.commit()
    db.refresh(member)
    return KbMemberResponse(
        id=member.id,
        user_id=target.id,
        username=target.username,
        role=member.role,
        is_owner=False,
        created_at=member.created_at,
    )


@router.delete("/{kb_id}/members/{member_id}", summary="移除成员")
def remove_member(
    kb_id: int,
    member_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_kb_role(db, kb_id, current_user, "owner")
    member = (
        db.query(KbMember)
        .filter(KbMember.id == member_id, KbMember.kb_id == kb_id)
        .first()
    )
    if not member:
        raise HTTPException(status_code=404, detail="成员不存在")
    db.delete(member)
    db.commit()
    return {"message": "已移除"}


# ============ 内部工具 ============

def _to_response(kb: KnowledgeBase, doc_count: int, role: str = "owner") -> KBResponse:
    return KBResponse(
        id=kb.id,
        name=kb.name,
        description=kb.description or "",
        embed_code=kb.embed_code,
        document_count=doc_count,
        role=role,
        created_at=kb.created_at,
        updated_at=kb.updated_at,
    )
