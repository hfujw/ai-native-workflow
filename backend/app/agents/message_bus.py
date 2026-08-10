"""进程内消息总线 — 让 Agent 之间直接通信，不经过 orchestrator 中转。

Phase 4 基础设施。当前用 asyncio.Queue，Phase 5 换 Redis Stream 时改配置即可。
"""

import asyncio
import logging

logger = logging.getLogger(__name__)


class MessageBus:
    """进程内消息总线。

    每个 Agent 注册一个收件箱（asyncio.Queue）。
    Agent 通过 bus.send(target, msg) 给其他 Agent 发消息。
    Agent 通过 bus.recv(own_name) 收消息。

    未来换 Redis Stream：改一行配置，接口不变。
    """

    def __init__(self):
        self._queues: dict[str, asyncio.Queue] = {}

    def register(self, agent_name: str):
        """注册一个 Agent。Agent 启动时调用。"""
        if agent_name not in self._queues:
            self._queues[agent_name] = asyncio.Queue()
            logger.debug("MessageBus=register | agent=%s", agent_name)

    async def send(self, target: str, msg: dict):
        """给指定 Agent 发消息。如果目标未注册，消息丢弃（日志警告）。"""
        q = self._queues.get(target)
        if q is None:
            logger.warning("MessageBus=send_dropped | target=%s (not registered)", target)
            return
        await q.put(msg)

    async def recv(self, agent_name: str, timeout: float = None) -> dict | None:
        """当前 Agent 收消息。

        timeout=None → 一直等到有消息。
        timeout>0  → 超时返回 None。
        """
        q = self._queues.get(agent_name)
        if q is None:
            logger.warning("MessageBus=recv_failed | agent=%s (not registered)", agent_name)
            return None
        try:
            if timeout:
                return await asyncio.wait_for(q.get(), timeout=timeout)
            return await q.get()
        except asyncio.TimeoutError:
            return None
