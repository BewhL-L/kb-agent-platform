"""
大模型调用封装
- 支持普通调用 / 流式调用 / 工具调用，兼容 OpenAI 接口规范
- 内置超时、指数退避重试、错误降级
- 支持按用户传入模型名（多模型切换）
"""
import asyncio
from typing import AsyncGenerator, Dict, List, Optional

from openai import APIConnectionError, APIError, APITimeoutError, AsyncOpenAI, InternalServerError, RateLimitError

from ..config import settings
from ..utils.logger import get_logger

logger = get_logger(__name__)


class LLMError(Exception):
    """LLM 调用失败（重试耗尽后抛出，上层做友好降级）"""


# 哪些异常值得重试（瞬时故障）
_RETRYABLE = (APITimeoutError, APIConnectionError, RateLimitError, InternalServerError)


class LLMService:
    """LLM 调用服务"""

    def __init__(self, api_key: str = "", base_url: str = "", model: str = ""):
        # 支持传入用户自定义模型（多模型切换）；API Key 平台统一提供
        self.client = AsyncOpenAI(
            api_key=api_key or settings.LLM_API_KEY,
            base_url=base_url or settings.LLM_BASE_URL,
            timeout=settings.LLM_TIMEOUT,
            max_retries=0,  # 我们自己实现重试，便于记录日志和控制节奏
        )
        self.model = model or settings.LLM_MODEL
        logger.debug(f"LLMService 初始化，model={self.model}")

    async def _call_with_retry(self, call_factory, operation: str = "chat"):
        """
        通用非流式重试封装（指数退避）
        call_factory: 无参 async callable，每次重试重新调用
        """
        last_error: Optional[Exception] = None
        for attempt in range(settings.LLM_MAX_RETRIES):
            try:
                return await call_factory()
            except _RETRYABLE as e:
                last_error = e
                if attempt < settings.LLM_MAX_RETRIES - 1:
                    delay = settings.LLM_RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        f"{operation} 第{attempt + 1}次调用失败（{type(e).__name__}），{delay:.1f}s 后重试"
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"{operation} 重试 {settings.LLM_MAX_RETRIES} 次后仍失败：{e}")
            except APIError as e:
                # 其他 API 错误（如 401 认证失败）不重试，直接抛出
                logger.error(f"{operation} 不可重试的 API 错误：{e}")
                raise LLMError(f"模型调用失败：{e}") from e
        raise LLMError("模型服务暂时不可用，请稍后再试") from last_error

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2000,
        purpose: str = "chat",
        user_id: int = None,
        kb_id: int = None,
        prompt_version: str = "",
    ) -> str:
        """普通调用，返回完整回答"""
        def _factory():
            return self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        response = await self._call_with_retry(_factory, operation="chat")
        # 记录 token 用量与费用
        self._record_usage(response, purpose, user_id, kb_id, prompt_version)
        return response.choices[0].message.content

    def _record_usage(
        self, response, purpose: str, user_id: int, kb_id: int, prompt_version: str = ""
    ) -> None:
        """从响应中提取 usage 并记录，失败不影响主流程"""
        try:
            usage = getattr(response, "usage", None)
            if not usage:
                return
            from ..database import SessionLocal
            from .usage_service import usage_service

            db = SessionLocal()
            try:
                usage_service.record_usage(
                    db,
                    model=self.model,
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    purpose=purpose,
                    user_id=user_id,
                    kb_id=kb_id,
                    prompt_version=prompt_version,
                )
            finally:
                db.close()
        except Exception as e:
            logger.debug(f"用量记录失败：{e}")

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> AsyncGenerator[str, None]:
        """流式调用，逐字 yield；流式在建立连接阶段做重试，开始输出后出错则中断提示"""
        stream = None
        for attempt in range(settings.LLM_MAX_RETRIES):
            try:
                stream = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=True,
                )
                break
            except _RETRYABLE as e:
                if attempt < settings.LLM_MAX_RETRIES - 1:
                    delay = settings.LLM_RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(f"流式连接失败，{delay:.1f}s 后重试")
                    await asyncio.sleep(delay)
                else:
                    raise LLMError("模型连接失败，请稍后再试") from e
            except APIError as e:
                raise LLMError(f"模型调用失败：{e}") from e

        if stream is None:
            raise LLMError("模型连接失败")

        try:
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except (APIError, APIConnectionError) as e:
            logger.error(f"流式输出中断：{e}")
            yield "\n\n[输出中断，请重试]"

    async def chat_with_tools(
        self,
        messages: List[Dict[str, str]],
        tools: List[dict],
        temperature: float = 0.7,
    ) -> dict:
        """带工具调用的对话（Agent 用），返回模型原始 message"""
        def _factory():
            return self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=temperature,
            )

        response = await self._call_with_retry(_factory, operation="chat_with_tools")
        return response.choices[0].message


def get_llm_service(model: str = "") -> LLMService:
    """
    工厂：根据用户当前选择的模型构建 LLMService
    model 为空则用系统默认模型
    """
    return LLMService(model=model)


# 全局单例（默认模型）
llm_service = LLMService()
