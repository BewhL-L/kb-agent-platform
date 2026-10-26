"""FastAPI 通用依赖"""
from typing import Optional, Tuple

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import KbMember, KnowledgeBase, User
from .security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

# 角色等级：数值越大权限越高，便于用 >= 比较
ROLE_LEVEL = {"viewer": 1, "editor": 2, "owner": 3}
ROLE_LABEL = {"viewer": "查看者", "editor": "编辑者", "owner": "所有者"}


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """获取当前登录用户，未登录返回 401"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="未登录或登录已过期",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = decode_token(token)
    if payload is None:
        raise credentials_exception
    user_id = payload.get("sub")
    if user_id is None:
        raise credentials_exception
    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None or not user.is_active:
        raise credentials_exception
    return user


# ============ 知识库级 RBAC ============

def get_kb_role(db: Session, kb_id: int, user: User) -> Optional[str]:
    """
    返回当前用户在该知识库的角色：owner / editor / viewer，无权限返回 None。

    判定顺序（顺序本身就是业务规则）：
      1. 创建者 -> owner（不查中间表，避免脏数据把创建者降权）
      2. 中间表有记录 -> 记录里的 role
      3. 都没有 -> None
    """
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if kb is None:
        return None
    if kb.user_id == user.id:
        return "owner"
    member = (
        db.query(KbMember)
        .filter(KbMember.kb_id == kb_id, KbMember.user_id == user.id)
        .first()
    )
    return member.role if member else None


def require_kb_role(
    db: Session,
    kb_id: int,
    user: User,
    min_role: str = "viewer",
) -> Tuple[KnowledgeBase, str]:
    """
    校验并返回 (知识库, 角色)。不满足时抛 404 / 403。

    用法：`kb, role = require_kb_role(db, kb_id, current_user, "editor")`
    读接口用 viewer，写接口（上传/改名/删除/邀请）用 editor 或 owner。
    """
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")

    role = "owner" if kb.user_id == user.id else None
    if role is None:
        member = (
            db.query(KbMember)
            .filter(KbMember.kb_id == kb_id, KbMember.user_id == user.id)
            .first()
        )
        role = member.role if member else None

    if role is None:
        raise HTTPException(status_code=403, detail="无权访问该知识库")
    if ROLE_LEVEL.get(role, 0) < ROLE_LEVEL[min_role]:
        raise HTTPException(
            status_code=403,
            detail=f"权限不足：需要 {ROLE_LABEL[min_role]} 及以上，当前为 {ROLE_LABEL.get(role, role)}",
        )
    return kb, role
