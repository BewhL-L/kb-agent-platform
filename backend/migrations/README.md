# 数据库迁移（Alembic）

## 为什么需要它

`Base.metadata.create_all()` 只会**建缺失的表**，不会：

- 给已有表加列 / 改类型 / 加索引
- 记录「这个库现在是第几版」

所以只要表里已经有数据，改结构就必须用迁移。

## 日常三条命令

```bash
cd backend

# 1) 改完 models 后，生成一个迁移脚本（先自己看一眼生成的内容！）
alembic revision --autogenerate -m "add xxx column"

# 2) 应用到数据库
alembic upgrade head

# 3) 回退一步（写错时用）
alembic downgrade -1
```

查看状态：

```bash
alembic current     # 当前版本
alembic history     # 迁移历史
```

## 两种数据库，两种初始化方式

| 场景 | 做法 |
|---|---|
| **全新库**（空） | 直接 `alembic upgrade head`，从 baseline 一次建全 |
| **已有库**（表是 create_all 建的、没迁移记录） | 先 `alembic stamp head` 把它标记成"已是最新"，之后才能正常升级 |

`stamp` 只写版本号，不动数据。**不要**在已有库上直接 `upgrade head`，否则会报 `table already exists`。

## 生产/容器里的正确姿势

容器启动命令里已经内置了 `scripts/db_bootstrap.py`，它会自己判断：

```
空库            -> alembic upgrade head
老库（无版本表）-> alembic stamp head + upgrade head
已纳管          -> upgrade head（幂等，可重复执行）
```

想手动执行也可以：

```bash
docker compose exec backend python scripts/db_bootstrap.py

# 之后每次发版（改了 models 并生成了迁移）
docker compose exec backend alembic upgrade head
```

`.env` 里 `AUTO_CREATE_TABLES` 已是 `false`——应用不再偷偷建表，schema 只有一个来源。

## 当前版本

- `20261026_1933_..._baseline.py`：13 张表 + 50 个索引的基线，等于把当时的 `create_all` 结果固化下来。

## 注意（Windows 特有）

`alembic.ini` 必须保持**纯 ASCII**。Alembic 用系统 locale 编码读这个文件，中文 Windows 是 GBK，写中文注释会直接 `UnicodeDecodeError`。
