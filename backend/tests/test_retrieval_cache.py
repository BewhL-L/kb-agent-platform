"""
检索缓存测试
============
三件事必须证明：
    1. MemoryCache 的 TTL 真的生效（之前 ttl 参数是摆设）
    2. 同一问题第二次不再打向量库（命中）
    3. 文档变更后旧缓存失效（版本号 +1，旧 key 自然不命中）
"""
import io
import time


def test_memory_cache_ttl_works():
    from app.services.cache import MemoryCache

    c = MemoryCache()
    c.set("k", {"a": 1}, ttl=30)
    assert c.get("k") == {"a": 1}

    c.set("short", 1, ttl=0.05)
    time.sleep(0.12)
    assert c.get("short") is None, "TTL 到期必须取不到"


def test_version_bump_changes_key():
    from app.services.cache import MemoryCache
    from app.services.retrieval_cache import RetrievalCache

    rc = RetrievalCache(backend=MemoryCache())
    key_v0 = rc._key(1, "同一个问题")
    rc.bump(1)
    key_v1 = rc._key(1, "同一个问题")

    assert rc.version(1) == 1
    assert key_v0 != key_v1, "版本号变了，缓存 key 必须变"


def test_retrieval_cache_hit_and_invalidate(client, registered_user, monkeypatch):
    _, headers = registered_user
    kb_id = client.post("/api/kb", json={"name": "缓存测试库"}, headers=headers).json()["id"]

    content = "七天无理由退货自签收次日起计算，退款原路退回，1-3 个工作日到账。".encode("utf-8")
    resp = client.post(
        f"/api/kb/{kb_id}/upload",
        files={"file": ("policy.txt", io.BytesIO(content), "text/plain")},
        headers=headers,
    )
    doc_id = resp.json()["id"]
    for _ in range(30):
        if client.get(f"/api/docs/{doc_id}", headers=headers).json()["status"] == "completed":
            break
        time.sleep(0.2)

    from app.services.rag_service import rag_service
    from app.services.retrieval_cache import retrieval_cache
    from app.services.vector_store import vector_store

    calls = {"n": 0}
    # 计数点选 `_embed` 而不是 `query`：
    # 一是"有没有真的进向量路"这件事的唯一必经点是 embedding（无论是 query 还是
    # query_batch 都要先算向量）；二是 `query` 只是其中一种实现——多查询改写改走
    # 一次批量 `query_batch` 之后，继续数 `query` 会永远得到 0，
    # 测试会以"缓存永远命中"的姿态假通过。
    original_embed = vector_store._embed

    def counting_embed(texts):
        calls["n"] += 1
        return original_embed(texts)

    monkeypatch.setattr(vector_store, "_embed", counting_embed)

    question = "退货从哪天开始算？"
    first = rag_service.retrieve(kb_id, question)
    calls_after_first = calls["n"]
    assert calls_after_first > 0
    assert first, "首次检索必须有结果"

    second = rag_service.retrieve(kb_id, question)
    assert calls["n"] == calls_after_first, "第二次应命中缓存，不再查向量库"
    assert [c.get("text") for c in second] == [c.get("text") for c in first]

    # 模拟文档变更（真实链路由 document_service 在增删改时 bump）
    retrieval_cache.bump(kb_id)
    rag_service.retrieve(kb_id, question)
    assert calls["n"] > calls_after_first, "版本号变了必须穿透缓存"
