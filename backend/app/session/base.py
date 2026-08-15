"""状态存储抽象基类 — MemoryBackend（单机） + RedisBackend（多实例，未来）。

限流器、断路器等模块通过 StateBackend 接口操作状态，
不直接操作 dict——切换后端只需改配置，不改业务代码。
"""

from abc import ABC, abstractmethod


class StateBackend(ABC):
    """状态存储抽象。四个方法覆盖当前所有需求：
    - 限流器：incr("rate:{ip}:{date}") + expire(86400)
    - 断路器：get("circuit:state") / set("circuit:state", "open")
    - 会话：set("session:{id}", json_str, ttl=3600)
    """

    @abstractmethod
    async def get(self, key: str) -> str | None: ...

    @abstractmethod
    async def set(self, key: str, value: str, ttl: int | None = None) -> None: ...

    @abstractmethod
    async def incr(self, key: str, amount: int = 1) -> int: ...

    @abstractmethod
    async def expire(self, key: str, seconds: int) -> None: ...
