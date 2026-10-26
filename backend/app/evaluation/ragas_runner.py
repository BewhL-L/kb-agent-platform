"""
RAGAS 适配（可选）
- 安装 ragas（及 datasets）后，直接使用官方四指标
- 未安装或运行失败时返回 None，评测继续使用内置的确定性指标 + LLM Judge
"""
from typing import Dict, List, Optional

from ..utils.logger import get_logger

logger = get_logger(__name__)

RAGAS_AVAILABLE = False
try:
    from ragas import evaluate  # noqa: F401
    from ragas.metrics import (  # noqa: F401
        answer_relevancy,
        context_precision,
        context_recall,
        faithfulness,
    )
    RAGAS_AVAILABLE = True
except Exception:
    RAGAS_AVAILABLE = False


def run_ragas(samples: List[Dict]) -> Optional[Dict[str, float]]:
    """
    samples: [{question, answer, contexts: [str], reference}]
    返回 {metric: score} 或 None
    """
    if not RAGAS_AVAILABLE:
        logger.info("未安装 ragas，跳过官方 RAGAS 指标（可 pip install ragas datasets）")
        return None
    try:
        from datasets import Dataset

        ds = Dataset.from_list(samples)
        from ragas import evaluate
        from ragas.metrics import answer_relevancy, context_precision, context_recall, faithfulness

        result = evaluate(
            ds,
            metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
        )
        return {k: float(v) for k, v in result.items()}
    except Exception as e:
        logger.warning(f"RAGAS 运行失败：{e}")
        return None
