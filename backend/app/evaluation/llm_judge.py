"""
LLM-as-Judge（模型评审，0-1 分）
- faithfulness 事实一致性：答案是否都能被检索资料支撑（识别幻觉）
- answer_relevancy 答案相关性：答案是否切题
评审失败返回 None，不计入平均，链路不中断。
"""
import json
import re
from typing import Optional

from ..config import settings
from ..retrieval._sync_llm import sync_chat
from ..utils.logger import get_logger

logger = get_logger(__name__)

FAITH_SYSTEM = (
    "你是事实一致性评审。判断「答案」中的每条陈述是否都能被「参考资料」支撑，"
    "不能被支撑的内容属于幻觉。只输出 JSON，不要解释。"
)
REL_SYSTEM = (
    "你是相关性评审。判断「答案」是否直接回应了「问题」，没有答非所问或无关内容。"
    "只输出 JSON，不要解释。"
)


def _parse_score(raw: str) -> Optional[float]:
    if not raw:
        return None
    m = re.search(r"\{.*\}", raw, re.S)
    if m:
        try:
            d = json.loads(m.group(0))
            for k in ("score", "rating", "分数"):
                if k in d:
                    return float(d[k])
        except (json.JSONDecodeError, ValueError):
            pass
    m2 = re.search(r"[01](\.\d+)?", raw.strip())
    return float(m2.group(0)) if m2 else None


def _clamp(x: Optional[float]) -> Optional[float]:
    return None if x is None else max(0.0, min(1.0, x))


def judge_faithfulness(question: str, answer: str, retrieved: list) -> Optional[float]:
    if not settings.LLM_JUDGE_ENABLED:
        return None
    context = "\n\n".join(f"[资料{i}] {c['text']}" for i, c in enumerate(retrieved, 1))
    prompt = (
        f"问题：{question}\n参考资料：\n{context}\n答案：{answer}\n"
        f'请评估事实一致性，输出 {{"score": 0到1小数}}，1 表示答案完全由资料支撑。'
    )
    return _clamp(_parse_score(sync_chat(
        prompt, system=FAITH_SYSTEM, temperature=0.0, max_tokens=200,
        purpose="judge",
    )))


def judge_relevancy(question: str, answer: str) -> Optional[float]:
    if not settings.LLM_JUDGE_ENABLED:
        return None
    prompt = (
        f"问题：{question}\n答案：{answer}\n"
        f'请评估答案与问题的相关程度，输出 {{"score": 0到1小数}}，1 表示完全切题。'
    )
    return _clamp(_parse_score(sync_chat(
        prompt, system=REL_SYSTEM, temperature=0.0, max_tokens=200,
        purpose="judge",
    )))
