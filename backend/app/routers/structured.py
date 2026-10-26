"""结构化回答路由：同一问题的三种呈现（要点 / 对比表 / 时间线）"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas.structured import StructuredRequest, StructuredResponse
from ..services import structured_service
from ..services.llm_service import get_llm_service
from ..utils.deps import get_current_user, require_kb_role

router = APIRouter(prefix="/structured", tags=["结构化回答"])


@router.post("/generate", response_model=StructuredResponse, summary="按模板生成结构化回答")
async def generate_structured(
    data: StructuredRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    - 传 kb_id：先按 RAG 链路检索，再把资料交给模型（回答有依据）
    - 不传 kb_id：纯生成（用于对比"有资料 / 无资料"的差别）
    - 模型输出不合法 JSON 时降级为 bullets，并置 degraded=true，接口永远 200
    """
    context = ""
    if data.kb_id is not None:
        require_kb_role(db, data.kb_id, current_user, "viewer")
        from ..services.rag_service import rag_service

        sources = await rag_service.aretrieve(data.kb_id, data.question)
        context = "\n\n".join(
            f"【资料{i}】{s['text']}" for i, s in enumerate(sources, 1)
        )

    llm = get_llm_service(current_user.current_model)
    result, degraded, raw = await structured_service.generate(
        llm, data.question, data.template, context
    )
    return StructuredResponse(
        template=data.template,
        result=result,
        raw=raw[:2000],
        degraded=degraded,
    )
