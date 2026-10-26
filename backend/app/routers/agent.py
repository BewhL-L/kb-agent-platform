"""AI Agent 路由：工具调用、多 Agent 协作、编排演示"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..models import User
from ..services import agent_service
from ..services.agent_service import TOOL_DEFINITIONS, AgentService
from ..utils.deps import get_current_user

router = APIRouter(prefix="/agent", tags=["AI Agent"])


class AgentRequest(BaseModel):
    """Agent 对话请求"""
    question: str = Field(..., min_length=1, max_length=1000)
    history: list[dict] = Field(default_factory=list, description="历史对话")
    kb_id: Optional[int] = None


class MultiAgentRequest(BaseModel):
    """多 Agent 协作请求"""
    question: str = Field(..., min_length=1, max_length=1000)
    kb_id: int
    # 编排后端：native（原生状态机，默认）/ langgraph-multi-agent /
    # langgraph-react / langgraph-plan-execute
    backend: str = "native"


@router.get("/tools", summary="获取可用工具列表")
def list_tools(current_user: User = Depends(get_current_user)):
    """返回当前 Agent 支持的所有工具定义"""
    return {
        "tools": [
            {
                "name": t["function"]["name"],
                "description": t["function"]["description"],
            }
            for t in TOOL_DEFINITIONS
        ]
    }


@router.post("/chat", summary="Agent 对话（自动工具调用）")
async def agent_chat(
    data: AgentRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Agent 自动判断是否调用工具：
    - 问"现在几点" -> 自动调用 get_current_time
    - 问"帮我算 100*23" -> 自动调用 calculator
    - 传 kb_id 时可检索知识库
    """
    if current_user.current_model:
        from ..services.llm_service import get_llm_service
        agent = AgentService(llm=get_llm_service(current_user.current_model))
    else:
        agent = agent_service

    messages = data.history + [{"role": "user", "content": data.question}]
    result = await agent.chat(messages, kb_id=data.kb_id)
    return {"answer": result["answer"], "sources": result["sources"]}


@router.post("/multi-agent", summary="多 Agent 协作（含步骤可视化）")
async def multi_agent(
    data: MultiAgentRequest,
    current_user: User = Depends(get_current_user),
):
    """
    多 Agent 分工协作：
    - backend=native：原生状态机（planner/researcher/writer/supervisor），
      无需安装 langgraph，返回每一步（steps）供前端展示
    - backend=langgraph-*：基于 LangGraph 的编排（需安装 langgraph）
    """
    # 校验知识库权限（viewer 即可问答）
    if data.kb_id:
        from ..database import SessionLocal
        from ..utils.deps import require_kb_role
        db = SessionLocal()
        try:
            require_kb_role(db, data.kb_id, current_user, "viewer")
        finally:
            db.close()

    # 原生状态机（默认，含步骤）
    if data.backend in ("native", "native-multi-agent"):
        from ..services.native_multi_agent import native_multi_agent
        return await native_multi_agent.run(data.question, data.kb_id)

    # LangGraph 编排
    try:
        from ..orchestration import get_orchestrator
        runner = get_orchestrator(data.backend)
    except (RuntimeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    if runner is None:
        # 传了 native 但走到这里的兜底
        from ..services.native_multi_agent import native_multi_agent
        return await native_multi_agent.run(data.question, data.kb_id)

    answer = await runner(data.question, data.kb_id)
    return {"answer": answer, "steps": [], "backend": data.backend}
