"""
把已有数据库升级到 RBAC 版本（幂等，可重复执行）
================================================
做两件事：
  1. 建出缺失的表（主要是 kb_members）——SQLAlchemy create_all 只会建表，不会改表
  2. 给已存在的 users 表补 role 列（create_all 不会补列，这是最容易踩的坑）

用法（在 backend 目录下执行）：
    python scripts/migrate_add_rbac.py

为什么不用 Alembic：
    这是过渡脚本。正式做法是引入 Alembic 管理迁移版本（见学习任务清单）。
    在那之前，这个脚本保证「不删库」也能升级。
"""
import os
import sys

# 允许直接 `python scripts/migrate_add_rbac.py` 运行：把 backend 目录加进 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import engine  # noqa: E402
from app.models import Base  # noqa: E402


def main() -> None:
    print(f"目标数据库：{settings.DATABASE_URL}")

    inspector = inspect(engine)
    before = set(inspector.get_table_names())

    # 1. 建缺失的表（已有表不受影响）
    Base.metadata.create_all(bind=engine)
    after = set(inspect(engine).get_table_names())
    created = after - before
    print(f"新建表：{sorted(created) if created else '无'}")

    # 2. 补 users.role 列
    if "users" not in after:
        print("users 表不存在，跳过补列（请先启动一次应用让 create_all 建表）")
        return

    columns = [c["name"] for c in inspect(engine).get_columns("users")]
    if "role" in columns:
        print("users.role 已存在，无需处理")
        return

    with engine.begin() as conn:
        conn.execute(
            text("ALTER TABLE users ADD COLUMN role VARCHAR(16) NOT NULL DEFAULT 'editor'")
        )
    print("已补列：users.role（默认 editor）")


if __name__ == "__main__":
    main()
