"""文档管理路由：上传、列表、状态查询、删除、增量更新"""
import os
import threading

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from ..config import settings
from ..database import SessionLocal, get_db
from ..models import Document, User
from ..schemas import DocumentResponse
from ..services import document_service
from ..utils.deps import get_current_user, require_kb_role

router = APIRouter(tags=["文档"])


def _validate_file(file: UploadFile) -> str:
    """校验文件类型，返回扩展名"""
    ext = os.path.splitext(file.filename)[1].lower().lstrip(".")
    if ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型，仅支持：{', '.join(settings.allowed_extensions_list)}",
        )
    return ext


def _start_background_processing(doc_id: int) -> None:
    """后台处理文档：根据 ASYNC_MODE 走 Celery 队列或本地线程"""
    if settings.ASYNC_MODE == "celery":
        try:
            from ..tasks.document_tasks import process_document_task
            process_document_task.delay(doc_id)
            return
        except Exception as e:
            # Celery 不可用时降级为线程
            from ..utils.logger import get_logger
            get_logger(__name__).warning(f"Celery 提交失败，降级为线程：{e}")

    def _process_in_background():
        bg_db = SessionLocal()
        try:
            bg_doc = bg_db.query(Document).filter(Document.id == doc_id).first()
            if bg_doc:
                document_service.process_document(bg_db, bg_doc)
        finally:
            bg_db.close()

    thread = threading.Thread(target=_process_in_background, daemon=True)
    thread.start()


@router.post("/kb/{kb_id}/upload", response_model=DocumentResponse, summary="上传文档")
async def upload_document(
    kb_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 上传属于写操作：editor 及以上
    require_kb_role(db, kb_id, current_user, "editor")
    ext = _validate_file(file)

    # 校验文件大小
    content = await file.read()
    max_size = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    if len(content) > max_size:
        raise HTTPException(status_code=400, detail=f"文件大小不能超过 {settings.MAX_FILE_SIZE_MB}MB")

    # 保存文件
    stored_name, file_path, file_size = document_service.save_upload_file(
        content, file.filename
    )

    # 写入数据库
    document = Document(
        kb_id=kb_id,
        filename=file.filename,
        stored_filename=stored_name,
        file_path=file_path,
        file_size=file_size,
        file_type=ext,
        status="processing",
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    # 后台处理
    _start_background_processing(document.id)

    return DocumentResponse.model_validate(document)


@router.put("/docs/{doc_id}", response_model=DocumentResponse, summary="更新文档（重新上传，增量处理）")
async def update_document(
    doc_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    require_kb_role(db, doc.kb_id, current_user, "editor")
    ext = _validate_file(file)

    content = await file.read()
    max_size = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    if len(content) > max_size:
        raise HTTPException(status_code=400, detail=f"文件大小不能超过 {settings.MAX_FILE_SIZE_MB}MB")

    # 删除旧向量
    document_service.delete_document_vectors(doc.kb_id, doc_id)
    # Wiki 联动：引用该文档的页面先标记为 stale（重处理后自动重编译恢复）
    document_service.mark_wiki_stale_for_document(db, doc.kb_id, doc_id)
    # 删除旧磁盘文件
    if doc.file_path and os.path.exists(doc.file_path):
        try:
            os.remove(doc.file_path)
        except OSError:
            pass

    # 保存新文件
    stored_name, file_path, file_size = document_service.save_upload_file(
        content, file.filename
    )

    # 更新记录字段
    doc.filename = file.filename
    doc.stored_filename = stored_name
    doc.file_path = file_path
    doc.file_size = file_size
    doc.file_type = ext
    doc.status = "processing"
    doc.error_msg = ""
    doc.chunk_count = 0
    db.commit()
    db.refresh(doc)

    # 后台重新处理
    _start_background_processing(doc.id)

    return DocumentResponse.model_validate(doc)


@router.get("/kb/{kb_id}/docs", summary="文档列表（分页）")
def list_documents(
    kb_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_kb_role(db, kb_id, current_user, "viewer")
    query = db.query(Document).filter(Document.kb_id == kb_id)
    total = query.count()
    docs = query.order_by(Document.created_at.desc()) \
        .offset((page - 1) * page_size).limit(page_size).all()
    return {
        "total": total,
        "items": [DocumentResponse.model_validate(d).model_dump() for d in docs],
    }


@router.get("/docs/{doc_id}", response_model=DocumentResponse, summary="查询文档状态")
def get_document(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    require_kb_role(db, doc.kb_id, current_user, "viewer")
    return doc


@router.get("/docs/{doc_id}/preview", summary="文档预览内容")
def preview_document(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    文档预览：
    - 文本类（txt/md/docx）：返回解析后的文本内容，前端渲染
    - PDF：返回文件 URL，前端用 iframe/pdf.js 渲染
    """
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    require_kb_role(db, doc.kb_id, current_user, "viewer")

    file_url = f"/uploads/{doc.stored_filename}"
    if doc.file_type in ("txt", "md", "markdown", "docx", "doc"):
        # 文本类直接解析返回
        try:
            from ..services.document_parser import parse_document
            content = parse_document(doc.file_path)
        except Exception as e:
            content = f"文档解析失败：{e}"
        return {
            "filename": doc.filename,
            "file_type": doc.file_type,
            "content": content,
            "file_url": file_url,
        }
    # PDF 等：前端用 file_url 渲染
    return {
        "filename": doc.filename,
        "file_type": doc.file_type,
        "content": "",
        "file_url": file_url,
    }


@router.delete("/docs/{doc_id}", summary="删除文档")
def delete_document(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    require_kb_role(db, doc.kb_id, current_user, "editor")

    # 删除向量
    document_service.delete_document_vectors(doc.kb_id, doc_id)
    # Wiki 联动：清理页面来源，无来源的页面删除
    document_service.detach_document_from_wiki(db, doc.kb_id, doc_id)
    # 删除本地文件
    if doc.file_path and os.path.exists(doc.file_path):
        try:
            os.remove(doc.file_path)
        except OSError:
            pass
    # 删除数据库记录
    db.delete(doc)
    db.commit()
    return {"message": "删除成功"}
