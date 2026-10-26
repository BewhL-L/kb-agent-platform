"""
检索质量回归测试（评测进 CI 的最小实现）
========================================
目的：把"评测驱动"从口号变成门槛——任何人改动切片、检索、Rerank，
只要 Hit@3 掉下阈值，CI 就红。

为什么不用 golden_qa.json：
    那 20 条绑定真实知识库 id 和真实文档名，CI 里没有语料。
    这里用 4 份可控的小语料 + 4 条问题，验证的是**链路**而不是业务内容。

真实评测（含 LLM 裁判）仍然走 `python -m app.evaluation.run_eval`。
"""
import io
import time

from app.evaluation import metrics as M

DOCS = {
    "售后政策.txt": (
        "七天无理由退货自签收次日起计算。商品有质量问题时退货运费由商家承担，"
        "无理由退货运费由买家承担。退款原路退回，一般 1-3 个工作日到账。"
    ),
    "物流时效.txt": (
        "普通地区下单后 48 小时内发货，偏远地区发货时间顺延 3 到 5 天。"
        "快递默认发顺丰，支持自提点自取。"
    ),
    "人事制度.txt": (
        "员工年假按工龄计算，满一年 5 天。年假可以分次使用，也可以申请调休。"
        "病假需要提供医院证明并走审批流程。"
    ),
    "财务报销.txt": (
        "差旅住宿标准：一线城市每晚不超过 600 元，其他城市不超过 400 元。"
        "报销必须提供增值税发票，发票抬头需与公司名称一致。"
    ),
}

CASES = [
    ("七天无理由退货从哪天开始算？", "售后政策.txt"),
    ("偏远地区发货要多久？", "物流时效.txt"),
    ("年假可以调休吗？", "人事制度.txt"),
    ("差旅住宿报销标准是多少？", "财务报销.txt"),
]


def _wait(client, headers, doc_id, tries=30):
    for _ in range(tries):
        data = client.get(f"/api/docs/{doc_id}", headers=headers).json()
        if data["status"] in ("completed", "failed"):
            return data["status"]
        time.sleep(0.2)
    return "timeout"


def test_retrieval_hit_rate_does_not_regress(client, registered_user):
    _, headers = registered_user
    kb_id = client.post("/api/kb", json={"name": "评测回归库"}, headers=headers).json()["id"]

    for name, text in DOCS.items():
        resp = client.post(
            f"/api/kb/{kb_id}/upload",
            files={"file": (name, io.BytesIO(text.encode("utf-8")), "text/plain")},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert _wait(client, headers, resp.json()["id"]) == "completed"

    from app.services.rag_service import rag_service

    hits, ranks = [], []
    for question, expected_doc in CASES:
        case = {"expected_document_names": [expected_doc]}
        retrieved = rag_service.retrieve(kb_id, question, top_k=5)
        assert retrieved, f"检索为空：{question}"
        hits.append(M.hit_at_k(retrieved, case, k=3))
        ranks.append(M.mrr(retrieved, case))

    hit3 = sum(hits) / len(hits)
    mrr = sum(ranks) / len(ranks)

    print(f"\n[检索回归] Hit@3={hit3:.2f}  MRR={mrr:.2f}")
    # 阈值按当前实现定：改动检索链路时，先看这个数字有没有掉
    # Hit@3 是主门槛：只要期望文档还在前三，检索链路就是通的。
    # MRR 在假 embedding 下抖动较大（向量是词袋哈希，不是真语义），只做兜底。
    assert hit3 >= 0.75, f"Hit@3 退化：{hit3:.2f}（期望 >= 0.75）"
    assert mrr >= 0.45, f"MRR 异常：{mrr:.2f}（期望 >= 0.45）"
