"""WebSocket 连接管理器。"""

import json
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)

MAX_CONNECTIONS = 20


class WSManager:
    def __init__(self):
        """建立通讯本"""
        self.connections: dict[str, WebSocket] = {}

    @property
    def active_count(self) -> int:
        return len(self.connections)

    async def connect(self, session_id: str, websocket: WebSocket) -> bool:
        """接受 WebSocket 连接。返回 False 表示被拒绝，调用方应直接 return。"""
        # 1. 连接数上限——防止资源耗尽（本地桌面端同样适用）
        if len(self.connections) >= MAX_CONNECTIONS:
            logger.warning("连接数已达上限 %d，拒绝新连接 [%s]", MAX_CONNECTIONS, session_id)
            await websocket.close(code=1013, reason="服务器繁忙，请稍后重试")
            return False

        # 2. 踢掉同 session_id 的旧连接——防止 fd 泄漏
        old = self.connections.pop(session_id, None)
        if old is not None:
            logger.debug("踢掉旧连接 [%s]", session_id)
            try:
                await old.close(code=1000, reason="新连接取代")
            except Exception as e:
                logger.debug("关闭旧连接失败: %s", e)

        # 同意Websocket链接
        await websocket.accept()
        self.connections[session_id] = websocket
        logger.debug("WebSocket 已连接 [%s]（当前 %d 个连接）", session_id, len(self.connections))
        return True

    async def disconnect(self, session_id: str):
        self.connections.pop(session_id, None)

    async def shutdown(self, timeout: float = 5.0):
        """优雅关闭——通知所有客户端后断开。"""
        for sid, ws in list(self.connections.items()):
            try:
                await ws.close(code=1001, reason="服务器维护中")
            except Exception as e:
                logger.debug("shutdown 关闭连接失败 [%s]: %s", sid, e)
        self.connections.clear()

    async def _safe_send(self, session_id: str, payload: dict):
        """安全发送：连接断开时静默处理，不抛崩主流程"""
        ws = self.connections.get(session_id)
        if not ws:
            return
        try:
            await ws.send_text(json.dumps(payload, ensure_ascii=False))
        except Exception as e:
            logger.debug("WebSocket 发送失败 [%s]: %s", session_id, str(e))
            self.connections.pop(session_id, None)

    async def send_json(self, session_id: str, payload: dict):
        await self._safe_send(session_id, payload)

    async def send_page_ready(self, session_id: str, page_html: str):
        await self._safe_send(session_id, {
            "type": "page_ready",
            "page_html": page_html,
        })

    async def send_failed(self, session_id: str, reason: str, suggestions: list):
        await self._safe_send(session_id, {
            "type": "generation_failed",
            "reason": reason,
            "suggestions": suggestions,
        })


ws_manager = WSManager()
