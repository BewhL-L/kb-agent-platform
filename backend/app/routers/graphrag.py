"""
GraphRAG 路由
- 构建图谱（后台线程）、查询构建状态
- 获取图谱数据（节点+边，供前端可视化）
- 局部检索 / 全局检索
"""
import threading

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import settings
from ..database import SessionLocal, get_db
from ..models import User
from ..models.graph_community import GraphCommunity
from ..models.graph_entity import GraphEntity
from ..models.graph_relation import GraphRelation
from ..schemas.graphrag import GraphBuildRequest, GraphSearchRequest
from ..services.graph_builder import graph_builder
from ..services.graph_retriever import graph_retriever
from ..utils.deps import get_current_user, require_kb_role
from ..utils.logger import get_logger

router = APIRouter(prefix="/graphrag", tags=["GraphRAG"])
logger = get_logger(__name__)


def require_graphrag_enabled() -> None:
    """GRAPHRAG_ENABLED 总开关：关闭后建图与检索接口统一返回 503（前端可据此隐藏入口）"""
    if not settings.GRAPHRAG_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="GraphRAG 已关闭（GRAPHRAG_ENABLED=false）",
        )

# 构建状态：kb_id -> "building" / "done" / "failed"
_build_status: dict = {}


def _build_in_background(kb_id: int, doc_ids):
    db = SessionLocal()
    try:
        _build_status[kb_id] = "building"
        graph_builder.build_graph(db, kb_id, doc_ids)
        _build_status[kb_id] = "done"
    except Exception as e:
        logger.error(f"图谱构建失败：{e}")
        _build_status[kb_id] = "failed"
    finally:
        db.close()


@router.post(
    "/kb/{kb_id}/build",
    summary="构建知识图谱",
    dependencies=[Depends(require_graphrag_enabled)],
)
def build_graph(
    kb_id: int,
    data: GraphBuildRequest = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_kb_role(db, kb_id, current_user, "editor")
    doc_ids = data.doc_ids if data else None

    # 已在构建中则不重复启动
    if _build_status.get(kb_id) == "building":
        return {"status": "building", "message": "图谱正在构建中"}

    thread = threading.Thread(
        target=_build_in_background, args=(kb_id, doc_ids), daemon=True
    )
    thread.start()
    return {"status": "building", "message": "图谱构建已开始，请稍后查询状态"}


@router.get("/kb/{kb_id}/status", summary="查询图谱构建状态")
def graph_status(
    kb_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_kb_role(db, kb_id, current_user, "viewer")
    return {
        "status": _build_status.get(kb_id, "idle"),
        "entities": db.query(GraphEntity).filter(GraphEntity.kb_id == kb_id).count(),
        "relations": db.query(GraphRelation).filter(GraphRelation.kb_id == kb_id).count(),
        "communities": db.query(GraphCommunity).filter(GraphCommunity.kb_id == kb_id).count(),
    }


@router.get("/kb/{kb_id}/graph", summary="获取图谱节点与边（可视化）")
def get_graph(
    kb_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_kb_role(db, kb_id, current_user, "viewer")
    entities = db.query(GraphEntity).filter(GraphEntity.kb_id == kb_id).all()
    relations = db.query(GraphRelation).filter(GraphRelation.kb_id == kb_id).all()
    communities = db.query(GraphCommunity).filter(GraphCommunity.kb_id == kb_id).all()

    nodes = [
        {
            "id": e.id, "name": e.name, "entity_type": e.entity_type,
            "summary": e.summary, "degree": e.degree,
            "community_id": e.community_id,
        }
        for e in entities
    ]
    edges = [
        {
            "id": r.id, "source_id": r.source_entity_id,
            "target_id": r.target_entity_id, "source": r.source_name,
            "target": r.target_name, "relation_type": r.relation_type,
        }
        for r in relations
    ]
    return {
        "nodes": nodes,
        "edges": edges,
        "communities": [
            {"id": c.id, "title": c.title, "summary": c.summary,
             "entity_count": c.entity_count}
            for c in communities
        ],
    }


@router.post(
    "/kb/{kb_id}/local",
    summary="图谱局部检索",
    dependencies=[Depends(require_graphrag_enabled)],
)
async def local_search(
    kb_id: int,
    data: GraphSearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_kb_role(db, kb_id, current_user, "viewer")
    return await graph_retriever.local_search(kb_id, data.question)


@router.post(
    "/kb/{kb_id}/global",
    summary="图谱全局检索（map-reduce）",
    dependencies=[Depends(require_graphrag_enabled)],
)
async def global_search(
    kb_id: int,
    data: GraphSearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_kb_role(db, kb_id, current_user, "viewer")
    return await graph_retriever.global_search(kb_id, data.question)
