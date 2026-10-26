"""
Rerank 精排
- LLM Rerank（默认）：让对话模型对候选按相关度重新排序，零额外服务
- Cohere Rerank（可选）：调用 Cohere 多语言 Rerank API，效果更稳
解析失败/服务异常时保持原顺序，链路不中断。
"""
import json
import re
from typing import Dict, List

from ..config import settings
from ..utils.logger import get_logger
from ._sync_llm import sync_chat

logger = get_logger(__name__)

RERANK_SYSTEM = (
    "你是检索精排助手。请根据「查询」与每个候选段落的相关程度，对候选重新排序，"
    "最相关的排在最前。只输出 JSON，不要解释。"
)


def _parse_order(raw: str, n: int) -> List[int]:
    if not raw:
        return list(range(n))
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return list(range(n))
    try:
        data = json.loads(m.group(0))
        order = data.get("order", [])
        return [int(x) for x in order]
    except (json.JSONDecodeError, ValueError, AttributeError):
        return list(range(n))


def llm_rerank(query: str, candidates: List[Dict], top_n: int) -> List[Dict]:
    listing = "\n".join(f"[{i}] {c['text']}" for i, c in enumerate(candidates))
    prompt = (
        f"查询：{query}\n候选段落：\n{listing}\n"
        f'请按相关度从高到低排序，输出 JSON 对象 {{"order": [编号...]}}，只输出 JSON。'
    )
    raw = sync_chat(
        prompt, system=RERANK_SYSTEM, temperature=0.0, max_tokens=300,
        purpose="rerank",
    )
    order = _parse_order(raw, len(candidates))

    ranked: List[Dict] = []
    used = set()
    for i in order:
        if 0 <= i < len(candidates) and i not in used:
            c = dict(candidates[i])
            c["rerank_rank"] = len(ranked)
            ranked.append(c)
            used.add(i)
    # 解析遗漏的候选补到末尾，避免丢失
    for i, c in enumerate(candidates):
        if i not in used and len(ranked) < top_n:
            cc = dict(c)
            cc["rerank_rank"] = len(ranked)
            ranked.append(cc)
    return ranked[:top_n]


class Reranker:
    """精排统一入口"""

    def rerank(self, query: str, candidates: List[Dict], top_n: int = None) -> List[Dict]:
        top_n = top_n or settings.RERANK_TOP_N
        if not candidates:
            return []
        if not settings.RERANK_ENABLED:
            return candidates[:top_n]
        if settings.RERANK_PROVIDER == "cohere":
            try:
                return self._cohere(query, candidates, top_n)
            except Exception as e:
                logger.warning(f"Cohere Rerank 失败，降级 LLM Rerank：{e}")
        return llm_rerank(query, candidates, top_n)

    def _cohere(self, query: str, candidates: List[Dict], top_n: int) -> List[Dict]:
        import cohere

        co = cohere.Client(settings.COHERE_API_KEY)
        docs = [c["text"] for c in candidates]
        r = co.rerank(
            model="rerank-multilingual-v3.0",
            query=query,
            documents=docs,
            top_n=top_n,
        )
        out: List[Dict] = []
        for rank, item in enumerate(r.results):
            c = dict(candidates[item.index])
            c["rerank_rank"] = rank
            out.append(c)
        return out


reranker = Reranker()
