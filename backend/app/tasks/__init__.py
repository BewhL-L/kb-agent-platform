"""后台任务包（Celery）"""
from .celery_app import celery_app
from .document_tasks import process_document_task

__all__ = ["celery_app", "process_document_task"]
