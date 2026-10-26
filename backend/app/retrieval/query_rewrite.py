"""
查询改写（Query Rewrite）
- multi_query：生成多个不同表述/角度的查询，缓解 Query-Doc 词汇不匹配
- hyde：先生成假想答案（HyDE），用其做语义检索，适合问题很短/口语化场景
任一环节失败都安全降级为原始问题。
"""
import json
import re
from typing import List

from ..config import settings
from ..utils.logger import get_logger
from ._sync_llm import sync_chat

logger = get_logger(__name__)

MULTI_QUERY_SYSTEM = (
    "你是检索查询改写助手。针对用户的原始问题，生成若干语义等价但表述、角度不同的检索查询，"
    "用于提升知识库召回率。只输出 JSON 字符串数组，不要输出解释。"
)

HYDE_SYSTEM = (
    "你是知识库检索助手。请针对用户问题，模仿相关文档可能的口吻，写出一段简短的假设性内容"
    "（3-4 句，无需保证真实），用于语义检索。"
)


def _extract_json_array(raw: str) -> List[str]:
    if not raw:
        return []
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
        return [str(x).strip() for x in data if str(x).strip()] if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def multi_query(question: str, count: int = None) -> List[str]:
    """返回 [原始问题, 改写1, 改写2 ...]，已去重"""
    count = count or settings.MULTI_QUERY_COUNT
    if not settings.QUERY_REWRITE_ENABLED:
        return [question]

    prompt = (
        f"原始问题：{question}\n"
        f"请生成 {count} 个不同表述的检索查询（可换同义词、换角度、补全上下文），"
        f'输出 JSON 数组，例如 ["查询1", "查询2"]，不要输出其他内容。'
    )
    raw = sync_chat(
        prompt, system=MULTI_QUERY_SYSTEM, temperature=0.4, max_tokens=400,
        purpose="rewrite",
    )
    rewritten = _extract_json_array(raw)

    result: List[str] = []
    for q in [question] + rewritten:
        if q not in result:
            result.append(q)
    return result[: count + 1]


def hyde(question: str) -> str:
    """返回用于检索的假想文档；关闭或失败时返回原问题"""
    if not settings.HYDE_ENABLED:
        return question
    doc = sync_chat(
        question, system=HYDE_SYSTEM, temperature=0.5, max_tokens=300,
        purpose="rewrite",
    )
    doc = doc.strip()
    return doc or question
