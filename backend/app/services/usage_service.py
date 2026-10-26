"""
LLM 成本记录与统计服务
- 按模型单价计算每次调用的费用
- 记录到 llm_usages 表
- 提供按时间/用途/模型的汇总统计
"""
import json
from datetime import timedelta
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from ..config import settings
from ..models.llm_usage import LLMUsage
from ..timeutil import utc_now
from ..utils.logger import get_logger

logger = get_logger(__name__)


class UsageService:
    """LLM 成本服务"""

    def __init__(self):
        self._price_map: Dict[str, List[float]] = {}
        try:
            self._price_map = json.loads(settings.MODEL_PRICE_CONFIG)
        except json.JSONDecodeError:
            logger.warning("模型单价配置解析失败，费用将按 0 计算")

    def calculate_cost(
        self, model: str, prompt_tokens: int, completion_tokens: int
    ) -> float:
        """根据模型单价（每百万 token，元）计算费用"""
        price = self._price_map.get(model)
        if not price:
            # 模糊匹配：模型名包含配置中的 key（或反之）
            # 在所有匹配中选 key 最长的，避免 "gpt-4o" 误抢 "gpt-4o-mini"
            best_key = ""
            for key, val in self._price_map.items():
                if key in model or model in key:
                    if len(key) > len(best_key):
                        best_key = key
            if best_key:
                price = self._price_map[best_key]
        if not price:
            return 0.0
        input_price, output_price = price
        cost = (prompt_tokens / 1_000_000) * input_price + (
            completion_tokens / 1_000_000
        ) * output_price
        return round(cost, 6)

    def record_usage(
        self,
        db: Session,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        purpose: str = "chat",
        user_id: int = None,
        kb_id: int = None,
        prompt_version: str = "",
    ) -> Optional[LLMUsage]:
        """记录一次 LLM 调用与费用"""
        if not settings.COST_TRACKING_ENABLED:
            return None
        total_tokens = prompt_tokens + completion_tokens
        cost = self.calculate_cost(model, prompt_tokens, completion_tokens)
        usage = LLMUsage(
            user_id=user_id,
            kb_id=kb_id,
            model=model,
            purpose=purpose,
            prompt_version=prompt_version,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost=cost,
        )
        db.add(usage)
        db.commit()
        return usage

    def get_summary(
        self,
        db: Session,
        days: int = 30,
        user_id: int = None,
        kb_id: int = None,
    ) -> Dict:
        """
        汇总最近 N 天的用量与费用
        - 总 token、总费用、调用次数
        - 按用途拆分、按模型拆分、按天趋势
        """
        since = utc_now() - timedelta(days=days)
        query = db.query(LLMUsage).filter(LLMUsage.created_at >= since)
        if user_id:
            query = query.filter(LLMUsage.user_id == user_id)
        if kb_id:
            query = query.filter(LLMUsage.kb_id == kb_id)
        rows = query.all()

        total_cost = round(sum(r.cost for r in rows), 4)
        total_tokens = sum(r.total_tokens for r in rows)
        total_prompt = sum(r.prompt_tokens for r in rows)
        total_completion = sum(r.completion_tokens for r in rows)

        # 按用途拆分
        by_purpose: Dict[str, Dict] = {}
        for r in rows:
            item = by_purpose.setdefault(
                r.purpose, {"calls": 0, "tokens": 0, "cost": 0.0}
            )
            item["calls"] += 1
            item["tokens"] += r.total_tokens
            item["cost"] = round(item["cost"] + r.cost, 4)

        # 按模型拆分
        by_model: Dict[str, Dict] = {}
        for r in rows:
            item = by_model.setdefault(
                r.model, {"calls": 0, "tokens": 0, "cost": 0.0}
            )
            item["calls"] += 1
            item["tokens"] += r.total_tokens
            item["cost"] = round(item["cost"] + r.cost, 4)

        # 按天趋势
        by_day: Dict[str, float] = {}
        for r in rows:
            day = r.created_at.strftime("%Y-%m-%d")
            by_day[day] = round(by_day.get(day, 0.0) + r.cost, 4)
        daily = [{"date": d, "cost": c} for d, c in sorted(by_day.items())]

        return {
            "days": days,
            "total_calls": len(rows),
            "total_tokens": total_tokens,
            "prompt_tokens": total_prompt,
            "completion_tokens": total_completion,
            "total_cost": total_cost,
            "by_purpose": by_purpose,
            "by_model": by_model,
            "daily": daily,
        }


usage_service = UsageService()
