"""
溯源校验 + 拒答指标的单元测试
==============================
这两块是「幻觉治理」的两面：
    - citation：答案有没有依据（句子级）
    - refusal：该拒答时有没有拒、不该拒时有没有乱拒（用例级）
"""
import io
import time

from app.evaluation import metrics as M
from app.services.grounding_service import grounding_service

SOURCES = [{
    "document_name": "售后政策.txt",
    "text": "七天无理由退货自签收次日起计算，退货运费由买家承担。",
}]


# ============ 溯源校验 ============

def test_verbatim_sentence_is_supported():
    result = grounding_service.verify("七天无理由退货自签收次日起计算。", SOURCES)
    assert result["checked"] is True
    assert result["coverage"] == 1.0
    assert result["citations"][0]["source_index"] == 0
    assert result["low_coverage"] is False


def test_unrelated_sentence_is_unsupported():
    result = grounding_service.verify("公司为员工提供免费午餐和班车。", SOURCES)
    assert result["checked"] is True
    assert result["coverage"] == 0.0
    assert result["unsupported"], "无依据的句子必须被标出来"
    assert result["low_coverage"] is True


def test_mixed_answer_reports_partial_coverage():
    answer = "七天无理由退货自签收次日起计算。另外公司提供免费午餐。"
    result = grounding_service.verify(answer, SOURCES)
    assert 0 < result["coverage"] < 1
    assert len(result["supported"]) == 1
    assert len(result["unsupported"]) == 1


def test_no_sources_means_not_checked():
    """没有检索结果时不能判"幻觉"，只能不检查"""
    result = grounding_service.verify("任何一句话都可以。", [])
    assert result["checked"] is False
    assert result["coverage"] is None


def test_short_fragments_are_ignored():
    result = grounding_service.verify("好的。以上。", SOURCES)
    assert result["checked"] is False
    assert result["reason"] == "no_sentences"


def test_chat_api_returns_grounding(client, registered_user):
    _, headers = registered_user
    kb_id = client.post("/api/kb", json={"name": "溯源校验库"}, headers=headers).json()["id"]

    content = "七天无理由退货自签收次日起计算，退货运费由买家承担。".encode("utf-8")
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

    resp = client.post(
        "/api/chat",
        json={"kb_id": kb_id, "question": "退货从哪天开始算？"},
        headers=headers,
    )
    assert resp.status_code == 200
    grounding = resp.json()["grounding"]
    assert grounding is not None
    assert grounding["checked"] is True
    assert 0.0 <= grounding["coverage"] <= 1.0


# ============ 拒答指标 ============

def test_should_refuse_reads_category_and_explicit_field():
    assert M.should_refuse({"category": "拒答-超纲"}) is True
    assert M.should_refuse({"category": "售后-退款"}) is False
    assert M.should_refuse({"should_refuse": True, "category": "其他"}) is True


def test_refusal_detection_patterns():
    assert M.is_refusal_answer("根据现有知识库资料，暂时无法回答该问题。") is True
    assert M.is_refusal_answer("退款一般 1-3 个工作日到账。") is False


def test_refusal_summary_rates():
    rows = [
        {"should_refuse": True, "refused": True},
        {"should_refuse": True, "refused": False},
        {"should_refuse": False, "refused": False},
        {"should_refuse": False, "refused": True},
    ]
    summary = M.refusal_summary(rows)
    assert summary["refusal_recall"] == 0.5
    assert summary["false_refusal_rate"] == 0.5
    assert summary["should_refuse_cases"] == 2
    assert summary["refused_cases"] == 2
