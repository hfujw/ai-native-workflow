"""历史端点 — 生成历史列表 + 单条回看 + 重命名/置顶/删除。"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.observability.trace import get_trace
from app.projects import (
    delete_project,
    get_project,
    get_projects,
)

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
        return JSONResponse(status_code=404, content={"error": "未找到该项目"})
    return project


@router.delete("/api/history/{project_id}")
async def delete_history(project_id: str):
    """删除历史作品。"""
    return {"ok": delete_project(project_id)}


@router.get("/api/history/{project_id}/trace")
async def get_history_trace(project_id: str):
    """读取一个生成记录的完整决策轨迹（思考回放用——"AI 是怎么想到这些的"）。"""
    project = get_project(project_id)
    if project is None:
        return JSONResponse(status_code=404, content={"error": "未找到该项目"})
    entries = get_trace(project_id)  # trace 文件按 session_id(=project_id) 命名
    return {"entries": entries, "total": len(entries)}
