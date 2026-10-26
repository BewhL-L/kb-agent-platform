"""
长期记忆服务（上下文工程）
- 短期记忆：最近 N 轮对话原文（精确但占用 token）
- 长期记忆：更早的对话用 LLM 压缩成摘要（省 token，保留关键信息）
- 每次回答时组合：长期摘要 + 最近 N 轮原文

记忆分层：
    [ 长期记忆：压缩摘要 ]  [ 短期记忆：最近 N 轮原文 ]  [ 当前问题 ]
"""
from typing import Optional

from sqlalchemy.orm import Session

from ..config import settings
from ..models.conversation import Conversation
from ..models.message import Message
from ..utils.logger import get_logger

logger = get_logger(__name__)


# 压缩摘要的 prompt
COMPRESS_SYSTEM = """你是一个对话记忆整理专家。你的任务是把对话历史压缩成简洁的摘要，保留对后续问答有用的关键信息。"""

COMPRESS_PROMPT = """请把以下对话内容压缩成摘要。

【已有摘要】
{existing_summary}

【需要补充的对话】
{new_dialogue}

要求：
1. 保留用户提到的关键事实、偏好、问题主题和已经给出的结论
2. 去掉寒暄、重复、无关细节
3. 把新对话的信息合并进已有摘要，输出更新后的完整摘要
4. 摘要控制在 300 字以内，用要点形式
5. 如果没有有价值的信息，直接输出已有摘要
"""


class MemoryService:
    """长期记忆服务"""

    def update_memory(self, db: Session, conversation: Conversation) -> str:
        """
        检查对话消息，把短期窗口之外的新消息压缩进长期记忆。
        返回更新后的长期摘要。
        """
        if not settings.MEMORY_ENABLED:
            return ""

        # 短期窗口保留的消息条数（N 轮 = 2N 条）
        keep_count = settings.HISTORY_KEEP_TURNS * 2

        all_messages = (
            db.query(Message)
            .filter(Message.conversation_id == conversation.id)
            .order_by(Message.id.asc())
            .all()
        )
        if len(all_messages) <= keep_count:
            return conversation.long_memory or ""

        # 窗口外的消息中，尚未压缩的部分
        upto_id = conversation.memory_upto_msg_id or 0
        new_messages = [
            m for m in all_messages[:-keep_count]
            if m.id > upto_id
        ]
        if not new_messages:
            return conversation.long_memory or ""

        # 拼接新对话文本
        dialogue_lines = []
        for m in new_messages:
            role = "用户" if m.role == "user" else "助手"
            content = m.content or ""
            dialogue_lines.append(f"{role}：{content[:500]}")
        new_dialogue = "\n".join(dialogue_lines)

        try:
            from ..retrieval._sync_llm import sync_chat
            prompt = COMPRESS_PROMPT.format(
                existing_summary=conversation.long_memory or "（暂无）",
                new_dialogue=new_dialogue,
            )
            summary = sync_chat(
                prompt, system=COMPRESS_SYSTEM, temperature=0.2, max_tokens=500,
                purpose="memory", kb_id=conversation.kb_id,
            )
            if summary:
                conversation.long_memory = summary
        except Exception as e:
            logger.warning(f"长期记忆压缩失败：{e}")

        # 更新压缩进度
        conversation.memory_upto_msg_id = new_messages[-1].id
        db.commit()
        return conversation.long_memory or ""

    def build_memory_block(self, conversation: Optional[Conversation]) -> str:
        """构建注入 system 提示词的长期记忆块"""
        if not conversation or not conversation.long_memory:
            return ""
        return f"## 历史对话摘要\n{conversation.long_memory}\n"


memory_service = MemoryService()
