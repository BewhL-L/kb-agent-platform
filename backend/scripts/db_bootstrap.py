"""
数据库启动引导（容器入口用）
============================
`AUTO_CREATE_TABLES=false` 之后，schema 完全由 Alembic 管。
但直接 `alembic upgrade head` 在"老库"上会炸：表已经存在，却没有 alembic_version。

这个脚本把三种情况收敛成一条命令：

    空库（无表）              -> alembic upgrade head（从基线建全）
    老库（有表、无版本表）    -> alembic stamp head + upgrade head
    已纳管（有 alembic_version）-> upgrade head（幂等）

用法：
    cd backend && python scripts/db_bootstrap.py

它会打印判定结果，出错直接非零退出（容器不会带着坏 schema 起来）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import inspect  # noqa: E402

from app import models  # noqa: E402,F401  确保 metadata 完整
from app.config import settings  # noqa: E402
from app.database import db_target, engine, wait_for_db  # noqa: E402

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    # 容器入口先于数据库就绪是常态（服务名未注册 / PG 正在 crash recovery）。
    # 这里先退避等待，避免 bootstrap 直接抛 OperationalError 让容器退出、
    # 再靠 restart 策略反复重启去"碰运气"。
    wait_for_db()

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    has_version = "alembic_version" in tables
    has_app_tables = "users" in tables

    config = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
    # script_location 在 ini 里是相对路径（相对 cwd），这里改成绝对路径，
    # 保证从任何目录调用都能找到 migrations/
    config.set_main_option("script_location", os.path.join(BACKEND_DIR, "migrations"))

    print(f"[db_bootstrap] url={db_target()}")
    print(f"[db_bootstrap] 现有表 {len(tables)} 张，alembic_version={'有' if has_version else '无'}")

    if not has_version and has_app_tables:
        # 老库：表是 create_all 建的，先把它标记成"已是最新"，否则 upgrade 会重复建表
        print("[db_bootstrap] 检测到未纳管的老库 -> stamp head")
        command.stamp(config, "head")

    command.upgrade(config, "head")
    print("[db_bootstrap] 已到达 head")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
