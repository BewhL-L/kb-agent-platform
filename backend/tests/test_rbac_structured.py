"""
RBAC 与结构化回答的接口测试
===========================
覆盖三件事：
1. 邀请成员后，被邀请人能看到共享知识库（列表口径改了，必须有回归测试）
2. viewer 不能邀请他人、不能上传（越权要 403）
3. 模型输出不是合法 JSON 时，结构化接口降级而不是 500

写法参考：每个测试都用 `client` fixture 拿一套干净的表（conftest 里已做隔离）。
"""


def _register(client, username: str, password: str = "Test1234") -> dict:
    """注册第二个用户，返回认证头"""
    payload = {"username": username, "email": f"{username}@example.com", "password": password}
    client.post("/api/auth/register", json=payload)
    token = client.post("/api/auth/login", json=payload).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _create_kb(client, headers, name: str = "测试库") -> int:
    resp = client.post("/api/kb", json={"name": name}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_owner_can_invite_and_see_member(client, registered_user):
    _, owner_headers = registered_user
    kb_id = _create_kb(client, owner_headers)
    _register(client, "teammate")

    resp = client.post(
        f"/api/kb/{kb_id}/members",
        json={"username": "teammate", "role": "viewer"},
        headers=owner_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "viewer"

    listing = client.get(f"/api/kb/{kb_id}/members", headers=owner_headers).json()
    assert listing["my_role"] == "owner"
    roles = {item["username"]: item["role"] for item in listing["items"]}
    assert roles == {"testuser": "owner", "teammate": "viewer"}


def test_shared_kb_shows_up_in_member_list(client, registered_user):
    _, owner_headers = registered_user
    kb_id = _create_kb(client, owner_headers, name="共享给同事的库")
    teammate_headers = _register(client, "teammate2")

    # 邀请前：同事看不到
    before = client.get("/api/kb", headers=teammate_headers).json()
    assert before["total"] == 0

    client.post(
        f"/api/kb/{kb_id}/members",
        json={"username": "teammate2", "role": "editor"},
        headers=owner_headers,
    )

    after = client.get("/api/kb", headers=teammate_headers).json()
    assert after["total"] == 1
    assert after["items"][0]["role"] == "editor"


def test_viewer_cannot_invite_or_upload(client, registered_user):
    _, owner_headers = registered_user
    kb_id = _create_kb(client, owner_headers)
    viewer_headers = _register(client, "viewer1")
    client.post(
        f"/api/kb/{kb_id}/members",
        json={"username": "viewer1", "role": "viewer"},
        headers=owner_headers,
    )

    # 越权邀请 -> 403
    resp = client.post(
        f"/api/kb/{kb_id}/members",
        json={"username": "testuser", "role": "viewer"},
        headers=viewer_headers,
    )
    assert resp.status_code == 403

    # 越权上传 -> 403（不校验文件内容，权限先拦）
    resp = client.post(
        f"/api/kb/{kb_id}/upload",
        files={"file": ("a.txt", b"hello", "text/plain")},
        headers=viewer_headers,
    )
    assert resp.status_code == 403


def test_viewer_can_read_docs_and_chat(client, registered_user):
    _, owner_headers = registered_user
    kb_id = _create_kb(client, owner_headers)
    viewer_headers = _register(client, "viewer2")
    client.post(
        f"/api/kb/{kb_id}/members",
        json={"username": "viewer2", "role": "viewer"},
        headers=owner_headers,
    )

    assert client.get(f"/api/kb/{kb_id}/docs", headers=viewer_headers).status_code == 200
    resp = client.post(
        "/api/chat",
        json={"kb_id": kb_id, "question": "你好", "use_agent": False},
        headers=viewer_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["answer"]


def test_structured_endpoint_degrades_on_bad_json(client, registered_user):
    """conftest 的假模型只会返回普通文本，正好用来验证降级分支"""
    _, headers = registered_user
    resp = client.post(
        "/api/structured/generate",
        json={"question": "对比一下 A 和 B", "template": "comparison"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["degraded"] is True
    assert body["result"]["bullets"], "降级后必须至少有一条内容"


def _a2a_payload() -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "message/send",
        "params": {"message": {"parts": [{"text": "hi"}], "metadata": {"kb_id": 1}}},
    }


def test_a2a_disabled_returns_jsonrpc_error(client, monkeypatch):
    """默认关闭：连鉴权都不进，直接回 JSON-RPC 错误"""
    from app.config import settings

    monkeypatch.setattr(settings, "A2A_ENABLED", False)
    resp = client.post("/a2a/", json=_a2a_payload())
    assert resp.status_code == 200
    assert resp.json()["error"]["code"] == -32601


def test_a2a_requires_token(client, monkeypatch):
    """打开但未配置 Token：必须拒绝，不能默默放行"""
    from app.config import settings

    monkeypatch.setattr(settings, "A2A_ENABLED", True)
    monkeypatch.setattr(settings, "A2A_TOKEN", "")
    resp = client.post("/a2a/", json=_a2a_payload())
    assert resp.status_code == 503


def test_a2a_rejects_wrong_token(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "A2A_ENABLED", True)
    monkeypatch.setattr(settings, "A2A_TOKEN", "right-token")
    resp = client.post(
        "/a2a/",
        json=_a2a_payload(),
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert resp.status_code == 401
