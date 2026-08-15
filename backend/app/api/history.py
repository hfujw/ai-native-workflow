"""历史端点 — 生成历史列表 + 单条回看。"""

from fastapi import APIRouter

from app.projects import get_project, get_projects

router = APIRouter()


@router.get("/api/history")
async def list_history():
    """生成历史列表（新的在前）。"""
    return {"projects": get_projects()}


@router.get("/api/history/{project_id}")
async def get_history(project_id: str):
    """单个生成记录（可回看页面）。"""
    project = get_project(project_id)
    if project is None:
        return {"error": "未找到该项目"}, 404
    return project
