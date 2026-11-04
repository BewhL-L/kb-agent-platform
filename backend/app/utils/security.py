"""安全工具：密码加密（bcrypt 原生）+ JWT

关于 JWT 的两个设计点（改之前先读）：

1. **必须带 jti**。没有 jti 的 token 只有一个 `exp`，意味着「签发出去就收不回来」——
   员工离职、密码泄露、设备丢失都只能等它自然过期。本项目默认有效期 7 天
   （`ACCESS_TOKEN_EXPIRE_MINUTES = 10080`），收不回来是不能接受的。
2. **吊销标记只存到 exp 为止**。过期的 token 已经被签名 + exp 校验拦住，
   再往吊销表里堆只会让它无限增长。

局限（已知，本版不解决）：吊销是 **单 token 级**，没有 user 级版本号，
所以「改密码后让该用户所有旧 token 立刻失效」还做不到——需要给 `users` 加一列
`token_version` 并写一次迁移。已记进 README「已知限制」。
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from jose import JWTError, jwt

from ..config import settings
from .logger import get_logger

logger = get_logger(__name__)

# bcrypt 仅支持最多 72 字节密码
_MAX_BYTES = 72

# 已吊销 token 的键前缀（按 jti 标记，Redis / 内存缓存都能承载）
_REVOKE_PREFIX = "jwt:revoked:"


def hash_password(password: str) -> str:
    """加密密码"""
    pwd = password.encode("utf-8")[:_MAX_BYTES]
    return bcrypt.hashpw(pwd, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    pwd = plain_password.encode("utf-8")[:_MAX_BYTES]
    try:
        return bcrypt.checkpw(pwd, hashed_password.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """生成 JWT Token

    附带三个声明：
      - `exp` 过期时间（原有）
      - `iat` 签发时间，排障时能算出剩余寿命，也是吊销 TTL 的依据
      - `jti` 本枚 token 的唯一标识，让它可以被单独吊销
    """
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    expire = now + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "iat": now, "jti": uuid.uuid4().hex})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """解析 Token（只验签名与 exp，是否吊销由调用方再查）"""
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return None


def token_remaining_seconds(payload: dict) -> int:
    """token 剩余有效期（秒）。解析不出来返回 0。"""
    exp = payload.get("exp")
    if exp is None:
        return 0
    try:
        return max(0, int(float(exp) - datetime.now(timezone.utc).timestamp()))
    except (TypeError, ValueError):
        return 0


def revoke_token(payload: dict) -> bool:
    """吊销单枚 token。返回是否确实写入了吊销标记。

    没有 jti 的历史 token 无法精确吊销，返回 False（调用方据此提示"请重新登录"）。
    """
    jti = payload.get("jti")
    if not jti:
        return False
    ttl = token_remaining_seconds(payload)
    if ttl <= 0:
        return True  # 已过期，不用标记也进不来
    from ..services.cache import cache

    cache.set(_REVOKE_PREFIX + jti, 1, ttl=ttl)
    return True


def is_token_revoked(payload: dict) -> bool:
    """检查 token 是否已被吊销。

    吊销表跟着缓存后端走：Redis 正常时跨进程一致；降级为内存缓存时只在单进程生效。
    查询失败时**放行并记 warning**——不能因为缓存抖动就让所有人登不上，
    但也不能静默：这条日志是唯一线索，别删。
    """
    jti = payload.get("jti")
    if not jti:
        return False
    try:
        from ..services.cache import cache

        return cache.get(_REVOKE_PREFIX + jti) is not None
    except Exception as e:  # pragma: no cover - 只在缓存后端异常时命中
        logger.warning(f"吊销检查失败，本次按未吊销处理：{e}")
        return False
