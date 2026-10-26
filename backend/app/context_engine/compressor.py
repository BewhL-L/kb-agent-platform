"""
对话历史压缩
- 保留最近 keep_turns 轮原始消息
- 更早的历史用 LLM 压成一条摘要（保留关键事实 / 用户偏好 / 待办）
压缩失败时安全返回原始历史。
"""
from typing import Dict, List

from ..config import settings
from ..retrieval._sync_llm import sync_chat
from ..utils.logger import get_logger

logger = get_logger(__name__)

SUMMARY_SYSTEM = (
    "你是对话历史压缩助手。请把给定的早期对话压缩成简洁摘要，"
    "保留关键事实、用户偏好、重要结论和待办事项，使用第三人称，不要丢失重要信息。"
)


def compress_history(messages: List[Dict], keep_turns: int = None) -> List[Dict]:
    keep_turns = keep_turns or settings.HISTORY_KEEP_TURNS
    keep_msgs = keep_turns * 2

    if not settings.HISTORY_COMPRESS_ENABLED or len(messages) <= keep_msgs:
        return messages

    older = messages[:-keep_msgs]
    recent = messages[-keep_msgs:]
    convo = "\n".join(f"{m['role']}: {m['content']}" for m in older)

    summary = sync_chat(
        f"请压缩以下对话历史：\n{convo}",
        system=SUMMARY_SYSTEM,
        temperature=0.1,
        max_tokens=500,
    ).strip()

    if not summary:
        return messages
    return [{"role": "system", "content": f"【早期对话摘要】\n{summary}"}] + recent
