"""
评测执行器（Evaluation Runner）
对 golden QA 逐条：检索 → 生成 → 计算检索/生成指标 →（可选）LLM Judge →（可选）RAGAS
汇总平均并生成报告（eval_reports/eval_时间戳.json 与 latest.json）。
"""
import json
import os
import time
from datetime import datetime
from typing import Dict, List, Optional

from ..config import settings
from ..services.grounding_service import grounding_service
from ..utils.logger import get_logger
from . import metrics as M
from .llm_judge import judge_faithfulness, judge_relevancy
from .ragas_runner import run_ragas

logger = get_logger(__name__)

_METRIC_NAMES = [
    "hit@k",
    "mrr",
    "context_precision",
    "context_recall",
    "answer_keyword_coverage",
    "citation_coverage",
    "faithfulness",
    "answer_relevancy",
]


def load_dataset(path: str = None) -> List[Dict]:
    path = path or settings.EVAL_DATASET_PATH
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("cases", [])


def _avg(values: List[Optional[float]]) -> Optional[float]:
    nums = [v for v in values if v is not None]
    return round(sum(nums) / len(nums), 4) if nums else None


class EvaluationRunner:
    async def run(
        self,
        kb_id: int = None,
        top_k: int = None,
        use_judge: bool = None,
        dataset_path: str = None,
    ) -> Dict:
        from ..services.rag_service import rag_service

        use_judge = settings.LLM_JUDGE_ENABLED if use_judge is None else use_judge
        k = top_k or settings.TOP_K
        cases = load_dataset(dataset_path)

        rows: List[Dict] = []
        ragas_samples: List[Dict] = []

        for case in cases:
            target_kb = kb_id or case.get("kb_id")
            question = case["question"]

            t0 = time.time()
            retrieved = await rag_service.aretrieve(target_kb, question, k)
            chat = await rag_service.chat(target_kb, question)
            answer = chat["answer"]
            latency = round(time.time() - t0, 3)

            row = {
                "id": case.get("id"),
                "category": case.get("category"),
                "question": question,
                "hit@k": M.hit_at_k(retrieved, case, k),
                "mrr": M.mrr(retrieved, case),
                "context_precision": M.average_precision(retrieved, case),
                "context_recall": M.context_recall(retrieved, case),
                "answer_keyword_coverage": M.answer_keyword_coverage(answer, case),
                # 溯源覆盖率：答案里有依据的句子占比（零成本，见 grounding_service）
                "citation_coverage": grounding_service.verify(answer, retrieved)["coverage"],
                # 拒答识别：该拒的有没有拒、不该拒的有没有乱拒
                "should_refuse": M.should_refuse(case),
                "refused": M.is_refusal_answer(answer),
                "latency_s": latency,
            }
            if use_judge:
                row["faithfulness"] = judge_faithfulness(question, answer, retrieved)
                row["answer_relevancy"] = judge_relevancy(question, answer)
            else:
                row["faithfulness"] = None
                row["answer_relevancy"] = None
            rows.append(row)

            ragas_samples.append({
                "question": question,
                "answer": answer,
                "contexts": [c["text"] for c in retrieved],
                "reference": case.get("reference_answer", ""),
            })

        summary: Dict = {m: _avg([r[m] for r in rows]) for m in _METRIC_NAMES}
        summary["case_count"] = len(rows)
        summary["avg_latency_s"] = _avg([r["latency_s"] for r in rows])
        summary.update(M.refusal_summary(rows))

        report = {
            "run_at": datetime.now().isoformat(timespec="seconds"),
            "summary": summary,
            "cases": rows,
        }

        ragas_scores = run_ragas(ragas_samples)
        if ragas_scores:
            report["ragas"] = ragas_scores

        self._save(report)
        return report

    def _save(self, report: Dict) -> None:
        os.makedirs(settings.EVAL_REPORT_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(settings.EVAL_REPORT_DIR, f"eval_{ts}.json")
        latest = os.path.join(settings.EVAL_REPORT_DIR, "latest.json")
        for p in (path, latest):
            with open(p, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
        report["report_path"] = path


evaluation_runner = EvaluationRunner()
