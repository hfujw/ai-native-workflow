"""偏好端点 — 读取/更新用户风格偏好。"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.preferences import get_preferences, update_preferences

router = APIRouter()


class _PreferenceRequest(BaseModel):
    style_hints: list[str] = []
    preferred_components: list[str] = []


@router.get("/api/preferences")
async def get_pref():
    """当前用户偏好。"""
    return await get_preferences()


@router.put("/api/preferences")
async def put_pref(req: _PreferenceRequest):
    """更新用户偏好。"""
    return await update_preferences(req.model_dump(exclude_defaults=True))
