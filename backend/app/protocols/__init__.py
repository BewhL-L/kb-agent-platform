"""Agent 互操作协议包（A2A 等）"""
from .a2a_server import AGENT_CARD
from .a2a_server import router as a2a_router

__all__ = ["a2a_router", "AGENT_CARD"]
