"""
评测 HTTP API
- POST /api/evaluation/run            触发评测（可带 kb_id）
- GET  /api/evaluation/latest         查看最新评测报告
"""
import json
import os

from fastapi import APIRouter, Depends

from ..config import settings
from ..evaluation.runner import evaluation_runner
from ..utils.deps import get_current_user

router = APIRouter(prefix="/evaluation", tags=["评测"])


@router.post("/run")
async def run_evaluation(kb_id: int = None, current_user=Depends(get_current_user)):
    report = await evaluation_runner.run(kb_id=kb_id)
    return {
        "summary": report["summary"],
        "report_path": report.get("report_path"),
        "ragas": report.get("ragas"),
    }


@router.get("/latest")
def latest_report(current_user=Depends(get_current_user)):
    path = os.path.join(settings.EVAL_REPORT_DIR, "latest.json")
    if not os.path.exists(path):
        return {"message": "暂无评测报告，请先调用 /run 运行评测"}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
