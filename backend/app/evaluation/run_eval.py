"""
命令行评测入口（在 backend 目录下运行）
  python -m app.evaluation.run_eval --kb-id 1
  python -m app.evaluation.run_eval --no-judge
"""
import argparse
import asyncio
import json

from .runner import evaluation_runner


async def _run(kb_id: int, use_judge: bool) -> None:
    report = await evaluation_runner.run(kb_id=kb_id, use_judge=use_judge)
    print("\n===== 评测汇总 =====")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    if "ragas" in report:
        print("\n===== RAGAS 官方指标 =====")
        print(json.dumps(report["ragas"], ensure_ascii=False, indent=2))
    print(f'\n报告已保存：{report.get("report_path")}')


def main() -> None:
    p = argparse.ArgumentParser(description="RAG / Agentic RAG 评测")
    p.add_argument("--kb-id", type=int, default=None, help="统一评测该知识库（覆盖用例 kb_id）")
    p.add_argument("--no-judge", action="store_true", help="不调用 LLM Judge（省 token）")
    args = p.parse_args()
    asyncio.run(_run(args.kb_id, use_judge=not args.no_judge))


if __name__ == "__main__":
    main()
