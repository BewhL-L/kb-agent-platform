"""
Prompt 版本记录测试
==================
Prompt 是代码资产：改了就得升版本，并且要能在成本表里按版本聚合。
这里验证「调用 -> usage 记录 -> prompt_version 落库」这条链路是通的。
"""
from app.database import SessionLocal
from app.models import LLMUsage
from app.prompts.system import AGENT_SYSTEM, RAG_SYSTEM
from app.services.usage_service import usage_service


def test_prompt_ref_format():
    assert RAG_SYSTEM.ref == f"{RAG_SYSTEM.name}@{RAG_SYSTEM.version}"
    assert RAG_SYSTEM.name == "rag_system"
    assert "{context}" in RAG_SYSTEM.template, "RAG Prompt 必须保留上下文占位符"
    assert AGENT_SYSTEM.name == "agent_system"


def test_usage_records_prompt_version(client):
    db = SessionLocal()
    try:
        usage_service.record_usage(
            db,
            model="test-model",
            prompt_tokens=10,
            completion_tokens=5,
            purpose="chat",
            prompt_version=RAG_SYSTEM.ref,
        )
        row = db.query(LLMUsage).order_by(LLMUsage.id.desc()).first()
        assert row is not None
        assert row.prompt_version == RAG_SYSTEM.ref
        assert row.total_tokens == 15
    finally:
        db.close()
