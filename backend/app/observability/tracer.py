"""
Langfuse 可观测性封装
- 启用后记录每次 RAG/Agent 调用：检索 span + 生成 generation + 延迟
- 未启用 / 未安装 langfuse / 写入失败时全部静默降级，对业务零影响
配合评测体系形成「离线评测 + 在线追踪」的完整质量闭环。
"""
from typing import Dict, List

from ..config import settings
from ..utils.logger import get_logger

logger = get_logger(__name__)


class Observability:
    def __init__(self):
        self.lf = None
        if settings.LANGFUSE_ENABLED:
            try:
                from langfuse import Langfuse

                self.lf = Langfuse(
                    public_key=settings.LANGFUSE_PUBLIC_KEY,
                    secret_key=settings.LANGFUSE_SECRET_KEY,
                    host=settings.LANGFUSE_HOST,
                )
                logger.info("Langfuse 可观测性已启用")
            except Exception as e:
                logger.warning(f"Langfuse 初始化失败，降级为不追踪：{e}")
                self.lf = None

    @property
    def enabled(self) -> bool:
        return self.lf is not None

    def trace_rag(
        self,
        question: str,
        retrieved: List[Dict],
        answer: str,
        kb_id: int = None,
        model: str = None,
        latency: float = None,
    ) -> None:
        if not self.lf:
            return
        try:
            trace = self.lf.trace(
                name="rag-qa",
                input={"question": question},
                metadata={"kb_id": kb_id, "latency_s": latency},
            )
            trace.span(
                name="retrieval",
                input={"question": question},
                output=[
                    {"document_name": c.get("document_name"), "text": c.get("text")}
                    for c in retrieved
                ],
            ).end()
            trace.generation(
                name="generation",
                model=model or settings.LLM_MODEL,
                input=question,
                output=answer,
            )
            self.lf.flush()
        except Exception as e:
            logger.debug(f"trace 写入失败：{e}")


observability = Observability()
