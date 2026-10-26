"""
网站嵌入路由（公开、免登录）
- GET  /embed/{code}       返回自包含的聊天窗口页面（供 iframe 嵌入）
- POST /embed/{code}/chat  公开问答接口（匿名访客）
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import KnowledgeBase
from ..services import rag_service
from ..utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["网站嵌入"], include_in_schema=False)


class EmbedChatRequest(BaseModel):
    """嵌入页问答请求"""
    question: str = Field(..., min_length=1, max_length=500)
    history: list[dict] = Field(default_factory=list)


def _get_kb_by_code(db: Session, code: str) -> KnowledgeBase:
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.embed_code == code).first()
    if not kb:
        raise HTTPException(status_code=404, detail="嵌入链接无效")
    return kb


@router.get("/embed/{code}", response_class=HTMLResponse, summary="嵌入聊天窗口页面")
def embed_page(code: str, db: Session = Depends(get_db)):
    kb = _get_kb_by_code(db, code)
    html = EMBED_HTML.replace("__CODE__", code).replace("__TITLE__", kb.name)
    return HTMLResponse(content=html)


@router.post("/embed/{code}/chat", summary="嵌入公开问答接口")
async def embed_chat(code: str, data: EmbedChatRequest, db: Session = Depends(get_db)):
    kb = _get_kb_by_code(db, code)
    try:
        result = await rag_service.chat(kb.id, data.question, data.history)
        return {"answer": result["answer"], "sources": result["sources"]}
    except Exception as e:
        logger.error(f"嵌入问答失败：{e}")
        return {"answer": "服务暂时不可用，请稍后再试。", "sources": []}


# ============ 自包含嵌入页面（原生 HTML/CSS/JS，无外部依赖） ============

EMBED_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>__TITLE__</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  html, body { height: 100%; font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; }
  body { display: flex; flex-direction: column; background: #f5f7fa; }
  .header {
    background: linear-gradient(135deg, #4f46e5, #6366f1);
    color: #fff; padding: 14px 18px; font-size: 15px; font-weight: 600;
    box-shadow: 0 2px 8px rgba(79,70,229,.25);
  }
  .messages { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 12px; }
  .msg { max-width: 82%; padding: 10px 14px; border-radius: 12px; font-size: 14px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; }
  .msg.bot { background: #fff; color: #333; align-self: flex-start; border-bottom-left-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
  .msg.user { background: #4f46e5; color: #fff; align-self: flex-end; border-bottom-right-radius: 4px; }
  .msg .src { margin-top: 8px; padding-top: 8px; border-top: 1px solid #eee; font-size: 12px; color: #888; }
  .typing { color: #999; font-size: 13px; align-self: flex-start; padding: 6px 12px; }
  .input-bar { display: flex; gap: 8px; padding: 12px; background: #fff; border-top: 1px solid #eee; }
  .input-bar input {
    flex: 1; border: 1px solid #dcdfe6; border-radius: 20px; padding: 10px 16px;
    font-size: 14px; outline: none;
  }
  .input-bar input:focus { border-color: #6366f1; }
  .input-bar button {
    border: none; background: #4f46e5; color: #fff; border-radius: 20px;
    padding: 0 18px; font-size: 14px; cursor: pointer;
  }
  .input-bar button:disabled { background: #a5b4fc; cursor: not-allowed; }
</style>
</head>
<body>
  <div class="header">__TITLE__</div>
  <div class="messages" id="messages">
    <div class="msg bot">你好，我是知识库助手，有什么可以帮你的吗？</div>
  </div>
  <div class="input-bar">
    <input id="input" placeholder="请输入问题..." autocomplete="off">
    <button id="send">发送</button>
  </div>
<script>
  const code = "__CODE__";
  const messagesEl = document.getElementById("messages");
  const input = document.getElementById("input");
  const sendBtn = document.getElementById("send");
  let history = [];

  function addMsg(text, role, sources) {
    const el = document.createElement("div");
    el.className = "msg " + role;
    el.textContent = text;
    if (sources && sources.length) {
      const src = document.createElement("div");
      src.className = "src";
      const names = [...new Set(sources.map(s => s.document_name))];
      src.textContent = "参考来源：" + names.join("、");
      el.appendChild(src);
    }
    messagesEl.appendChild(el);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return el;
  }

  async function send() {
    const question = input.value.trim();
    if (!question) return;
    addMsg(question, "user");
    history.push({ role: "user", content: question });
    input.value = "";
    sendBtn.disabled = true;

    const typing = document.createElement("div");
    typing.className = "typing";
    typing.textContent = "正在思考...";
    messagesEl.appendChild(typing);
    messagesEl.scrollTop = messagesEl.scrollHeight;

    try {
      const res = await fetch("/embed/" + code + "/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, history }),
      });
      const data = await res.json();
      typing.remove();
      addMsg(data.answer, "bot", data.sources);
      history.push({ role: "assistant", content: data.answer });
    } catch (e) {
      typing.remove();
      addMsg("网络异常，请稍后再试。", "bot");
    }
    sendBtn.disabled = false;
    input.focus();
  }

  sendBtn.addEventListener("click", send);
  input.addEventListener("keydown", e => { if (e.key === "Enter") send(); });
</script>
</body>
</html>
"""
