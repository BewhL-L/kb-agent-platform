"""
索引效果实测（面试素材生成器）
==============================
用真实 SQLite 数据演示三件事：
1. 没索引：全表扫描（SCAN）
2. 只建过滤列索引 (kb_id)：能定位行，但排序仍要临时 B 树
3. 把排序列也放进索引 (kb_id, created_at)：过滤 + 排序一次搞定

运行：
    cd backend && python scripts/explain_index.py
"""
import os
import random
import sqlite3
import tempfile
import time

ROWS = 50_000
KBS = 20
STATUSES = ["completed", "processing", "failed"]

# 和 GET /api/kb/{kb_id}/docs 的真实查询一致：
# 按知识库过滤 + 按创建时间倒序 + 分页
SQL = (
    "select id, filename from documents "
    "where kb_id = ? "
    "order by created_at desc limit 20"
)


def build_db(path: str) -> None:
    con = sqlite3.connect(path)
    con.execute(
        """
        create table documents (
            id integer primary key,
            kb_id integer not null,
            filename text not null,
            status text not null,
            created_at text not null
        )
        """
    )
    rows = [
        (
            i,
            random.randint(1, KBS),
            f"doc_{i}.pdf",
            random.choice(STATUSES),
            f"2026-{random.randint(1, 12):02d}-{random.randint(1, 28):02d} 10:00:00",
        )
        for i in range(ROWS)
    ]
    con.executemany("insert into documents values (?,?,?,?,?)", rows)
    con.commit()
    con.close()


def run_query(path: str, label: str) -> None:
    con = sqlite3.connect(path)
    plan = con.execute("explain query plan " + SQL, (7,)).fetchall()
    con.execute(SQL, (7,)).fetchall()  # 预热

    start = time.perf_counter()
    for _ in range(20):
        con.execute(SQL, (7,)).fetchall()
    cost = (time.perf_counter() - start) / 20 * 1000
    con.close()

    print(f"\n[{label}] 平均 {cost:.2f} ms / 次")
    for p in plan:
        print("    plan:", p[-1])


def add_index(path: str, ddl: str) -> None:
    con = sqlite3.connect(path)
    con.execute(ddl)
    con.commit()
    con.close()


def main() -> None:
    random.seed(42)
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        build_db(path)
        run_query(path, "① 无索引")

        add_index(path, "create index ix_doc_kb on documents(kb_id)")
        run_query(path, "② 索引 (kb_id)：能定位行，但排序仍要临时 B 树")

        add_index(
            path,
            "create index ix_doc_kb_created on documents(kb_id, created_at)",
        )
        run_query(path, "③ 索引 (kb_id, created_at)：项目里实际建的")

        print("\n看 plan 的差别：SCAN -> SEARCH，以及是否还出现 USE TEMP B-TREE FOR ORDER BY。")
    finally:
        os.remove(path)


if __name__ == "__main__":
    main()
