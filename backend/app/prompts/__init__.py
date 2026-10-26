"""Prompt 注册表：模板与版本放在一起，改动必须升版本号。"""
from .system import AGENT_SYSTEM, RAG_SYSTEM, Prompt

__all__ = ["Prompt", "RAG_SYSTEM", "AGENT_SYSTEM"]
