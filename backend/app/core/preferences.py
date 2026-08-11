"""用户偏好记忆 — 记住风格/组件偏好，下次生成自动注入。

存 StateBackend（memory/redis），全局单一偏好集（无用户体系）。
schema:
{"style_hints": ["暗色", "极简"], "preferred_components": ["timeline"], "learned_at": 1723350000}
"""

import json
import logging
import time

from app.state import state

logger = logging.getLogger(__name__)

_KEY = "prefs"


async def get_preferences() -> dict:
    """读当前偏好（不存在返回空 dict）。"""
    raw = await state.get(_KEY)
    try:
        prefs = json.loads(raw) if raw else {}
        return prefs if isinstance(prefs, dict) else {}
    except json.JSONDecodeError:
        return {}


async def update_preferences(patch: dict) -> dict:
    """合并更新偏好，返回更新后的完整偏好。"""
    prefs = await get_preferences()
    prefs.update(patch)
    prefs["learned_at"] = int(time.time())
    await state.set(_KEY, json.dumps(prefs, ensure_ascii=False))
    return prefs
