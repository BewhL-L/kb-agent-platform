"""
接口限流中间件（单机内存滑动窗口）
- 按客户端 IP 统计每个窗口（60s）内的请求数
- 超过阈值返回 429
- 无需额外依赖，适合单实例部署；多实例需换 Redis 方案
"""
import json
import threading
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from ..config import settings
from ..utils.logger import get_logger

logger = get_logger(__name__)

# 不限流的路径前缀
_WHITELIST = ("/health", "/docs", "/openapi.json", "/redoc", "/favicon")


class RateLimitMiddleware(BaseHTTPMiddleware):
    """滑动窗口限流"""

    def __init__(self, app, limit_per_minute: int = None, window_seconds: int = 60):
        super().__init__(app)
        self.limit = limit_per_minute or settings.RATE_LIMIT_PER_MINUTE
        self.window = window_seconds
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def _client_ip(self, request: Request) -> str:
        """
        取真实客户端 IP。

        X-Forwarded-For 是一个可被客户端伪造的链（格式多为「伪造值, 真实值」），
        直接取第一段等于把限流开关交给调用方。因此优先用反向代理写入的 X-Real-IP，
        其次取 XFF 的最后一跳（最外层代理追加的那一段）。
        """
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[-1].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next):
        if not settings.RATE_LIMIT_ENABLED:
            return await call_next(request)

        path = request.url.path
        if path.startswith(_WHITELIST):
            return await call_next(request)

        ip = self._client_ip(request)
        now = time.time()

        with self._lock:
            bucket = self._hits[ip]
            # 清除窗口外的旧记录
            while bucket and bucket[0] <= now - self.window:
                bucket.popleft()

            if len(bucket) >= self.limit:
                retry_after = int(self.window - (now - bucket[0])) + 1
                logger.warning(f"IP {ip} 触发限流（{self.limit}/{self.window}s）")
                return Response(
                    content=json.dumps(
                        {"detail": f"请求过于频繁，请 {retry_after} 秒后再试"},
                        ensure_ascii=False,
                    ),
                    status_code=429,
                    media_type="application/json",
                    headers={"Retry-After": str(retry_after)},
                )

            bucket.append(now)

        return await call_next(request)
