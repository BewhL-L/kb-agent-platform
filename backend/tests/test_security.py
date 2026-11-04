"""安全工具测试：密码哈希 + JWT + 吊销

为什么这里要专门测"吊销"：
JWT 是自包含的，**默认签发出去就收不回来**。所以"能不能吊销"不是附加功能，
而是"离职/泄露/丢设备时你有没有手段"的分界线。这条链路上任何一环退化成
"看起来能吊销、实际没生效"，都不会报错，只会静默失效——必须由测试盯住。
"""
from app.utils.security import (
    create_access_token,
    decode_token,
    hash_password,
    is_token_revoked,
    revoke_token,
    token_remaining_seconds,
    verify_password,
)


def test_password_hashing():
    h = hash_password("secret123")
    assert h != "secret123"
    assert verify_password("secret123", h)
    assert not verify_password("wrong", h)


def test_jwt_roundtrip():
    token = create_access_token({"sub": "42", "username": "alice"})
    payload = decode_token(token)
    assert payload is not None
    assert payload["sub"] == "42"
    assert payload["username"] == "alice"


def test_invalid_token():
    assert decode_token("not.a.valid.token") is None


# ===== 吊销能力 =====

def test_jwt_carries_jti_and_iat():
    """jti 是可吊销的前提，iat 是算剩余寿命的依据，两者缺一不可。"""
    payload = decode_token(create_access_token({"sub": "1"}))
    assert payload["jti"]
    assert payload["iat"]
    assert token_remaining_seconds(payload) > 0


def test_jti_unique_per_token():
    """同一个用户连签两枚 token，jti 也必须不同——否则吊销会误伤。"""
    a = decode_token(create_access_token({"sub": "1"}))["jti"]
    b = decode_token(create_access_token({"sub": "1"}))["jti"]
    assert a != b


def test_revoke_then_detected():
    payload = decode_token(create_access_token({"sub": "7"}))
    assert is_token_revoked(payload) is False
    assert revoke_token(payload) is True
    assert is_token_revoked(payload) is True


def test_revoke_without_jti_returns_false():
    """历史 token（无 jti）无法精确吊销，必须显式返回 False，不能假装成功。"""
    assert revoke_token({"sub": "1"}) is False
    assert is_token_revoked({"sub": "1"}) is False


def test_revoke_is_per_token_not_per_user():
    """吊销按 jti 精确到单枚，不能把同用户的其他设备一起踢掉。"""
    a = decode_token(create_access_token({"sub": "9"}))
    b = decode_token(create_access_token({"sub": "9"}))
    revoke_token(a)
    assert is_token_revoked(a) is True
    assert is_token_revoked(b) is False


# ===== 接口级：登出真的生效吗 =====

def test_logout_invalidates_token(client, registered_user):
    """登出后同一枚 token 必须 401——这是"能吊销"唯一的可验证证据。

    只删前端本地 token 也叫"登出"，但服务端仍然认，所以必须测服务端。
    """
    _, headers = registered_user
    assert client.get("/api/auth/me", headers=headers).status_code == 200

    assert client.post("/api/auth/logout", headers=headers).status_code == 200

    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_logout_requires_auth(client):
    assert client.post("/api/auth/logout").status_code == 401
