"""时间工具：统一获取 UTC 时间，替代已弃用的 datetime.utcnow()"""
from datetime import datetime, timezone


def utc_now() -> datetime:
    """
    返回当前 UTC 时间（naive，去掉 tzinfo）。
    - 用 datetime.now(timezone.utc) 替代弃用的 datetime.utcnow()
    - 去掉 tzinfo，与 SQLite/现有数据的 naive datetime 保持一致
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
