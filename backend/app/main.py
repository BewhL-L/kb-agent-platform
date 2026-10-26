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
from .database import Base, engine
from .middleware.rate_limit import RateLimitMiddleware
from .routers import routers
from .routers.embed import router as embed_router
from .utils.logger import get_logger

logger = get_logger(__name__)

# 导入所有模型，确保建表时能识别
from . import models  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时建表（仅开发模式；生产用 alembic upgrade head）"""
    if settings.AUTO_CREATE_TABLES:
        Base.metadata.create_all(bind=engine)
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    os.makedirs(settings.VECTOR_DB_PATH, exist_ok=True)
    logger.info(f"{settings.APP_NAME} 启动完成")
    yield


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
    return {"status": "healthy"}
