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


def test_bm25_scores_child_but_returns_parent(tmp_path):
    """父子分块的核心契约：**打分用子块，返回用父块**。

    早期实现拿 1000 字父块建索引，词频被稀释、长度归一化被拖累，
    BM25 抓"型号/专有名词"的优势就没了；但返回又必须给父块，
    否则生成阶段只能看到半句话。所以这两个粒度不能是同一个字段。
    """
    idx = BM25Index(996, persist_dir=str(tmp_path))
    child = "退款一般在三个工作日内原路退回"
    parent = "售后总则：以下条款适用于所有渠道订单。" + child + "。如需加急请联系客服。"
    idx.add([child], 1, "售后.pdf", parents=[parent])

    r = idx.search("退款", top_k=1)
    assert r, "阈值或打分把唯一命中过滤掉了"
    assert r[0]["text"] == parent, "返回的必须是父块（上下文完整）"
    assert r[0]["child_text"] == child, "子块要保留，供精排与前端展示"


def test_bm25_parents_must_align(tmp_path):
    """parents 与 chunks 必须一一对齐：错位会让父块张冠李戴。

    语料刻意写成「查询词在两种分词粒度下都是完整词项」的形式（发票 / 开具 / 要求），
    否则 jieba 与降级分词切出来的 token 不同，用例会随环境时红时绿。
    """
    idx = BM25Index(995, persist_dir=str(tmp_path))
    idx.add(
        ["退款流程说明", "发票开具要求"],
        1,
        "混.pdf",
        parents=["父块甲（讲退款）", "父块乙（讲发票）"],
    )
    r = idx.search("发票", top_k=1)
    assert r and r[0]["text"] == "父块乙（讲发票）"


def test_bm25_never_filters_top_candidate(tmp_path, monkeypatch):
    """不变量：**头名永远不能被阈值滤掉**，无论阈值调多高。

    这是 `BM25_MIN_SCORE` 的真实坑：IDF = log(1 + (N-n+0.5)/(n+0.5)) 随语料规模下降，
    小语料里再准的命中也只有 0.2~0.3 分。若只用绝对阈值，一个 0.5 就会让 search()
    返回空列表——而空召回不会报错，整条检索链路静默退化成"只有向量路"。
    现在的门槛是 `min(绝对阈值, 头名 × 比例)`，因此头名天然留下。

    这个用例不依赖分词粒度：不管 jieba 还是降级分词，结论都一样。
    """
    from app.config import settings

    idx = BM25Index(994, persist_dir=str(tmp_path))
    idx.add(["退款流程说明"], 1, "a.pdf")

    # 把绝对阈值调到远超任何可能得分的程度：绝对阈值实现会返回空
    monkeypatch.setattr(settings, "BM25_MIN_SCORE", 999.0)
    r = idx.search("退款", top_k=1)
    assert r, "头名被阈值滤掉了：小语料下检索会静默返回空"
    assert r[0]["text"] == "退款流程说明"


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


def test_merge_orders_by_rerank_rank_not_score():
    """合并两次检索时，排序键必须是 `rerank_rank` 而不是 `score`。

    反例（曾经的实现）：向量分数落在 [0,1]、BM25 分数无上界，按 score 混排会让
    BM25 来源的片段一律压过向量来源的——不是更相关，只因为量纲大。后果是精排
    明明给出了正确顺序，却被这一行整个覆盖，**钱花了效果等于没开**。
    """
    from app.retrieval.self_rag import self_rag

    old = [
        {"text": "精排第0", "rerank_rank": 0, "score": 0.31, "fusion_score": 0.9},
        {"text": "精排第1", "rerank_rank": 1, "score": 0.88, "fusion_score": 0.8},
    ]
    new = [{"text": "后到但分数虚高", "rerank_rank": 2, "score": 9.9, "fusion_score": 0.1}]

    merged = self_rag._merge(old, new)
    assert [m["text"] for m in merged] == ["精排第0", "精排第1", "后到但分数虚高"]


def test_merge_without_rerank_is_stable():
    """关掉精排时没有 rerank_rank，应退回插入序，保证结果可复现而不是随字典序漂移。"""
    from app.retrieval.self_rag import self_rag

    a = [{"text": "甲"}, {"text": "乙"}]
    b = [{"text": "丙"}]
    assert [m["text"] for m in self_rag._merge(a, b)] == ["甲", "乙", "丙"]


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
