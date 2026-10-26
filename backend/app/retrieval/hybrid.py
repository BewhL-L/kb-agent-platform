"""
混合检索（Hybrid Search）
- 稠密向量路：语义相似（同义、近义、概念）
- 稀疏 BM25 路：精确词项（型号、专有名词、关键词）
- RRF（Reciprocal Rank Fusion）融合两路排序，对分数尺度不敏感，稳健
- Rerank 精排后返回 top_k
查询改写（multi_query）在融合前扩展召回。
"""
from typing import Dict, List, Optional

from ..config import settings
from ..utils.logger import get_logger
from .bm25_retriever import BM25Index
from .query_rewrite import multi_query
from .reranker import reranker

logger = get_logger(__name__)


def _key(c: Dict):
    return (c.get("document_id"), c.get("text"))


def rrf(
    rank_lists: List[List[Dict]],
    k: int = None,
    weights: Optional[List[float]] = None,
) -> List[Dict]:
    """
    Reciprocal Rank Fusion
    score(d) = Σ_list weight_list * 1 / (k + rank_list(d) + 1)
    """
    k = k or settings.RRF_K
    scores: Dict[tuple, float] = {}
    meta: Dict[tuple, Dict] = {}
    for li, lst in enumerate(rank_lists):
        w = weights[li] if weights else 1.0
        for rank, c in enumerate(lst):
            key = _key(c)
            scores[key] = scores.get(key, 0.0) + w / (k + rank + 1)
            meta.setdefault(key, c)

    ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    out = []
    for key, s in ordered:
        c = dict(meta[key])
        c["fusion_score"] = round(s, 5)
        out.append(c)
    return out


class HybridRetriever:
    """混合检索统一入口"""

    def retrieve(
        self,
        kb_id: int,
        question: str,
        top_k: int = None,
        mode: str = None,
    ) -> List[Dict]:
        top_k = top_k or settings.TOP_K
        mode = mode or settings.RETRIEVAL_MODE

        queries = multi_query(question)

        # 稠密向量路（多查询合并去重）
        from ..services.vector_store import vector_store

        vec_candidates: List[Dict] = []
        seen = set()
        for q in queries:
            for c in vector_store.query(kb_id, q, top_k=settings.FETCH_K):
                key = _key(c)
                if key not in seen:
                    seen.add(key)
                    vec_candidates.append(c)

        if mode != "hybrid":
            vec_candidates.sort(key=lambda c: c.get("score", 0), reverse=True)
            return reranker.rerank(question, vec_candidates[: settings.FETCH_K], top_k)

        # 稀疏 BM25 路（走进程内缓存，避免每次查询都解析整份索引 JSON）
        bm25 = BM25Index.load_cached(kb_id)
        bm_candidates: List[Dict] = []
        seen_b = set()
        for q in queries:
            for c in bm25.search(q, top_k=settings.FETCH_K):
                key = _key(c)
                if key not in seen_b:
                    seen_b.add(key)
                    bm_candidates.append(c)

        fused = rrf(
            [vec_candidates, bm_candidates],
            weights=[settings.VECTOR_WEIGHT, settings.BM25_WEIGHT],
        )
        return reranker.rerank(question, fused[: settings.FETCH_K], top_k)

    # ===== 索引维护钩子（由 vector_store 触发）=====

    def on_add(self, kb_id: int, chunks: List[str], document_id: int, document_name: str) -> None:
        try:
            BM25Index(kb_id).add(chunks, document_id, document_name)
        except Exception as e:
            logger.warning(f"BM25 索引更新失败：{e}")

    def on_delete_document(self, kb_id: int, document_id: int) -> None:
        try:
            BM25Index(kb_id).remove_document(document_id)
        except Exception as e:
            logger.warning(f"BM25 索引删除失败：{e}")

    def on_delete_kb(self, kb_id: int) -> None:
        try:
            BM25Index(kb_id).remove_kb()
        except Exception as e:
            logger.warning(f"BM25 索引删除失败：{e}")


hybrid_retriever = HybridRetriever()
