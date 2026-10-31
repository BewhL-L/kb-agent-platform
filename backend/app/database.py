"""数据库连接配置与启动期可用性等待"""
from __future__ import annotations

import logging
import random
import time

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import settings

# 此处不能用 app.utils.logger.get_logger：app/utils/__init__.py 会 import .deps，
# 而 deps 又 import 本模块的 get_db，形成循环导入（database → utils → deps → database）。
# 取同名 logger 即可，日志仍向父 logger "app" 冒泡，沿用统一格式与级别。
logger = logging.getLogger("app.database")

IS_SQLITE = settings.DATABASE_URL.startswith("sqlite")

_engine_options: dict = {"echo": False, "pool_pre_ping": True}
if IS_SQLITE:
    # SQLite 需要 check_same_thread=False 才能在多线程 FastAPI 中使用；
    # 内存库用的是 SingletonThreadPool，不接受 pool_size 等参数，故只对非 SQLite 生效
    _engine_options["connect_args"] = {"check_same_thread": False}
else:
    _engine_options.update(
        pool_size=5,
        max_overflow=10,
        pool_recycle=1800,
        pool_timeout=30,
    )

engine = create_engine(settings.DATABASE_URL, **_engine_options)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def db_target() -> str:
    """返回脱敏后的连接目标（不含账号密码）。

    写进启动日志后，出现「连不上」时能一眼区分是主机名解析问题还是端口/库名问题。
    """
    try:
        url = make_url(settings.DATABASE_URL)
    except Exception:  # noqa: BLE001 - 诊断函数不应抛出
        return "<UNPARSABLE DATABASE_URL>"
    if url.get_backend_name() == "sqlite":
        return f"sqlite://{url.database}"
    return (
        f"{url.drivername}://{url.host or '<local>'}:{url.port or '<default>'}"
        f"/{url.database or '<none>'}"
    )


def wait_for_db(
    max_attempts: int | None = None,
    base_delay: float | None = None,
    max_delay: float | None = None,
) -> None:
    """阻塞等待数据库可用，失败按指数退避重试。

    解决的是「进程比依赖先起来」这一类故障：
      - 容器名尚未在 Docker 内嵌 DNS 中注册 → failed to resolve host
      - PostgreSQL 刚被硬停机，正在做 crash recovery → the database system is starting up
      - 数据库被重启 / OOM 后短暂拒绝连接 → Connection refused

    全部尝试失败后抛出最后一次异常，让进程退出并由 compose 的 restart 策略兜底，
    而不是带着不可用的连接池对外提供服务——那种状态比直接退出更难排查。
    """
    if IS_SQLITE:
        return

    attempts = max_attempts or settings.DB_CONNECT_MAX_ATTEMPTS
    base = base_delay if base_delay is not None else settings.DB_CONNECT_BASE_DELAY
    ceiling = max_delay if max_delay is not None else settings.DB_CONNECT_MAX_DELAY

    for attempt in range(1, attempts + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except DBAPIError as exc:
            if attempt >= attempts:
                logger.error(f"数据库在 {attempts} 次尝试后仍不可用，放弃启动: {type(exc).__name__}")
                raise
            delay = min(base * (2 ** (attempt - 1)), ceiling)
            delay *= 0.5 + random.random()  # 抖动，避免多副本同时重连
            first_line = (str(exc).splitlines() or [""])[0][:200]
            logger.warning(
                f"数据库暂不可用（第 {attempt}/{attempts} 次，目标 {db_target()}）: "
                f"{first_line}；{delay:.1f}s 后重试"
            )
            time.sleep(delay)
        else:
            logger.info(f"数据库连接就绪（第 {attempt} 次尝试，目标 {db_target()}）")
            return


def get_db():
    """FastAPI 依赖：获取数据库会话，请求结束自动关闭"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
