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

    async def get(self, key: str) -> str | None:
        try:
            return await self._client.get(key)
        except Exception as e:
            logger.warning("Redis=get_failed | key=%s | error=%s", key, e)
            return None

    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        try:
            if ttl:
                await self._client.setex(key, ttl, value)
            else:
                await self._client.set(key, value)
        except Exception as e:
            logger.warning("Redis=set_failed | key=%s | error=%s", key, e)

    async def incr(self, key: str, amount: int = 1) -> int:
        try:
            if amount == 1:
                return await self._client.incr(key)
            return await self._client.incrby(key, amount)
        except Exception as e:
            logger.warning("Redis=incr_failed | key=%s | error=%s", key, e)
            return 0

    async def expire(self, key: str, seconds: int) -> None:
        try:
            await self._client.expire(key, seconds)
        except Exception as e:
            logger.warning("Redis=expire_failed | key=%s | error=%s", key, e)
