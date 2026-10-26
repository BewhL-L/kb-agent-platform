"""检索链路内部使用的同步 LLM 调用（查询改写 / Rerank / Wiki 编译需要在同步链路中调用）"""
from typing import Optional

from openai import OpenAI

from ..config import settings
from ..utils.logger import get_logger

logger = get_logger(__name__)
_client: Optional[OpenAI] = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
            timeout=settings.LLM_TIMEOUT,
            max_retries=settings.LLM_MAX_RETRIES,
        )
    return _client


def _record_sync_usage(resp, purpose: str, kb_id: int) -> None:
    """记录同步调用的 token 用量与费用，失败不影响主流程"""
    try:
        usage = getattr(resp, "usage", None)
        if not usage:
            return
        from ..database import SessionLocal
        from ..services.usage_service import usage_service

        db = SessionLocal()
        try:
            usage_service.record_usage(
                db,
                model=settings.LLM_MODEL,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                purpose=purpose,
                kb_id=kb_id,
            )
        finally:
            db.close()
    except Exception:
        pass


def sync_chat(
    prompt: str,
    system: str = "",
    temperature: float = 0.3,
    max_tokens: int = 500,
    purpose: str = "other",
    kb_id: int = None,
) -> str:
    """同步对话；失败时返回空串，由调用方走降级逻辑"""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    try:
        resp = get_client().chat.completions.create(
            model=settings.LLM_MODEL,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        _record_sync_usage(resp, purpose, kb_id)
        return resp.choices[0].message.content or ""
    except Exception as e:
        logger.warning(f"同步 LLM 调用失败：{e}")
        return ""
