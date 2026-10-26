"""评测体系测试：分层指标单元 + 评测执行器端到端"""
import json

from app.evaluation import metrics as M

CASE = {
    "expected_document_names": ["售后政策.pdf"],
    "must_contain_keywords": ["退款", "工作日"],
}


# ===== 检索指标 =====

def test_hit_at_k():
    retrieved = [{"document_name": "售后政策.pdf", "text": "退款在工作日内"}]
    assert M.hit_at_k(retrieved, CASE) == 1.0


def test_hit_at_k_miss():
    retrieved = [{"document_name": "其他.pdf", "text": "无关内容"}]
    assert M.hit_at_k(retrieved, CASE) == 0.0


def test_mrr():
    retrieved = [
        {"document_name": "其他.pdf", "text": "无关"},
        {"document_name": "售后政策.pdf", "text": "退款"},
    ]
    assert M.mrr(retrieved, CASE) == 0.5


def test_average_precision():
    retrieved = [{"document_name": "售后政策.pdf", "text": "退款 工作日"}]
    assert M.average_precision(retrieved, CASE) == 1.0


def test_context_recall_full():
    retrieved = [{"document_name": "售后政策.pdf", "text": "退款 工作日 到账"}]
    assert M.context_recall(retrieved, CASE) == 1.0


def test_context_recall_partial():
    # 只命中文档，关键词缺失 -> 1/3
    retrieved = [{"document_name": "售后政策.pdf", "text": "其他内容"}]
    assert M.context_recall(retrieved, CASE) == 1 / 3


def test_no_expectations_returns_none():
    assert M.average_precision([{"text": "x"}], {}) is None
    assert M.context_recall([{"text": "x"}], {}) is None


# ===== 生成指标 =====

def test_answer_coverage_full():
    assert M.answer_keyword_coverage("退款在工作日内", CASE) == 1.0


def test_answer_coverage_partial():
    assert M.answer_keyword_coverage("退款", CASE) == 0.5


# ===== 评测执行器端到端 =====

def test_runner_end_to_end(tmp_path):
    import asyncio

    from app.services.vector_store import vector_store

    kb = 888
    vector_store.add_documents(
        kb, ["退款一般在3-7个工作日内原路退回"], 1001, "售后政策.pdf"
    )

    dataset = {
        "cases": [
            {
                "id": "t1",
                "kb_id": kb,
                "question": "退款多久到账",
                "reference_answer": "3-7个工作日",
                "must_contain_keywords": ["退款"],
                "expected_document_names": ["售后政策.pdf"],
            }
        ]
    }
    ds_path = tmp_path / "ds.json"
    ds_path.write_text(json.dumps(dataset, ensure_ascii=False), encoding="utf-8")

    from app.evaluation.runner import EvaluationRunner

    report = asyncio.run(EvaluationRunner().run(dataset_path=str(ds_path)))
    s = report["summary"]

    assert s["case_count"] == 1
    assert s["hit@k"] == 1.0          # BM25 路命中（混合检索价值）
    assert s["faithfulness"] is not None
    assert s["answer_relevancy"] is not None
    assert report.get("report_path")
