"""状态存储模块。

使用方式：
    from app.state import state
    count = await state.incr("rate:1.2.3.4:2026-08-06")
"""

from app.core.config import settings

from .memory import MemoryBackend


def _create_state():
    """根据 STATE_BACKEND 配置创建对应实例。"""
    backend = settings.state_backend
    if backend == "redis":
        from .redis import RedisBackend
        return RedisBackend(url=settings.redis_url)
    return MemoryBackend()


state = _create_state()
