"""路由汇总"""
from . import (
    agent,
    auth,
    chat,
    conversations,
    documents,
    evaluation,
    finetune,
    graphrag,
    knowledge_bases,
    stats,
    structured,
    wiki,
)

routers = [
    auth.router,
    knowledge_bases.router,
    documents.router,
    conversations.router,
    chat.router,
    stats.router,
    agent.router,
    evaluation.router,
    wiki.router,
    graphrag.router,
    finetune.router,
    structured.router,
]
