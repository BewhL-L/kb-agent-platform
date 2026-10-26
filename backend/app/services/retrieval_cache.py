"""
检索结果缓存
============
只缓存 `retrieve()` 的输出，**不缓存答案**：
答案受多轮上下文、权限、时效影响，缓存命中就是事故。

失效用「版本号法」：
    每个知识库有一个版本号 kb:{id}:ver，
    缓存 key 里带上版本号；文档增删改时把版本号 +1，
    旧 key 自然再也命中不到，不需要 KEYS * 扫描（那样会阻塞 Redis）。

版本号本身不设 TTL：它必须一直存在，否则"清零"后旧缓存又活过来了。
"""
from typing import Dict, List, Optional

from ..config import settings
from .cache import cache, cache_key

# 检索逻辑改了就 +1，让旧缓存整体作废（等价于 schema 版本）
RETRIEVAL_SCHEMA_VERSION = 1


class RetrievalCache:
    def __init__(self, backend=None):
        self.cache = backend or cache

    @staticmethod
    def _version_key(kb_id: int) -> str:
        return f"kb:{kb_id}:ver"

    def version(self, kb_id: int) -> int:
        return int(self.cache.get(self._version_key(kb_id)) or 0)

    def bump(self, kb_id: int) -> int:
        """文档发生增删改时调用：让该库所有旧缓存失效"""
        return self.cache.incr(self._version_key(kb_id))

    def _key(self, kb_id: int, question: str) -> str:
        return cache_key(
            "ret", "v1", RETRIEVAL_SCHEMA_VERSION, kb_id, self.version(kb_id), question
        )

    def get(self, kb_id: int, question: str) -> Optional[List[Dict]]:
        if not settings.RETRIEVAL_CACHE_ENABLED:
            return None
        value = self.cache.get(self._key(kb_id, question))
        return value if isinstance(value, list) else None

    def set(self, kb_id: int, question: str, sources: List[Dict]) -> None:
        if not settings.RETRIEVAL_CACHE_ENABLED:
            return
        self.cache.set(
            self._key(kb_id, question),
            sources,
            ttl=settings.RETRIEVAL_CACHE_TTL,
        )

    def clear_kb(self, kb_id: int) -> None:
        self.bump(kb_id)


retrieval_cache = RetrievalCache()
