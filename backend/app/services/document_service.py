"""
文档处理服务：文件上传后，完整走一遍 解析 -> 切片 -> 向量化 -> 入库
"""
import os
import threading
import uuid

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Document
from ..utils.logger import get_logger
from .document_parser import parse_document
from .text_splitter import split_text
from .vector_store import get_vector_store

logger = get_logger(__name__)


class DocumentService:
    """文档处理服务"""

    def __init__(self, vector_store=None):
        self.vector_store = vector_store or get_vector_store()

    def save_upload_file(self, file_content: bytes, original_filename: str) -> tuple:
        """
        保存上传文件到磁盘
        返回 (存储文件名, 完整路径, 文件大小)
        """
        os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
        ext = os.path.splitext(original_filename)[1]
        stored_name = f"{uuid.uuid4().hex}{ext}"
        file_path = os.path.join(settings.UPLOAD_DIR, stored_name)
        with open(file_path, "wb") as f:
            f.write(file_content)
        return stored_name, file_path, len(file_content)

    def process_document(self, db: Session, document: Document) -> None:
        """
        处理单个文档：解析 -> 切片 -> 向量化 -> 更新状态
        可在后台线程中调用
        """
        try:
            document.status = "processing"
            db.commit()

            # 1. 解析文档
            text = parse_document(document.file_path)
            if not text.strip():
                raise ValueError("文档内容为空，无法处理")

            # 2. 文本切片 + 3. 向量化（父子分块或普通分块）
            if settings.PARENT_CHUNK_ENABLED:
                from .text_splitter import split_parent_child
                records = split_parent_child(text)
                if not records:
                    raise ValueError("切片失败")
                self.vector_store.add_parent_child_documents(
                    kb_id=document.kb_id,
                    records=records,
                    document_id=document.id,
                    document_name=document.filename,
                )
                # chunk_count 按大块数统计
                chunk_count = len({r["parent_index"] for r in records})
            else:
                chunks = split_text(text)
                if not chunks:
                    raise ValueError("切片失败")
                self.vector_store.add_documents(
                    kb_id=document.kb_id,
                    chunks=chunks,
                    document_id=document.id,
                    document_name=document.filename,
                )
                chunk_count = len(chunks)

            # 4. 更新状态
            document.status = "completed"
            document.chunk_count = chunk_count
            db.commit()

            # 4.5 让该库的检索缓存失效：新切片必须能被下一次检索看到
            from .retrieval_cache import retrieval_cache
            retrieval_cache.bump(document.kb_id)

            # 5. 触发 LLM Wiki 编译（独立后台线程，不阻塞文档处理；失败不影响主流程）
            if settings.WIKI_ENABLED and settings.WIKI_AUTO_COMPILE:
                self._trigger_wiki_compile(document.kb_id, document.id)

        except Exception as e:
            document.status = "failed"
            document.error_msg = str(e)
            db.commit()

    def _trigger_wiki_compile(self, kb_id: int, doc_id: int) -> None:
        """触发 Wiki 编译：根据 ASYNC_MODE 走 Celery 队列或本地线程"""
        if settings.ASYNC_MODE == "celery":
            try:
                from ..tasks.document_tasks import compile_wiki_task
                compile_wiki_task.delay(kb_id, doc_id)
                return
            except Exception as e:
                logger.warning(f"Celery 提交失败，降级为线程：{e}")

        # 本地线程：每个线程使用独立的数据库会话
        from ..database import SessionLocal

        def _compile_in_background():
            bg_db = SessionLocal()
            try:
                from ..wiki import wiki_compiler
                wiki_compiler.compile_document(bg_db, kb_id, doc_id)
            except Exception as e:
                logger.warning(f"文档 {doc_id} 的 Wiki 编译失败：{e}")
            finally:
                bg_db.close()

        thread = threading.Thread(target=_compile_in_background, daemon=True)
        thread.start()

    def delete_document_vectors(self, kb_id: int, document_id: int) -> None:
        """删除文档时同步删除向量，并让检索缓存失效"""
        self.vector_store.delete_document(kb_id, document_id)
        from .retrieval_cache import retrieval_cache
        retrieval_cache.bump(kb_id)

    def detach_document_from_wiki(
        self, db: Session, kb_id: int, document_id: int
    ) -> dict:
        """
        删除文档时，从所有 Wiki 页面的 source_doc_ids 中移除该文档。
        - 页面还有其他来源文档：仅移除该 ID，标记为 stale（待重编译）
        - 页面来源文档全部被删：删除该页面（知识已无来源）
        返回 {"updated": 页面数, "deleted": 页面数}
        """
        from ..models.wiki_page import WikiPage

        pages = (
            db.query(WikiPage)
            .filter(WikiPage.kb_id == kb_id)
            .all()
        )
        updated = 0
        deleted = 0
        for page in pages:
            source_ids = list(page.source_doc_ids or [])
            if document_id not in source_ids:
                continue

            source_ids.remove(document_id)
            if not source_ids:
                # 没有任何来源文档了，删除页面
                db.delete(page)
                deleted += 1
            else:
                page.source_doc_ids = source_ids
                page.status = "stale"
                updated += 1
        db.commit()
        logger.info(
            f"文档 {document_id} 删除：Wiki 页面更新 {updated} 个，删除 {deleted} 个"
        )
        return {"updated": updated, "deleted": deleted}

    def mark_wiki_stale_for_document(
        self, db: Session, kb_id: int, document_id: int
    ) -> int:
        """
        更新文档时，把引用该文档的 Wiki 页面先标记为 stale。
        文档重新处理完成后会自动触发重编译，恢复为 compiled。
        返回标记的页面数。
        """
        from ..models.wiki_page import WikiPage

        pages = (
            db.query(WikiPage)
            .filter(WikiPage.kb_id == kb_id)
            .all()
        )
        count = 0
        for page in pages:
            if document_id in (page.source_doc_ids or []):
                page.status = "stale"
                count += 1
        db.commit()
        return count

    def delete_kb_vectors(self, kb_id: int) -> None:
        """删除知识库时同步删除整个 collection，并让检索缓存失效"""
        self.vector_store.delete_kb(kb_id)
        from .retrieval_cache import retrieval_cache
        retrieval_cache.bump(kb_id)


document_service = DocumentService()
