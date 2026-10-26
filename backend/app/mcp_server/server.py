"""
MCP Server 核心
把知识库能力以标准 MCP 工具暴露，外部 MCP 客户端（Claude Desktop、Cursor、IDE、其他 Agent）可直接调用：
- list_knowledge_bases：列出知识库
- search_knowledge_base：检索资料片段
- ask_knowledge_base：RAG 问答（带来源）
- get_current_time：当前时间
MCP SDK 为可选依赖，运行时才导入。
"""
import asyncio
import json

from ..utils.logger import get_logger

logger = get_logger(__name__)


def _run(coro):
    return asyncio.run(coro)


def build_server(host: str = "0.0.0.0", port: int = 8001):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as e:
        raise ImportError("未安装 MCP SDK，请先执行：pip install mcp") from e

    mcp = FastMCP("enterprise-kb-assistant", host=host, port=port)

    @mcp.tool()
    def list_knowledge_bases() -> str:
        """列出系统中所有知识库的 ID、名称与简介"""
        from ..database import SessionLocal
        from ..models.knowledge_base import KnowledgeBase

        db = SessionLocal()
        try:
            rows = db.query(KnowledgeBase).all()
            return json.dumps(
                [{"id": r.id, "name": r.name, "description": r.description} for r in rows],
                ensure_ascii=False,
            )
        finally:
            db.close()

    @mcp.tool()
    def search_knowledge_base(kb_id: int, query: str, top_k: int = 5) -> str:
        """在指定知识库中检索与查询相关的资料片段，返回 JSON"""
        from ..services.rag_service import rag_service

        return json.dumps(rag_service.retrieve(kb_id, query, top_k), ensure_ascii=False)

    @mcp.tool()
    def ask_knowledge_base(kb_id: int, question: str) -> str:
        """基于指定知识库回答问题（RAG），答案末尾附来源文档"""
        from ..services.rag_service import rag_service

        r = _run(rag_service.chat(kb_id, question))
        sources = ", ".join({s.get("document_name", "") for s in r.get("sources", []) if s.get("document_name")})
        return f"{r['answer']}\n\n来源：{sources}" if sources else r["answer"]

    @mcp.tool()
    def get_current_time() -> str:
        """获取当前日期时间"""
        from datetime import datetime

        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ============ LLM Wiki 工具 ============

    @mcp.tool()
    def list_wiki_pages(kb_id: int, entity_type: str = "") -> str:
        """列出知识库中已编译的 Wiki 页面（标题/摘要/类型/版本）"""
        from ..database import SessionLocal
        from ..models.wiki_page import WikiPage

        db = SessionLocal()
        try:
            query = db.query(WikiPage).filter(WikiPage.kb_id == kb_id)
            if entity_type:
                query = query.filter(WikiPage.entity_type == entity_type)
            pages = query.all()
            return json.dumps(
                [
                    {
                        "id": p.id,
                        "title": p.title,
                        "summary": p.summary,
                        "entity_type": p.entity_type,
                        "version": p.version,
                        "status": p.status,
                    }
                    for p in pages
                ],
                ensure_ascii=False,
            )
        finally:
            db.close()

    @mcp.tool()
    def search_wiki_pages(kb_id: int, query: str, top_k: int = 3) -> str:
        """按问题检索知识库中最相关的 Wiki 页面，返回页面正文（适合全局理解/对比/总结类问题）"""
        from ..wiki.wiki_retriever import wiki_retriever

        pages = wiki_retriever.retrieve_wiki_pages(kb_id, query)
        pages = pages[:top_k]
        return json.dumps(pages, ensure_ascii=False)

    @mcp.tool()
    def read_wiki_page(page_id: int) -> str:
        """读取指定 Wiki 页面的完整 Markdown 内容"""
        from ..database import SessionLocal
        from ..models.wiki_page import WikiPage

        db = SessionLocal()
        try:
            page = db.query(WikiPage).filter(WikiPage.id == page_id).first()
            if not page:
                return json.dumps({"error": "页面不存在"}, ensure_ascii=False)
            return json.dumps(
                {
                    "title": page.title,
                    "content": page.content,
                    "entity_type": page.entity_type,
                    "source_doc_ids": page.source_doc_ids,
                    "version": page.version,
                },
                ensure_ascii=False,
            )
        finally:
            db.close()

    @mcp.tool()
    def get_wiki_graph(kb_id: int) -> str:
        """获取知识库的 Wiki 页面关联图谱（节点与边），用于跨实体推理"""
        from ..database import SessionLocal
        from ..models.wiki_page import WikiPage

        db = SessionLocal()
        try:
            pages = db.query(WikiPage).filter(WikiPage.kb_id == kb_id).all()
            nodes = [
                {"id": p.id, "title": p.title, "entity_type": p.entity_type}
                for p in pages
            ]
            edges = []
            valid = {p.id for p in pages}
            seen = set()
            for p in pages:
                for rid in (p.related_page_ids or []):
                    if rid in valid:
                        key = tuple(sorted((p.id, rid)))
                        if key not in seen:
                            seen.add(key)
                            edges.append({"source": key[0], "target": key[1]})
            return json.dumps({"nodes": nodes, "edges": edges}, ensure_ascii=False)
        finally:
            db.close()

    return mcp
