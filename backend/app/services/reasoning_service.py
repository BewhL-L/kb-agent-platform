"""
推理模型服务（Reasoning / Test-time Compute）
================================================
- 调用带"思考链"的推理模型，分离【思考过程】与【最终答案】
  - 兼容 reasoning_content 字段（DeepSeek R1 / 豆包 thinking 等）
  - 兼容 <think>...</think> 标签（开源 R1 风格）
- Self-Consistency：多次采样取多数一致答案（推理时计算）
- 判断问题是否需要推理（简单问题走普通模型，省时省钱）

与普通 RAG 的区别：
    普通 RAG：检索 -> 直接生成答案
    推理 RAG：检索 -> 模型先推理（分析、规划、自检）-> 再给答案
"""
import asyncio
import re
from typing import Dict, List

from ..config import settings
from ..utils.logger import get_logger
from .llm_service import LLMService

logger = get_logger(__name__)


# 复杂问题信号词（命中则倾向启用推理）
_COMPLEX_SIGNALS = [
    "为什么", "如何", "对比", "比较", "分析", "总结", "步骤", "流程",
    "区别", "优劣", "方案", "规划", "推导", "证明", "计算", "如果",
]

# 匹配 <think>...</think>（含未闭合的情况）
_THINK_RE = re.compile(r"<think>(.*?)</think>", re.S)
_THINK_OPEN_RE = re.compile(r"<think>(.*)", re.S)


def extract_reasoning(content: str) -> Dict[str, str]:
    """
    从文本中分离思考过程与最终答案。
    返回 {"reasoning": 思考过程, "answer": 最终答案}
    """
    if not content:
        return {"reasoning": "", "answer": ""}

    m = _THINK_RE.search(content)
    if m:
        reasoning = m.group(1).strip()
        answer = (content[:m.start()] + content[m.end():]).strip()
        return {"reasoning": reasoning, "answer": answer}

    # 未闭合的 <think>（思考后直接结束，常见于流式）
    m2 = _THINK_OPEN_RE.search(content)
    if m2:
        return {"reasoning": m2.group(1).strip(), "answer": ""}

    return {"reasoning": "", "answer": content.strip()}


def needs_reasoning(question: str) -> bool:
    """启发式判断问题是否需要推理模型"""
    if len(question) >= settings.REASONING_MIN_QUESTION_LEN:
        return True
    return any(sig in question for sig in _COMPLEX_SIGNALS)


class ReasoningService:
    """推理模型服务"""

    def __init__(self):
        self.llm = LLMService()

    async def reason(
        self,
        messages: List[Dict],
        model: str = None,
        temperature: float = 0.6,
        max_tokens: int = 4000,
    ) -> Dict[str, str]:
        """
        调用推理模型，返回 {"answer", "reasoning"}。
        """
        model = model or settings.REASONING_MODEL
        client = self.llm.client

        # 为推理模型构建独立的 LLMService（模型名不同）
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self._record(response, model)

        msg = response.choices[0].message
        # 优先用独立的 reasoning_content 字段
        reasoning = getattr(msg, "reasoning_content", None)
        content = msg.content or ""

        if reasoning:
            return {"answer": content.strip(), "reasoning": reasoning.strip()}

        # 退化：从 content 解析 <think>
        parsed = extract_reasoning(content)
        return parsed

    async def reason_with_consistency(
        self,
        messages: List[Dict],
        samples: int = None,
        model: str = None,
    ) -> Dict[str, str]:
        """
        Self-Consistency：多次采样独立推理，取最一致的答案。
        - 适合有确定答案的问题（数学、逻辑）
        - 成本为单次的 N 倍
        """
        samples = samples or settings.SELF_CONSISTENCY_SAMPLES
        tasks = [self.reason(messages, model=model) for _ in range(samples)]
        results = await asyncio.gather(*tasks)

        # 按最终答案投票（归一化后）
        votes: Dict[str, int] = {}
        reasonings: Dict[str, str] = {}
        for r in results:
            key = re.sub(r"\s+", "", r["answer"])
            votes[key] = votes.get(key, 0) + 1
            reasonings.setdefault(key, r["reasoning"])

        best_key = max(votes, key=votes.get)
        best_answer = next(
            r["answer"] for r in results
            if re.sub(r"\s+", "", r["answer"]) == best_key
        )
        return {
            "answer": best_answer,
            "reasoning": reasonings.get(best_key, ""),
            "votes": votes,
            "samples": samples,
        }

    def _record(self, response, model) -> None:
        """记录推理调用的 token 用量（推理 token 通常计入 completion）"""
        try:
            from ..database import SessionLocal
            from .usage_service import usage_service
            usage = getattr(response, "usage", None)
            if not usage:
                return
            db = SessionLocal()
            try:
                usage_service.record_usage(
                    db, model=model,
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    purpose="reasoning",
                )
            finally:
                db.close()
        except Exception as e:
            logger.debug(f"推理用量记录失败：{e}")


reasoning_service = ReasoningService()
