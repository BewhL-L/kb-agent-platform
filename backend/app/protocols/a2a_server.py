"""
A2A（Agent2Agent）协议示例
让本系统的知识库 Agent 能被其他 A2A 客户端 / Agent 发现并调用：
- Agent Card：GET /a2a/.well-known/agent.json
- 发送消息：POST /a2a/（JSON-RPC，method=message/send）
为便于理解，这里同步执行并直接返回 Task，不依赖额外 SDK。
kb_id 必须显式放在 message.metadata.kb_id 中传入（不再默认取 1 号库）。

安全约定：
- POST 必须携带 Authorization: Bearer <A2A_TOKEN>（或 X-A2A-Token 头）
- A2A_TOKEN 为空时一律拒绝，避免默认配置下把内部知识库暴露到公网
"""
import secrets
import uuid
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request

from ..config import settings
from ..utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/a2a", tags=["A2A"])

AGENT_CARD = {
    "protocolVersion": "0.2.0",
    "name": "enterprise-kb-agent",
    "description": "企业知识库问答 Agent（RAG + 工具调用）",
    "url": settings.A2A_PUBLIC_URL,
    "version": "1.0.0",
    "capabilities": {"streaming": False, "pushNotifications": False},
    "defaultInputModes": ["text"],
    "defaultOutputModes": ["text"],
    "skills": [
        {
            "id": "kb-qa",
            "name": "知识库问答",
            "description": "基于企业知识库回答问题并给出依据",
            "tags": ["rag", "knowledge-base"],
        }
    ],
}


def _check_token(authorization: Optional[str], x_a2a_token: Optional[str]) -> None:
    """校验调用方令牌：常量时间比较，避免时序侧信道"""
    expected = (settings.A2A_TOKEN or "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="A2A 未启用：请在 .env 中配置 A2A_TOKEN",
        )
    provided = ""
    if authorization and authorization.lower().startswith("bearer "):
        provided = authorization[7:].strip()
    elif x_a2a_token:
        provided = x_a2a_token.strip()
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=401,
            detail="A2A 鉴权失败",
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.get("/.well-known/agent.json")
async def agent_card():
    """Agent 描述文件：属于公开元数据，不要求令牌；关闭能力时返回 404"""
    if not settings.A2A_ENABLED:
        raise HTTPException(status_code=404, detail="A2A 未启用")
    return AGENT_CARD


@router.post("/")
async def rpc(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_a2a_token: Optional[str] = Header(None),
):
    body = await request.json()
    method = body.get("method")
    params = body.get("params", {})
    req_id = body.get("id")

    if not settings.A2A_ENABLED:
        return _err(req_id, -32601, "A2A disabled")
    _check_token(authorization, x_a2a_token)

    if method in ("message/send", "message/stream"):
        text, kb_id = _extract(params)
        if not text:
            return _err(req_id, -32602, "message.parts 中缺少文本内容")
        kb, error = _resolve_kb(kb_id)
        if error:
            return _err(req_id, -32602, error)
        answer = await _answer(text, kb.id)
        return _ok(req_id, _task(answer))
    if method == "tasks/get":
        return _ok(req_id, {"id": params.get("id"), "status": {"state": "completed"}})
    return _err(req_id, -32601, f"Method not found: {method}")


def _extract(params: dict):
    msg = params.get("message", {})
    parts = msg.get("parts", [])
    text = "".join(p.get("text", "") for p in parts if "text" in p) or msg.get("text", "")
    metadata = msg.get("metadata", {}) or {}
    kb_id = metadata.get("kb_id")
    return text, kb_id


def _resolve_kb(kb_id):
    """显式校验 kb_id：必须传、必须存在，不再回落到 1 号库"""
    if kb_id is None:
        return None, "缺少 metadata.kb_id，A2A 调用必须显式指定知识库"
    try:
        kb_id = int(kb_id)
    except (TypeError, ValueError):
        return None, "metadata.kb_id 必须是整数"

    from ..database import SessionLocal
    from ..models.knowledge_base import KnowledgeBase

    db = SessionLocal()
    try:
        kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
        if not kb:
            return None, f"知识库 {kb_id} 不存在"
        return kb, None
    finally:
        db.close()


async def _answer(text: str, kb_id: int) -> str:
    from ..services.rag_service import rag_service

    r = await rag_service.chat(kb_id, text)
    return r["answer"]


def _task(output: str) -> dict:
    return {
        "id": uuid.uuid4().hex,
        "status": {"state": "completed"},
        "artifacts": [{"parts": [{"text": output}]}],
    }


def _ok(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}
