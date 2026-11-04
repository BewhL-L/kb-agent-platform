"""智能问答路由：普通问答 + 流式问答（RAG / Agentic RAG）"""
import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..database import SessionLocal, get_db
from ..models import Conversation, KnowledgeBase, Message, User
from ..schemas import ChatRequest, FeedbackCreate, GlobalChatRequest
from ..services import AgentService, RAGService, agent_service, rag_service
from ..utils.deps import get_current_user, require_kb_role
from ..utils.logger import get_logger

router = APIRouter(tags=["智能问答"])

logger = get_logger(__name__)

# 工具名 -> 前端状态文案
_TOOL_LABEL = {
    "search_knowledge_base": "正在检索知识库…",
    "calculator": "正在计算…",
    "get_current_time": "正在获取时间…",
}


def _get_services(model_name: str):
    """根据用户当前选择的模型构建服务；为空则用全局单例"""
    if model_name:
        from ..services.llm_service import get_llm_service
        from ..services.vector_store import get_vector_store
        llm = get_llm_service(model_name)
        return (
            RAGService(llm=llm, vector_store=get_vector_store()),
            AgentService(llm=llm),
        )
    return rag_service, agent_service


@router.post("/chat", summary="普通问答（非流式）")
async def chat(
    data: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_kb_role(db, data.kb_id, current_user, "viewer")
    conv = _get_or_create_conv(db, data, current_user.id)
    history = _get_history(db, conv.id)

    # 保存用户消息
    user_msg = Message(conversation_id=conv.id, role="user", content=data.question)
    db.add(user_msg)
    db.commit()

    rag, agent = _get_services(current_user.current_model)

    # Agent 主导：由 Agent 自主决定检索 / 计算；否则走朴素 RAG
    if data.use_agent:
        result = await agent.chat(
            history + [{"role": "user", "content": data.question}],
            kb_id=data.kb_id,
        )
    else:
        result = await rag.chat(
            data.kb_id, data.question, history, conv.long_memory
        )

    answer = result["answer"]
    sources = result["sources"]

    # 溯源校验：这句话在检索片段里有没有依据（零成本、可复现，见 grounding_service）
    grounding = None
    if settings.GROUNDING_ENABLED:
        from ..services.grounding_service import grounding_service
        grounding = grounding_service.verify(answer, sources)

    # 保存 AI 消息
    ai_msg = Message(
        conversation_id=conv.id,
        role="assistant",
        content=answer,
        sources=json.dumps(sources, ensure_ascii=False),
    )
    db.add(ai_msg)
    if conv.title == "新对话":
        conv.title = data.question[:30]
    db.commit()
    db.refresh(ai_msg)

    # 更新长期记忆（把更早的对话压缩成摘要）
    from ..services.memory_service import memory_service
    memory_service.update_memory(db, conv)

    return {
        "conversation_id": conv.id,
        "answer": answer,
        "sources": sources,
        "grounding": grounding,
        "message_id": ai_msg.id,
    }


@router.post("/chat/reasoning", summary="推理增强问答（含思考链）")
async def reasoning_chat(
    data: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    推理模型问答：检索后模型先"思考"再回答。
    - 返回 reasoning（思考链），前端折叠展示
    - use_reasoning=false 时自动判断是否需要推理
    """
    require_kb_role(db, data.kb_id, current_user, "viewer")
    conv = _get_or_create_conv(db, data, current_user.id)
    history = _get_history(db, conv.id)

    # 保存用户消息
    user_msg = Message(conversation_id=conv.id, role="user", content=data.question)
    db.add(user_msg)
    db.commit()

    # 推理模型固定走推理服务（不随用户选择的普通模型切换）
    rag, _ = _get_services(current_user.current_model)
    result = await rag.reasoning_chat(
        data.kb_id, data.question, history, conv.long_memory,
        force=data.use_reasoning,
    )
    answer = result["answer"]
    sources = result["sources"]
    reasoning = result.get("reasoning", "")

    # 保存 AI 消息（思考链不入库，仅保存最终答案）
    ai_msg = Message(
        conversation_id=conv.id, role="assistant", content=answer,
        sources=json.dumps(sources, ensure_ascii=False),
    )
    db.add(ai_msg)
    if conv.title == "新对话":
        conv.title = data.question[:30]
    db.commit()
    db.refresh(ai_msg)

    from ..services.memory_service import memory_service
    memory_service.update_memory(db, conv)

    grounding = None
    if settings.GROUNDING_ENABLED:
        from ..services.grounding_service import grounding_service
        grounding = grounding_service.verify(answer, sources)

    return {
        "conversation_id": conv.id,
        "answer": answer,
        "reasoning": reasoning,
        "reasoned": result.get("reasoned", False),
        "sources": sources,
        "grounding": grounding,
        "message_id": ai_msg.id,
    }


@router.post("/chat/stream", summary="流式问答（SSE 打字机效果）")
async def chat_stream(
    data: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_kb_role(db, data.kb_id, current_user, "viewer")
    conv = _get_or_create_conv(db, data, current_user.id)
    history = _get_history(db, conv.id)

    # 保存用户消息
    user_msg = Message(conversation_id=conv.id, role="user", content=data.question)
    db.add(user_msg)
    db.commit()

    # 预创建 AI 消息占位
    ai_msg = Message(conversation_id=conv.id, role="assistant", content="")
    db.add(ai_msg)
    if conv.title == "新对话":
        conv.title = data.question[:30]
    db.commit()
    db.refresh(ai_msg)

    message_id = ai_msg.id
    conv_id = conv.id
    use_agent = data.use_agent
    model_name = current_user.current_model

    async def generate():
        full_answer = ""
        sources_data = []
        try:
            rag, agent = _get_services(model_name)

            if use_agent:
                # 流式 Agentic RAG：工具过程事件 + 最终答案流式
                async for event in agent.chat_stream(
                    history + [{"role": "user", "content": data.question}],
                    kb_id=data.kb_id,
                ):
                    if event.get("tool"):
                        label = _TOOL_LABEL.get(event["tool"], "处理中…")
                        yield f"data: {json.dumps({'status': label}, ensure_ascii=False)}\n\n"
                    elif event.get("token"):
                        full_answer += event["token"]
                        yield f"data: {json.dumps({'token': event['token']}, ensure_ascii=False)}\n\n"
                    elif event.get("done"):
                        sources_data = event["sources"]
            else:
                # 朴素 RAG 流式
                async for chunk in rag.chat_stream(
                    data.kb_id, data.question, history, conv.long_memory
                ):
                    if chunk.startswith("[[SOURCES]]"):
                        end = chunk.find("[[/SOURCES]]")
                        if end != -1:
                            sources_json = chunk[len("[[SOURCES]]"):end]
                            sources_data = json.loads(sources_json)
                            remainder = chunk[end + len("[[/SOURCES]]\n\n"):]
                            if remainder:
                                full_answer += remainder
                                yield f"data: {json.dumps({'token': remainder}, ensure_ascii=False)}\n\n"
                        continue
                    full_answer += chunk
                    yield f"data: {json.dumps({'token': chunk}, ensure_ascii=False)}\n\n"

            # 溯源校验：非流式的 /chat 与 /chat/reasoning 一直有，流式此前完全没有。
            # 而前端默认走的就是流式——等于"这句话有没有出处"只在一个用户不用的接口里存在。
            grounding = None
            if settings.GROUNDING_ENABLED and full_answer:
                try:
                    from ..services.grounding_service import grounding_service
                    grounding = grounding_service.verify(full_answer, sources_data)
                except Exception as e:
                    logger.warning(f"流式溯源校验失败，本次跳过：{e}")

            # 更新数据库消息
            _db = SessionLocal()
            try:
                msg = _db.query(Message).filter(Message.id == message_id).first()
                if msg:
                    msg.content = full_answer
                    msg.sources = json.dumps(sources_data, ensure_ascii=False)
                conv_obj = _db.query(Conversation).filter(Conversation.id == conv_id).first()
                if conv_obj:
                    # 更新长期记忆
                    from ..services.memory_service import memory_service
                    memory_service.update_memory(_db, conv_obj)
                _db.commit()
            finally:
                _db.close()

            yield f"data: {json.dumps({'done': True, 'conversation_id': conv_id, 'message_id': message_id, 'sources': sources_data, 'grounding': grounding}, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            # 客户端主动断开（关页面、切走、网络断）——这条**走不到下面那个 except**：
            # Python 3.8+ 的 CancelledError 继承 BaseException，不是 Exception。
            # 不单独兜住，用户看到的就是一条点不开、删不掉的空白气泡。
            _persist_stream_failure(message_id, full_answer, sources_data)
            raise  # 取消必须向上传播，否则 Starlette 无法正确收尾
        except Exception as e:
            # 两点必须做，否则一次异常会留下两个伤疤：
            #   1. 落库。预建的 assistant 消息不写回就会永远停在空 content，
            #      会话里出现一条点不开、删不掉的空白气泡。
            #   2. 把 conversation_id 带出去。前端拿不到它，下次提问就会新建会话，
            #      一次异常变成两条会话记录。
            logger.exception(f"流式问答中断（message_id={message_id}）：{e}")
            _persist_stream_failure(message_id, full_answer, sources_data)
            yield f"data: {json.dumps({'error': str(e), 'conversation_id': conv_id, 'message_id': message_id}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/chat/global", summary="跨知识库问答")
async def global_chat(
    data: GlobalChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """一次提问检索多个知识库（不传 kb_ids 则检索当前用户所有知识库）"""
    if data.kb_ids:
        kb_ids = data.kb_ids
    else:
        # 当前用户的所有知识库
        rows = db.query(KnowledgeBase.id).filter(
            KnowledgeBase.user_id == current_user.id
        ).all()
        kb_ids = [r[0] for r in rows]

    if not kb_ids:
        raise HTTPException(status_code=400, detail="没有可检索的知识库")

    # 校验知识库归属
    for kb_id in kb_ids:
        require_kb_role(db, kb_id, current_user, "viewer")

    result = await rag_service.chat_across_kbs(kb_ids, data.question)
    return result


@router.post("/feedback", summary="回答点赞/点踩")
def submit_feedback(
    data: FeedbackCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    msg = db.query(Message).filter(Message.id == data.message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="消息不存在")
    conv = db.query(Conversation).filter(Conversation.id == msg.conversation_id).first()
    if conv.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权操作")
    msg.feedback = data.feedback
    db.commit()
    return {"message": "反馈成功"}


def _persist_stream_failure(message_id: int, partial: str, sources_data: list) -> None:
    """流式生成异常/中断时把已产出的部分写回数据库，避免留下空白消息。

    只写用户真正看到过的内容（partial）。为什么不全填一句"生成失败"：
    这条消息之后会作为多轮上下文被取回，掺入工程标记只会污染后续 Prompt。
    真正的失败原因在日志里（`logger.exception`）。

    唯一例外是 `partial` 为空——一个字都没产出时，气泡里必须有个占位，
    否则前端渲染出来是一片空白，用户以为是自己点坏了。
    """
    _db = SessionLocal()
    try:
        msg = _db.query(Message).filter(Message.id == message_id).first()
        if msg is None:
            return
        msg.content = partial or "（本次回答生成中断，未产生内容）"
        msg.sources = json.dumps(sources_data or [], ensure_ascii=False)
        _db.commit()
    except Exception as e:
        # 回写失败不能再抛——外层已经在处理原始异常了
        logger.warning(f"流式失败回写数据库时再次失败（message_id={message_id}）：{e}")
    finally:
        _db.close()


def _get_or_create_conv(db: Session, data: ChatRequest, user_id: int) -> Conversation:
    if data.conversation_id:
        conv = db.query(Conversation).filter(
            Conversation.id == data.conversation_id,
            Conversation.user_id == user_id,
        ).first()
        if conv:
            return conv
    conv = Conversation(user_id=user_id, kb_id=data.kb_id, title="新对话")
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


def _get_history(db: Session, conv_id: int) -> list:
    """取最近 12 条消息作为多轮上下文。

    这里必须过 `neutralize`：历史消息是**用户原文存库后再取回**的，
    如果某一轮输入里带了 `<|im_start|>system` 之类角色标记，它会被原样存下来，
    之后**每一轮**都重新注入到 system 消息附近——这是一次成功、永久生效的注入。
    `guard.py` 原本只覆盖了检索内容，漏掉了这条最容易被反复利用的路径。

    取舍：只在「读出」时清洗，不动机器里的原始消息，这样用户在界面上看到的仍是自己写的内容；
    代价是那 4 个角色标记在展示层不会被过滤。对知识库问答来说这是可接受的。
    """
    from ..utils.guard import neutralize

    msgs = db.query(Message).filter(
        Message.conversation_id == conv_id
    ).order_by(Message.id.desc()).limit(12).all()
    msgs.reverse()
    return [
        {"role": m.role, "content": neutralize(m.content)}
        for m in msgs
        if m.content
    ]
