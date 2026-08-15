"""MemoryBackend — 单机内存实现。重启后数据清零。

限流器的关键在于：key 带日期（rate:{ip}:2026-08-06），expire 86400 秒自动过期。
不需要手动日重置——新的一天自然生成新 key，旧 key 到期自动消失。
"""

import time

from .base import StateBackend


class MemoryBackend(StateBackend):
    def __init__(self):
        self._data: dict[str, str] = {}
        self._ttl: dict[str, float] = {}

    async def get(self, key: str) -> str | None:
        self._check_ttl(key)
        return self._data.get(key)

    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        self._data[key] = value
        if ttl:
            self._ttl[key] = time.monotonic() + ttl
        else:
            self._ttl.pop(key, None)  # 清理旧 TTL，防止新值被误删

    async def incr(self, key: str, amount: int = 1) -> int:
        self._check_ttl(key)
        current = int(self._data.get(key, "0"))
        current += amount
        self._data[key] = str(current)
        return current

    async def expire(self, key: str, seconds: int) -> None:
        self._ttl[key] = time.monotonic() + seconds

    def _check_ttl(self, key: str) -> None:
        if key in self._ttl and time.monotonic() > self._ttl[key]:
            self._data.pop(key, None)
            self._ttl.pop(key, None)
