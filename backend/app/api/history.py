"""历史端点 — 生成历史列表 + 单条回看 + 重命名/置顶/删除。"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.observability.trace import get_trace
from app.projects import (
    delete_project,
    get_project,
    get_projects,
    pin_project,
    rename_project,
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


class _RenameRequest(BaseModel):
    topic: str


@router.patch("/api/history/{project_id}")
async def rename_history(project_id: str, req: _RenameRequest):
    """重命名历史作品（改 topic）。"""
    topic = req.topic.strip()
    if not topic:
        # 注意：新版 FastAPI 不支持 (dict, status) 元组返回——必须用 JSONResponse
        return JSONResponse(status_code=400, content={"error": "主题不能为空"})
    return {"ok": rename_project(project_id, topic)}


@router.post("/api/history/{project_id}/pin")
async def pin_history(project_id: str):
    """置顶历史作品（移到列表最前）。"""
    return {"ok": pin_project(project_id)}


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
