"""检索增强与上下文工程模块测试（不依赖真实 API）"""

from app.context_engine.assembler import ContextAssembler, estimate_tokens
from app.context_engine.compressor import compress_history
from app.context_engine.memory import LongTermMemory, ShortTermMemory
from app.retrieval.bm25_retriever import BM25Index
from app.retrieval.hybrid import rrf
from app.retrieval.query_rewrite import multi_query
from app.retrieval.reranker import llm_rerank
from app.retrieval.tokenizer import tokenize

# ===== 分词 =====

def test_tokenizer_chinese():
    t = tokenize("退款政策")
    assert isinstance(t, list) and t


def test_tokenizer_english():
    t = tokenize("refund policy document")
    assert "refund" in t


# ===== BM25 =====

def test_bm25_search(tmp_path):
    idx = BM25Index(999, persist_dir=str(tmp_path))
    idx.add(["退款一般在三个工作日内原路退回", "商品整机保修一年"], 1, "售后政策.pdf")
    r = idx.search("退款多久退回", top_k=2)
    assert r and "退款" in r[0]["text"]


def test_bm25_remove(tmp_path):
    idx = BM25Index(998, persist_dir=str(tmp_path))
    idx.add(["测试内容数据片段"], 1, "a.txt")
    idx.remove_document(1)
    assert idx.search("测试") == []


def test_bm25_persist_reload(tmp_path):
    idx = BM25Index(997, persist_dir=str(tmp_path))
    idx.add(["退款工作日到账"], 1, "a.pdf")
    reloaded = BM25Index(997, persist_dir=str(tmp_path))
    assert reloaded.search("退款")


# ===== 查询改写 =====

def test_multi_query_keeps_original():
    qs = multi_query("退款多久", count=2)
    assert qs[0] == "退款多久"
    assert len(qs) >= 2


# ===== Rerank =====

def test_llm_rerank():
    cands = [
        {"text": "退款内容", "document_name": "a", "document_id": 1},
        {"text": "无关内容", "document_name": "b", "document_id": 2},
    ]
    r = llm_rerank("退款", cands, 2)
    assert len(r) == 2
    assert r[0]["rerank_rank"] == 0


# ===== RRF =====

def test_rrf_fusion():
    a = [{"text": "x", "document_id": 1}]
    b = [
        {"text": "x", "document_id": 1},
        {"text": "y", "document_id": 2},
    ]
    r = rrf([a, b], weights=[0.6, 0.4])
    assert r[0]["text"] == "x"
    assert len(r) == 2


# ===== 记忆 =====

def test_short_memory_window():
    m = ShortTermMemory(max_turns=2)
    for i in range(8):
        m.add("user", f"内容{i}")
    assert len(m.get()) <= 4


def test_long_memory(tmp_path):
    m = LongTermMemory(str(tmp_path / "m.json"))
    m.add_fact("u1", "用户偏好简洁回答")
    assert "用户偏好简洁回答" in m.facts("u1")
    assert m.search("u1", "偏好")
    # 去重
    m.add_fact("u1", "用户偏好简洁回答")
    assert len(m.facts("u1")) == 1


# ===== 历史压缩 =====

def test_compress_history():
    msgs = [{"role": "user", "content": f"问题{i}"} for i in range(20)]
    out = compress_history(msgs, keep_turns=2)
    assert out[0]["role"] == "system"
    assert "摘要" in out[0]["content"]
    assert len(out) == 5  # 1 摘要 + 4 最近消息


def test_compress_short_unchanged():
    msgs = [{"role": "user", "content": "短对话"}]
    assert compress_history(msgs, keep_turns=2) == msgs


# ===== 组装 =====

def test_estimate_tokens():
    assert estimate_tokens("退款") >= 1
    assert estimate_tokens("refund") >= 1


def test_assemble_basic():
    a = ContextAssembler()
    msgs, kept = a.assemble(
        "系统：{context}", "问题",
        retrieved=[{"text": "资料内容", "document_name": "d", "document_id": 1}],
    )
    assert msgs[0]["role"] == "system"
    assert "资料内容" in msgs[0]["content"]
    assert msgs[-1]["content"] == "问题"


def test_select_tools_budget():
    tools = [{"function": {"name": f"tool_{i}"}} for i in range(15)]
    a = ContextAssembler()
    assert len(a.select_tools(tools, budget=5)) == 5


def test_select_tools_priority():
    tools = [
        {"function": {"name": "unrelated_thing"}},
        {"function": {"name": "search_knowledge_base"}},
    ]
    a = ContextAssembler()
    kept = a.select_tools(tools, budget=1)
    assert kept[0]["function"]["name"] == "search_knowledge_base"
