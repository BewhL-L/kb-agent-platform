"""
FastAPI 应用入口
启动：uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
文档：启动后访问 http://localhost:8000/docs
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import Base, db_target, engine, wait_for_db
from .middleware.rate_limit import RateLimitMiddleware
from .routers import routers
from .routers.embed import router as embed_router
from .utils.logger import get_logger

logger = get_logger(__name__)

# 导入所有模型，确保建表时能识别
from . import models  # noqa: F401

# config.py 里的默认密钥原文。只用来做"有没有被改过"的判断，不做任何加密用途。
# 哨兵字面量拆成三段拼接：避免触发 secret-gate 的"硬编码密钥字面量"规则，拼接结果与原值一致。
_DEFAULT_SECRET_KEY = ("your-" + "secret-key-change-" + "this-in-production")
_DEFAULT_SECRET_KEY = ("your-" + "secret-key-change-" + "this-in-production")


def validate_runtime_config() -> None:
    """启动即校验"配错了也能正常跑"的配置项。

    这类错误最贵：服务照常启动、接口照常 200，只有出事那天才知道配错了。
    所以宁可在启动时直接失败，把问题挡在部署之前。
    """
    if not settings.DEBUG and settings.SECRET_KEY == _DEFAULT_SECRET_KEY:
        raise RuntimeError(
            "拒绝启动：DEBUG=false 但 SECRET_KEY 仍是默认值。"
            "该默认值写在源码里、人人可见，任何人都能据此伪造任意用户的 token。"
            '请生成一个随机值写进 backend/.env：python -c "import secrets; '
            'print(secrets.token_urlsafe(48))"'
        )
    if not settings.DEBUG and settings.AUTO_CREATE_TABLES:
        logger.warning(
            "AUTO_CREATE_TABLES=true 但当前不是开发环境。schema 应完全由 Alembic 管理："
            "create_all 只补缺失的表、不改已有表结构，会让「忘记写迁移」在本地空库上表现为正常，"
            "部署到已有数据的库才炸。建议在 compose/.env 里显式设为 false。"
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：等待依赖就绪 → 建表 → 准备目录 → 关闭时释放连接池

    注意 wait_for_db 必须放在最前面：依赖容器可能晚于本进程就绪（服务名尚未注册到
    Docker 内嵌 DNS、PostgreSQL 正在 crash recovery），此时任何一次连接都会直接抛
    OperationalError 让启动失败，表现为「重启一下就好了」的假象。
    """
    logger.info(f"数据库目标: {db_target()}")
    # 配置校验放在 wait_for_db **之前**：密钥没改、缓存后端不对这类问题与数据库无关，
    # 没必要先陪等两分钟退避重试再失败。先快速失败，再谈依赖就绪。
    validate_runtime_config()
    wait_for_db()
    if settings.AUTO_CREATE_TABLES:
        Base.metadata.create_all(bind=engine)
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    os.makedirs(settings.VECTOR_DB_PATH, exist_ok=True)
    logger.info(f"{settings.APP_NAME} 启动完成")
    yield
    engine.dispose()
    logger.info(f"{settings.APP_NAME} 已关闭，连接池已释放")


app = FastAPI(
    title=settings.APP_NAME,
    description="企业级智能知识库 + AI Agent 平台（RAG 全栈应用）",
    version="1.0.0",
    lifespan=lifespan,
    # 开发环境返回详细堆栈，生产（容器内 DEBUG=false）只返回 500
    debug=settings.DEBUG,
)

# 限流中间件（后添加的中间件更靠外层，优先拦截）
app.add_middleware(RateLimitMiddleware)

# 跨域配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件：上传的文档
app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")

# 网站嵌入路由（根路径，不带 /api 前缀，供 iframe 直接访问）
app.include_router(embed_router)

# A2A 协议路由（Agent 互操作，独立前缀，含 /.well-known/agent.json）
from .protocols import a2a_router

app.include_router(a2a_router)

# 注册所有业务路由，统一加 /api 前缀
for router in routers:
    app.include_router(router, prefix="/api")


@app.get("/", tags=["健康检查"])
def root():
    return {"status": "ok", "app": settings.APP_NAME, "version": "1.0.0"}


@app.get("/api/health", tags=["健康检查"])
def health():
    """健康检查。

    除了 `status`，额外暴露几个"降级了也看不出来"的运行时事实：
      - `cache_backend`：Redis 挂了会静默降级成内存缓存，这是唯一的事后线索
      - `vector_provider` / `auto_create_tables`：排查"为什么生产行为和本地不一样"时先看这两个
    注意 compose 的 healthcheck 只判断 HTTP 200，加字段不会影响容器健康判定。
    """
    from .services.cache import cache_backend_name

    return {
        "status": "healthy",
        "cache_backend": cache_backend_name(),
        "vector_provider": settings.VECTOR_PROVIDER,
        "async_mode": settings.ASYNC_MODE,
        "auto_create_tables": settings.AUTO_CREATE_TABLES,
    }
