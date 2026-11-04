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
    """选择缓存后端。

    两种模式的行为**故意不同**：

    - `ASYNC_MODE=thread`（单进程开发）：Redis 连不上就降级内存缓存，只记 warning。
      反正只有一个进程，内存缓存语义是对的。
    - `ASYNC_MODE=celery`（backend + worker 两个进程）：Redis 连不上**直接抛错**。
      因为版本号（`kb:{id}:ver`）是跨进程失效的唯一手段：worker 处理完文档后 bump 的版本号
      如果只落在 worker 自己的内存里，API 侧会继续命中旧 key，最长 `RETRIEVAL_CACHE_TTL`
      秒返回过期检索结果，而且**除了那条 warning 没有任何信号**——这正是"不影响使用"的
      失败最容易长期潜伏的那一类。宁可启动失败，也不要带着一份各进程不一致的缓存对外服务。
    """
    if settings.REDIS_URL:
        try:
            import redis

            client = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
            client.ping()
            logger.info("缓存使用 Redis")
            return RedisCache(client)
        except Exception as e:
            if settings.ASYNC_MODE == "celery":
                raise RuntimeError(
                    "拒绝启动：ASYNC_MODE=celery 需要共享缓存，但 Redis 不可用 "
                    f"({settings.REDIS_URL})：{e}。"
                    "celery 模式下 backend 与 worker 是独立进程，内存缓存会让检索结果"
                    "在文档更新后继续返回旧值，因此这里不做降级。"
                    "请先确认 redis 容器健康（docker compose ps redis / docker compose logs redis）。"
                ) from e
            logger.warning(f"Redis 不可用，降级为内存缓存：{e}")
    elif settings.ASYNC_MODE == "celery":
        raise RuntimeError(
            "拒绝启动：ASYNC_MODE=celery 必须配置 REDIS_URL（跨进程共享的缓存与版本号）。"
        )
    return MemoryCache()


cache = build_cache()


def cache_backend_name() -> str:
    """当前实际使用的缓存后端，health 接口会暴露它。

    存在的意义：降级是静默发生的，唯一能让人事后发现"原来是内存缓存"的地方。
    """
    return "redis" if isinstance(cache, RedisCache) else "memory"


def cache_key(prefix: str, *parts) -> str:
    h = hashlib.md5("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()
    return f"{prefix}:{h}"
