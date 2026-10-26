"""
前沿能力补齐 - 测试
================================================
- GraphRAG：图谱构建（实体/关系/社区）、图谱数据、局部/全局检索
- 推理模型：思考链解析、推理服务、RAG 推理问答
- 多 Agent：原生状态机协作（含步骤）
- 微调：SFT / DPO 数据集构建

所有 LLM / 向量调用均由 conftest.py 的内存假实现接管，不依赖真实 API。
异步方法在同步测试中通过 asyncio.run 执行。
"""
import asyncio
import io
import time

from app.database import SessionLocal
from app.models.graph_community import GraphCommunity
from app.models.graph_entity import GraphEntity
from app.models.graph_relation import GraphRelation
from app.services.finetune_data import finetune_data_service
from app.services.graph_builder import graph_builder
from app.services.graph_retriever import graph_retriever
from app.services.native_multi_agent import native_multi_agent
from app.services.reasoning_service import (
    extract_reasoning,
    needs_reasoning,
    reasoning_service,
)

# ============================================================
# 辅助函数
# ============================================================

def _create_kb(client, headers, name="前沿测试库"):
    r = client.post(
        "/api/kb", json={"name": name, "description": "测试"}, headers=headers
    )
    assert r.status_code == 200
    return r.json()["id"]


def _upload_txt(client, headers, kb_id, content, name="doc.txt"):
    r = client.post(
        f"/api/kb/{kb_id}/upload",
        files={"file": (name, io.BytesIO(content), "text/plain")},
        headers=headers,
    )
    assert r.status_code == 200
    return r.json()["id"]


def _wait(client, headers, doc_id, tries=25):
    status = None
    for _ in range(tries):
        status = client.get(f"/api/docs/{doc_id}", headers=headers).json()
        if status["status"] in ("completed", "failed"):
            return status
        time.sleep(0.2)
    return status


def _prepare_kb_with_doc(client, headers):
    """建库 + 上传一篇含 RAG 内容的文档 + 等待完成"""
    kb_id = _create_kb(client, headers)
    content = (
        "RAG 是检索增强生成技术，它依赖向量检索和知识图谱。"
        "向量检索通过相似度从知识库找资料。知识图谱用实体和关系组织知识。"
    ).encode("utf-8")
    doc_id = _upload_txt(client, headers, kb_id, content)
    assert _wait(client, headers, doc_id)["status"] == "completed"
    return kb_id


# ============================================================
# GraphRAG：图谱构建
# ============================================================

def test_graph_build(client, registered_user):
    _, headers = registered_user
    kb_id = _prepare_kb_with_doc(client, headers)

    db = SessionLocal()
    try:
        result = graph_builder.build_graph(db, kb_id)
    finally:
        db.close()

    assert result["entities"] >= 3
    assert result["relations"] >= 1
    assert result["communities"] >= 1


def test_graph_build_empty_kb(client, registered_user):
    _, headers = registered_user
    kb_id = _create_kb(client, headers, name="空库")
    db = SessionLocal()
    try:
        result = graph_builder.build_graph(db, kb_id)
    finally:
        db.close()
    assert result["entities"] == 0


def test_graph_entity_relation_persistence(client, registered_user):
    _, headers = registered_user
    kb_id = _prepare_kb_with_doc(client, headers)

    db = SessionLocal()
    try:
        graph_builder.build_graph(db, kb_id)
        entities = db.query(GraphEntity).filter(GraphEntity.kb_id == kb_id).all()
        relations = db.query(GraphRelation).filter(GraphRelation.kb_id == kb_id).all()
        communities = db.query(GraphCommunity).filter(GraphCommunity.kb_id == kb_id).all()

        # 实体字段完整
        names = {e.name for e in entities}
        assert "RAG" in names
        assert all(e.source_doc_ids for e in entities)

        # 边的两端不同、名称冗余正确
        for r in relations:
            assert r.source_entity_id != r.target_entity_id
            assert r.source_name and r.target_name

        # 社区含实体，且实体归属到社区
        assert communities
        assert communities[0].entity_count >= 1
        assert any(e.community_id is not None for e in entities)
    finally:
        db.close()


# ============================================================
# GraphRAG：API 与检索
# ============================================================

def test_graph_status_and_data_api(client, registered_user):
    _, headers = registered_user
    kb_id = _prepare_kb_with_doc(client, headers)

    # 构建前状态
    r = client.get(f"/api/graphrag/kb/{kb_id}/status", headers=headers)
    assert r.status_code == 200

    # 触发构建（后台线程）
    r = client.post(
        f"/api/graphrag/kb/{kb_id}/build", json={"doc_ids": None}, headers=headers
    )
    assert r.status_code == 200

    # 等待后台构建完成
    for _ in range(25):
        s = client.get(f"/api/graphrag/kb/{kb_id}/status", headers=headers).json()
        if s["status"] == "done":
            break
        time.sleep(0.2)

    # 图谱数据
    r = client.get(f"/api/graphrag/kb/{kb_id}/graph", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert len(data["nodes"]) >= 3
    assert len(data["edges"]) >= 1
    assert len(data["communities"]) >= 1


def test_graph_local_search(client, registered_user):
    _, headers = registered_user
    kb_id = _prepare_kb_with_doc(client, headers)

    db = SessionLocal()
    try:
        graph_builder.build_graph(db, kb_id)
    finally:
        db.close()

    result = asyncio.run(
        graph_retriever.local_search(kb_id, "RAG 依赖什么检索技术？")
    )
    assert result["answer"]
    assert len(result["entities"]) >= 1
    assert len(result["relations"]) >= 1


def test_graph_global_search(client, registered_user):
    _, headers = registered_user
    kb_id = _prepare_kb_with_doc(client, headers)

    db = SessionLocal()
    try:
        graph_builder.build_graph(db, kb_id)
    finally:
        db.close()

    result = asyncio.run(
        graph_retriever.global_search(kb_id, "总结这个知识库的主要内容")
    )
    assert result["answer"]
    assert len(result["communities"]) >= 1


# ============================================================
# 推理模型：思考链解析（纯函数）
# ============================================================

def test_extract_reasoning_with_think_tag():
    content = "<think>先分析问题，再找资料。</think>最终答案是 RAG。"
    r = extract_reasoning(content)
    assert r["reasoning"] == "先分析问题，再找资料。"
    assert r["answer"] == "最终答案是 RAG。"


def test_extract_reasoning_unclosed_think():
    r = extract_reasoning("<think>思考还在继续，没有结束标签")
    assert r["reasoning"] == "思考还在继续，没有结束标签"
    assert r["answer"] == ""


def test_extract_reasoning_no_tag():
    r = extract_reasoning("普通答案，没有思考过程")
    assert r["reasoning"] == ""
    assert r["answer"] == "普通答案，没有思考过程"


def test_extract_reasoning_empty():
    r = extract_reasoning("")
    assert r["reasoning"] == "" and r["answer"] == ""


def test_needs_reasoning():
    assert needs_reasoning("请详细分析 RAG 与 GraphRAG 的区别和优劣")
    assert needs_reasoning("为什么需要重排序？")
    # 极短且无复杂信号的问题，不强制推理
    assert not needs_reasoning("你好")


# ============================================================
# 推理模型：服务与 RAG 集成
# ============================================================

def test_reasoning_service_returns_chain():
    messages = [{"role": "user", "content": "分析 RAG 的流程"}]
    r = asyncio.run(reasoning_service.reason(messages, model="deepseek-r1"))
    assert r["answer"]
    assert r["reasoning"]


def test_rag_reasoning_chat(client, registered_user):
    _, headers = registered_user
    kb_id = _prepare_kb_with_doc(client, headers)

    from app.services.rag_service import RAGService
    rag = RAGService()
    result = asyncio.run(
        rag.reasoning_chat(kb_id, "请详细分析 RAG 的核心组件", force=True)
    )
    assert result["answer"]
    assert result["reasoned"] is True


# ============================================================
# 多 Agent：原生状态机
# ============================================================

def test_native_multi_agent_steps(client, registered_user):
    _, headers = registered_user
    kb_id = _prepare_kb_with_doc(client, headers)

    result = asyncio.run(
        native_multi_agent.run("梳理 RAG 的完整流程并说明各组件作用", kb_id)
    )
    assert result["answer"]
    assert result["backend"] == "native-multi-agent"

    # 包含四个角色的步骤
    agents = [s["agent"] for s in result["steps"]]
    assert "planner" in agents
    assert "researcher" in agents
    assert "writer" in agents
    assert "supervisor" in agents


def test_multi_agent_api(client, registered_user):
    _, headers = registered_user
    kb_id = _prepare_kb_with_doc(client, headers)

    r = client.post(
        "/api/agent/multi-agent",
        json={"question": "RAG 的流程是什么？", "kb_id": kb_id, "backend": "native"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["answer"]
    assert len(r.json()["steps"]) >= 1


# ============================================================
# 微调：数据构建
# ============================================================

def test_sft_dataset_from_golden():
    db = SessionLocal()
    try:
        dataset = finetune_data_service.build_sft_dataset(db, include_history=False)
    finally:
        db.close()
    # golden_qa 有 20 条
    assert len(dataset) >= 10
    item = dataset[0]
    assert {"messages"}.issubset(item.keys())
    roles = [m["role"] for m in item["messages"]]
    assert roles == ["system", "user", "assistant"]


def test_sft_dataset_empty_dpo():
    db = SessionLocal()
    try:
        dpo = finetune_data_service.build_dpo_dataset(db)
    finally:
        db.close()
    # 没有点赞/点踩配对，DPO 为空
    assert dpo == []


def test_finetune_preview_api(client, registered_user):
    _, headers = registered_user
    r = client.post(
        "/api/finetune/preview",
        json={"type": "sft", "kb_id": None},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["count"] >= 10
