"""
迁移可用性测试
==============
防止「改了 models 但忘记生成迁移」或「迁移脚本写坏」——这两种问题在 CI 里必须拦住。

做法：在临时目录建一个空库，跑 `alembic upgrade head`，检查表是否齐全。
"""
import os
import pathlib
import sqlite3
import subprocess
import sys

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]

REQUIRED_TABLES = {
    "users",
    "knowledge_bases",
    "kb_members",
    "documents",
    "conversations",
    "messages",
    "feedbacks",
    "llm_usages",
    "wiki_pages",
    "wiki_page_versions",
    "graph_entities",
    "graph_relations",
    "graph_communities",
}


def test_alembic_upgrade_head_creates_all_tables(tmp_path):
    db_path = tmp_path / "migration_check.db"
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{db_path.as_posix()}",
        "AUTO_CREATE_TABLES": "false",
    }

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"alembic 执行失败：\n{result.stdout}\n{result.stderr}"

    con = sqlite3.connect(db_path)
    try:
        tables = {row[0] for row in con.execute(
            "select name from sqlite_master where type='table'"
        )}
        indexes = con.execute(
            "select count(*) from sqlite_master where type='index' and name like 'ix_%'"
        ).fetchone()[0]
    finally:
        con.close()

    missing = REQUIRED_TABLES - tables
    assert not missing, f"迁移后缺少表：{sorted(missing)}"
    assert indexes >= 40, f"索引数量异常：{indexes}"
