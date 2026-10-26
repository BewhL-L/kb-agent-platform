"""文档处理与 Wiki 编译的 Celery 任务（worker 进程内独立创建 DB 会话）"""
from .celery_app import celery_app


@celery_app.task(name="tasks.process_document", bind=True, max_retries=2)
def process_document_task(self, document_id: int) -> dict:
    from ..database import SessionLocal
    from ..models import Document
    from ..services.document_service import document_service

    db = SessionLocal()
    try:
        document = db.query(Document).filter(Document.id == document_id).first()
        if not document:
            return {"status": "missing", "document_id": document_id}
        document_service.process_document(db, document)
        return {
            "status": document.status,
            "document_id": document_id,
            "chunks": document.chunk_count,
        }
    finally:
        db.close()


@celery_app.task(name="tasks.compile_wiki", bind=True, max_retries=2)
def compile_wiki_task(self, kb_id: int, document_id: int = None) -> dict:
    """Wiki 编译任务：编译单个文档或重编译整个知识库"""
    from ..database import SessionLocal

    db = SessionLocal()
    try:
        from ..wiki import wiki_compiler
        if document_id:
            wiki_compiler.compile_document(db, kb_id, document_id)
            return {"status": "done", "document_id": document_id}
        stats = wiki_compiler.recompile_kb(db, kb_id)
        return {"status": "done", "stats": stats}
    finally:
        db.close()
