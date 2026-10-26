"""
LLM Wiki 管理路由
- 页面列表 / 详情 / 删除
- 手动触发知识库重编译
- 页面关联图谱数据
"""
import threading

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..models import User, WikiPage
from ..schemas import (
    WikiGraphEdge,
    WikiGraphNode,
    WikiGraphResponse,
    WikiPageEditRequest,
    WikiPageResponse,
    WikiRecompileResponse,
    WikiRollbackResponse,
    WikiVersionResponse,
)
from ..utils.deps import get_current_user, require_kb_role

router = APIRouter(prefix="/wiki", tags=["LLM Wiki"])


def _start_background_recompile(kb_id: int) -> None:
    """后台线程执行知识库重编译"""
    def _recompile_in_background():
        bg_db = SessionLocal()
        try:
            from ..wiki import wiki_compiler
            wiki_compiler.recompile_kb(bg_db, kb_id)
        except Exception as e:
            from ..utils.logger import get_logger
            get_logger(__name__).error(f"知识库 {kb_id} 重编译失败：{e}")
        finally:
            bg_db.close()

    thread = threading.Thread(target=_recompile_in_background, daemon=True)
    thread.start()


@router.get("/kb/{kb_id}/pages", summary="Wiki 页面列表")
def list_pages(
    kb_id: int,
    entity_type: str = Query("", description="按实体类型筛选"),
    keyword: str = Query("", description="按标题/摘要关键词筛选"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_kb_role(db, kb_id, current_user, "viewer")
    query = db.query(WikiPage).filter(WikiPage.kb_id == kb_id)
    if entity_type:
        query = query.filter(WikiPage.entity_type == entity_type)
    if keyword:
        query = query.filter(
            (WikiPage.title.contains(keyword)) | (WikiPage.summary.contains(keyword))
        )
    pages = query.order_by(WikiPage.updated_at.desc()).all()

    items = []
    for p in pages:
        items.append({
            "id": p.id,
            "title": p.title,
            "summary": p.summary,
            "entity_type": p.entity_type,
            "kb_id": p.kb_id,
            "conflict_count": len(p.conflict_flags or []),
            "status": p.status,
            "version": p.version,
            "compiled_at": p.compiled_at,
        })
    return {"total": len(items), "items": items}


@router.get("/pages/{page_id}", response_model=WikiPageResponse, summary="Wiki 页面详情")
def get_page(
    page_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    page = db.query(WikiPage).filter(WikiPage.id == page_id).first()
    if not page:
        raise HTTPException(status_code=404, detail="页面不存在")
    require_kb_role(db, page.kb_id, current_user, "viewer")
    return page


@router.post("/kb/{kb_id}/recompile", response_model=WikiRecompileResponse, summary="重编译知识库")
def recompile_kb(
    kb_id: int,
    wait: bool = Query(False, description="是否等待编译完成（默认后台执行）"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_kb_role(db, kb_id, current_user, "editor")
    if wait:
        from ..wiki import wiki_compiler
        stats = wiki_compiler.recompile_kb(db, kb_id)
        return WikiRecompileResponse(
            message="重编译完成",
            created=stats["created"],
            updated=stats["updated"],
            failed=stats["failed"],
        )
    # 后台执行
    _start_background_recompile(kb_id)
    return WikiRecompileResponse(message="重编译已在后台启动，请稍后刷新查看")


@router.get("/kb/{kb_id}/graph", response_model=WikiGraphResponse, summary="Wiki 关联图谱")
def get_graph(
    kb_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_kb_role(db, kb_id, current_user, "viewer")
    pages = db.query(WikiPage).filter(WikiPage.kb_id == kb_id).all()

    nodes = [
        WikiGraphNode(id=p.id, title=p.title, entity_type=p.entity_type)
        for p in pages
    ]
    edges = []
    valid_ids = {p.id for p in pages}
    seen = set()
    for p in pages:
        for related_id in (p.related_page_ids or []):
            if related_id in valid_ids:
                # 无向边去重
                edge_key = tuple(sorted((p.id, related_id)))
                if edge_key not in seen:
                    seen.add(edge_key)
                    edges.append(WikiGraphEdge(source=edge_key[0], target=edge_key[1]))
    return WikiGraphResponse(nodes=nodes, edges=edges)


@router.put("/pages/{page_id}", response_model=WikiPageResponse, summary="人工编辑 Wiki 页面")
def edit_page(
    page_id: int,
    body: WikiPageEditRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    page = db.query(WikiPage).filter(WikiPage.id == page_id).first()
    if not page:
        raise HTTPException(status_code=404, detail="页面不存在")
    require_kb_role(db, page.kb_id, current_user, "editor")

    from ..wiki import page_manager
    updated = page_manager.manual_edit(
        db,
        page,
        content=body.content,
        summary=body.summary,
        editor_id=current_user.id,
    )
    # 编辑后重算双向链接
    try:
        from ..wiki import linker
        linker.update_relations(db, page.kb_id)
    except Exception:
        pass
    return updated


@router.get("/pages/{page_id}/versions", summary="Wiki 页面历史版本列表")
def list_versions(
    page_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    page = db.query(WikiPage).filter(WikiPage.id == page_id).first()
    if not page:
        raise HTTPException(status_code=404, detail="页面不存在")
    require_kb_role(db, page.kb_id, current_user, "viewer")

    from ..wiki.version_service import version_service
    versions = version_service.list_versions(db, page_id)
    return {
        "total": len(versions),
        "items": [WikiVersionResponse.model_validate(v).model_dump() for v in versions],
    }


@router.post(
    "/pages/{page_id}/rollback/{version_id}",
    response_model=WikiRollbackResponse,
    summary="回滚 Wiki 页面到指定历史版本",
)
def rollback_page(
    page_id: int,
    version_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    page = db.query(WikiPage).filter(WikiPage.id == page_id).first()
    if not page:
        raise HTTPException(status_code=404, detail="页面不存在")
    require_kb_role(db, page.kb_id, current_user, "editor")

    from ..wiki.version_service import version_service
    result = version_service.rollback(
        db, page, version_id, editor_id=current_user.id
    )
    if not result:
        raise HTTPException(status_code=404, detail="指定的历史版本不存在")
    return WikiRollbackResponse(
        message="回滚成功",
        current_version=result.version,
    )


@router.delete("/pages/{page_id}", summary="删除 Wiki 页面")
def delete_page(
    page_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    page = db.query(WikiPage).filter(WikiPage.id == page_id).first()
    if not page:
        raise HTTPException(status_code=404, detail="页面不存在")
    require_kb_role(db, page.kb_id, current_user, "editor")
    kb_id = page.kb_id
    db.delete(page)
    db.commit()
    # 重算链接，清理其他页面中指向该页的关联
    try:
        from ..wiki import linker
        linker.update_relations(db, kb_id)
    except Exception:
        pass
    return {"message": "删除成功"}
