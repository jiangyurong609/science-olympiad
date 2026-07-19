from __future__ import annotations

import logging
from collections import defaultdict, deque
from threading import Lock
from time import monotonic, time as wall_time

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings

_log = logging.getLogger("soplat.ratelimit")


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed-window rate limiter. Uses Redis (shared across Cloud Run replicas)
    when REDIS_URL is set, and falls back to a process-local window otherwise —
    including if Redis is momentarily unreachable, so a cache blip never 500s the
    app."""

    def __init__(self, app):
        super().__init__(app)
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()
        self._redis = None
        url = get_settings().redis_url
        if url:
            try:
                import redis.asyncio as aioredis
                self._redis = aioredis.from_url(url, socket_timeout=0.25,
                                                socket_connect_timeout=0.25)
                _log.info("rate_limit_backend_redis")
            except Exception:  # noqa: BLE001 — never let limiter setup break boot
                _log.warning("rate_limit_redis_init_failed_using_memory", exc_info=True)

    async def _redis_allow(self, key: str, limit: int, window: int) -> tuple[bool, int]:
        # Wall-clock, NOT monotonic(): monotonic()'s epoch is per-process, so
        # replicas would compute different bucket ids and never share the window.
        bucket = int(wall_time() // window)
        rkey = f"rl:{key}:{bucket}"
        pipe = self._redis.pipeline()
        pipe.incr(rkey)
        pipe.expire(rkey, window)
        count, _ = await pipe.execute()
        return count <= limit, window

    def _memory_allow(self, key: str, limit: int, window: int) -> tuple[bool, int]:
        now = monotonic()
        with self._lock:
            bucket = self._hits[key]
            cutoff = now - window
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                return False, max(1, int(window - (now - bucket[0])))
            bucket.append(now)
        return True, window

    @staticmethod
    def _client_ip(request: Request) -> str:
        # Behind Cloud Run/GFE the socket peer is the proxy, and the real client
        # is the FIRST hop in X-Forwarded-For — without this, every user shares
        # one bucket and per-client throttling does nothing.
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next):
        if request.url.path in {"/", "/api/health"} or request.url.path.startswith("/static/"):
            return await call_next(request)
        settings = get_settings()
        client = self._client_ip(request)
        key = f"{client}:{request.url.path}"
        limit, window = settings.rate_limit_requests, settings.rate_limit_window_seconds

        allowed, retry_after = True, window
        if self._redis is not None:
            try:
                allowed, retry_after = await self._redis_allow(key, limit, window)
            except Exception:  # noqa: BLE001 — Redis down => degrade to in-memory
                _log.warning("rate_limit_redis_error_fallback_memory", exc_info=True)
                allowed, retry_after = self._memory_allow(key, limit, window)
        else:
            allowed, retry_after = self._memory_allow(key, limit, window)

        if not allowed:
            return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"},
                                headers={"Retry-After": str(retry_after)})
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        return response
