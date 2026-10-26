"""
答案溯源校验（Citation / Grounding Verification）
================================================
解决的问题：RAG 最危险的失败不是"答不出"，而是**答得很顺但没依据**。
本模块给答案的每个句子打分：这句话能在检索到的片段里找到多少依据。

为什么不用 LLM 裁判：
- 每次问答再调一次模型，成本和延迟都翻倍；
- 结果不可复现，无法进 CI。
所以这里用**字符二元组覆盖率**做确定性校验：零成本、可复现、能进回归测试。
代价是对"大幅改写"的句子偏保守（可能误判为无依据），所以它是**提示**而不是**判决**。

契约：
    verify(answer, sources) -> {
        checked: bool,           # 没有资料/没有句子时为 False，调用方不要据此告警
        coverage: float | None,  # 有依据的句子占比
        supported: [str],
        unsupported: [str],
        citations: [{sentence, score, source_index}],
        low_coverage: bool,      # coverage < GROUNDING_MIN_COVERAGE
    }
"""
import re
from typing import Dict, List, Optional

from ..config import settings
from ..utils.logger import get_logger

logger = get_logger(__name__)

# 中英文句末标点 + 换行都视为句子边界
_SENT_SPLIT = re.compile(r"[。！？!?；;\n]+")
# 只保留"实义字符"（中文、字母、数字），标点/空白/markdown 符号全部去掉。
# 用 \w 的反集而不是逐个列标点：中文标点、全角符号、代码块符号一网打尽，也不会写错转义。
_STRIP = re.compile(r"[^\w]+", re.UNICODE)


def _clean(text: str) -> str:
    return _STRIP.sub("", text or "")


def _bigrams(text: str) -> set:
    cleaned = _clean(text)
    if len(cleaned) < 2:
        return {cleaned} if cleaned else set()
    return {cleaned[i:i + 2] for i in range(len(cleaned) - 1)}


def split_sentences(answer: str) -> List[str]:
    """切句并丢掉过短的片段（"好的""以上"这类不承载事实）"""
    parts = [p.strip() for p in _SENT_SPLIT.split(answer or "")]
    return [p for p in parts if len(_clean(p)) >= 6]


def _containment(sent_grams: set, source_grams: set) -> float:
    """句子有多少比例的二元组出现在该来源里（0-1）"""
    if not sent_grams:
        return 0.0
    return len(sent_grams & source_grams) / len(sent_grams)


class GroundingService:
    def verify(
        self,
        answer: str,
        sources: List[Dict],
        threshold: Optional[float] = None,
    ) -> Dict:
        threshold = (
            settings.GROUNDING_SENTENCE_THRESHOLD if threshold is None else threshold
        )
        sentences = split_sentences(answer)

        if not sources:
            return {
                "checked": False,
                "coverage": None,
                "threshold": threshold,
                "supported": [],
                "unsupported": sentences,
                "citations": [],
                "low_coverage": False,
                "reason": "no_sources",
            }
        if not sentences:
            return {
                "checked": False,
                "coverage": None,
                "threshold": threshold,
                "supported": [],
                "unsupported": [],
                "citations": [],
                "low_coverage": False,
                "reason": "no_sentences",
            }

        source_grams = [_bigrams(s.get("text", "")) for s in sources]
        supported: List[str] = []
        unsupported: List[str] = []
        citations: List[Dict] = []

        for sentence in sentences:
            grams = _bigrams(sentence)
            scores = [_containment(grams, sg) for sg in source_grams]
            best = max(scores) if scores else 0.0
            best_idx = scores.index(best) if scores else -1
            ok = best >= threshold
            (supported if ok else unsupported).append(sentence)
            citations.append({
                "sentence": sentence,
                "score": round(best, 3),
                "source_index": best_idx if ok else None,
            })

        coverage = len(supported) / len(sentences)
        return {
            "checked": True,
            "coverage": round(coverage, 3),
            "threshold": threshold,
            "supported": supported,
            "unsupported": unsupported,
            "citations": citations,
            "low_coverage": coverage < settings.GROUNDING_MIN_COVERAGE,
        }


grounding_service = GroundingService()
