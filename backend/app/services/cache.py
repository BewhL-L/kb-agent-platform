"""
缓存抽象（可选 Redis）
- 配置 REDIS_URL 且 redis 可用时使用 Redis（多进程/多实例共享）
- 否则降级为进程内内存字典
- 两种实现都支持 TTL 与 incr（版本号失效依赖 incr）
"""
import hashlib
import json
import time

from ..config import settings
from ..utils.logger import get_logger

logger = get_logger(__name__)


class MemoryCache:
    """进程内缓存。注意：多 worker 各自一份，只适合本地开发/单实例。"""

    def __init__(self):
        self._d = {}
        self._exp = {}

    def get(self, key: str):
        expire_at = self._exp.get(key)
        if expire_at is not None and expire_at <= time.time():
            self._d.pop(key, None)
            self._exp.pop(key, None)
            return None
        return self._d.get(key)

    def set(self, key: str, value, ttl: int = None) -> None:
        self._d[key] = value
        if ttl:
            self._exp[key] = time.time() + ttl
        else:
            self._exp.pop(key, None)

    def incr(self, key: str, amount: int = 1) -> int:
        value = int(self.get(key) or 0) + amount
        self.set(key, value)
        return value

    def delete(self, key: str) -> None:
        self._d.pop(key, None)
        self._exp.pop(key, None)

    def clear(self) -> None:
        self._d.clear()
        self._exp.clear()


class RedisCache:
    def __init__(self, client):
        self.r = client

    def get(self, key: str):
        v = self.r.get(key)
        return json.loads(v) if v else None

    def set(self, key: str, value, ttl: int = None) -> None:
        data = json.dumps(value, ensure_ascii=False)
        if ttl:
            self.r.setex(key, ttl, data)
        else:
            self.r.set(key, data)

    def incr(self, key: str, amount: int = 1) -> int:
        return int(self.r.incr(key, amount))

    def delete(self, key: str) -> None:
        self.r.delete(key)

    def clear(self) -> None:
        # 只清本应用的 key，避免 flushdb 误删别人的数据
        for key in self.r.scan_iter("kb:*"):
            self.r.delete(key)
        for key in self.r.scan_iter("ret:*"):
            self.r.delete(key)


def build_cache():
    if settings.REDIS_URL:
        try:
            import redis

            client = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
            client.ping()
            logger.info("缓存使用 Redis")
            return RedisCache(client)
        except Exception as e:
            logger.warning(f"Redis 不可用，降级为内存缓存：{e}")
    return MemoryCache()


cache = build_cache()


def cache_key(prefix: str, *parts) -> str:
    h = hashlib.md5("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()
    return f"{prefix}:{h}"
