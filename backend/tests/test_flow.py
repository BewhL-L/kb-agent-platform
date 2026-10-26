"""完整业务流程测试：注册登录 -> 建库 -> 上传 -> 问答 -> 嵌入 -> 增量更新"""
import io
import time


def _create_kb(client, headers, name="测试知识库"):
    r = client.post(
        "/api/kb", json={"name": name, "description": "测试用"}, headers=headers
    )
    assert r.status_code == 200
    return r.json()["id"]


def _wait_processing(client, headers, doc_id, tries=25):
    status = None
    for _ in range(tries):
        status = client.get(f"/api/docs/{doc_id}", headers=headers).json()
        if status["status"] in ("completed", "failed"):
            break
        time.sleep(0.2)
    return status


def test_full_rag_and_agent_flow(client, registered_user):
    _, headers = registered_user
    kb_id = _create_kb(client, headers)

    # 上传文档
    content = "我们的退货政策：七天无理由退货，质量问题免运费，无理由退货运费自理。".encode("utf-8")
    r = client.post(
        f"/api/kb/{kb_id}/upload",
        files={"file": ("policy.txt", io.BytesIO(content), "text/plain")},
        headers=headers,
    )
    assert r.status_code == 200
    doc_id = r.json()["id"]

    # 等待后台处理完成
    status = _wait_processing(client, headers, doc_id)
    assert status["status"] == "completed"
    assert status["chunk_count"] >= 1

    # 文档列表
    lst = client.get(f"/api/kb/{kb_id}/docs", headers=headers).json()
    assert lst["total"] == 1

    # 朴素 RAG 问答
    r = client.post(
        "/api/chat",
        json={"kb_id": kb_id, "question": "退货政策是什么？"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["answer"]

    # Agentic RAG 问答
    r = client.post(
        "/api/chat",
        json={"kb_id": kb_id, "question": "质量问题退货免运费吗？", "use_agent": True},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["answer"]


def test_embed_public_flow(client, registered_user):
    _, headers = registered_user
    kb_id = _create_kb(client, headers)

    # 获取嵌入代码
    r = client.get(f"/api/kb/{kb_id}/embed-code", headers=headers).json()
    code = r["embed_code"]
    assert "iframe" in r["iframe_code"]

    # 公开嵌入页面（免登录）
    page = client.get(f"/embed/{code}")
    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]

    # 公开问答（免登录）
    r = client.post(f"/embed/{code}/chat", json={"question": "你好", "history": []})
    assert r.status_code == 200
    assert "answer" in r.json()

    # 无效嵌入码
    assert client.get("/embed/invalidcode123").status_code == 404


def test_incremental_update(client, registered_user):
    _, headers = registered_user
    kb_id = _create_kb(client, headers)

    v1 = "第一版：产品保修期为一年。".encode("utf-8")
    r = client.post(
        f"/api/kb/{kb_id}/upload",
        files={"file": ("v1.txt", io.BytesIO(v1), "text/plain")},
        headers=headers,
    )
    doc_id = r.json()["id"]
    assert _wait_processing(client, headers, doc_id)["status"] == "completed"

    # 增量更新（同 ID 替换）
    v2 = "第二版：产品保修期延长为两年，自购买之日起算。".encode("utf-8")
    r = client.put(
        f"/api/docs/{doc_id}",
        files={"file": ("v2.txt", io.BytesIO(v2), "text/plain")},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "processing"

    # 等待重新处理完成
    status = _wait_processing(client, headers, doc_id)
    assert status["status"] == "completed"


def test_reject_invalid_file_type(client, registered_user):
    _, headers = registered_user
    kb_id = _create_kb(client, headers)
    r = client.post(
        f"/api/kb/{kb_id}/upload",
        files={"file": ("malware.exe", io.BytesIO(b"xxxx"), "application/octet-stream")},
        headers=headers,
    )
    assert r.status_code == 400
