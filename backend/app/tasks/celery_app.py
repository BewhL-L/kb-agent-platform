"""Celery 应用：生产环境后台任务（文档解析/向量化等耗时操作）"""
from celery import Celery

from ..config import settings

celery_app = Celery(
    "kb_worker",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=False,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_queue="default",
)

celery_app.autodiscover_tasks(["app.tasks"])
