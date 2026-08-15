"""RedisBackend — 多 Worker 共享状态。实现 StateBackend 四方法。"""

import logging

from .base import StateBackend

logger = logging.getLogger(__name__)


class RedisBackend(StateBackend):
    """Redis 状态后端——多进程/多机器共享。

    使用方式：STATE_BACKEND=redis REDIS_URL=redis://localhost:6379
    与 MemoryBackend 接口完全一致，Agent 代码零改动。
    """

    def __init__(self, url: str = "redis://localhost:6379"):
        import redis.asyncio as redis
        self._client = redis.from_url(url, decode_responses=True)
        self._available = True

    @property
    def available(self) -> bool:
        """后端可用性——限流器据此 fail-closed（P2-8），不静默失效。"""
        return self._available

    def _mark_unavailable(self, e: Exception):
        if self._available:
            self._available = False
            logger.error("Redis 不可用——限流将 fail-closed: %s", e)
            from app.observability.metrics import STATE_BACKEND
            STATE_BACKEND.labels(backend="redis").set(0)

    def _mark_available(self):
        if not self._available:
            self._available = True
            logger.info("Redis 恢复可用")
            from app.observability.metrics import STATE_BACKEND
            STATE_BACKEND.labels(backend="redis").set(1)

    async def get(self, key: str) -> str | None:
        try:
            val = await self._client.get(key)
            self._mark_available()
            return val
        except Exception as e:
            self._mark_unavailable(e)
            return None

    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        try:
            if ttl:
                await self._client.setex(key, ttl, value)
            else:
                await self._client.set(key, value)
            self._mark_available()
        except Exception as e:
            self._mark_unavailable(e)

    async def incr(self, key: str, amount: int = 1) -> int:
        try:
            if amount == 1:
                val = await self._client.incr(key)
            else:
                val = await self._client.incrby(key, amount)
            self._mark_available()
            return val
        except Exception as e:
            self._mark_unavailable(e)
            return 0

    async def expire(self, key: str, seconds: int) -> None:
        try:
            await self._client.expire(key, seconds)
            self._mark_available()
        except Exception as e:
            self._mark_unavailable(e)
