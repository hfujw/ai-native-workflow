"""状态存储——单机内存实现（本地桌面端，单进程无共享需求）。

使用方式：
    from app.session import state
    count = await state.incr("pref:views:2026-08-06")
"""

from .memory import MemoryBackend

state = MemoryBackend()
