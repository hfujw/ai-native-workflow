"""WebUI 端点 — WebUI 前端引导 + 成品查看。

task 13（2026-08-19）：前端 webui/（WebUI 二创）接深度后端。
- /webui/bootstrap    最小 mock：让前端 boot 流程可用（深度后端不走 WS 消息流）
- /works/{project_id} 成品 HTML 查看（compat.py 生成完成返回的链接指向这里）
"""

import logging

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from app.projects import get_project

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/webui/bootstrap")
async def webui_bootstrap():
    """前端启动引导（最小 mock）。

    前端 webui/ 的 boot 流程会 GET /webui/bootstrap，且要求返回 ws_path。
    深度后端的消息流走 /v1/responses SSE（不依赖 WS 会话），所以这里返回
    一个占位路径即可让 UI 渲染；其余字段对齐前端 BootstrapResponse。
    """
    return {
        "ws_path": "/ws",
        "token": "",
        "api_token": "",
        "expires_in": 3600,
        # 必须返回 DeepSeek 官方名——前端模型徽章直接用这个值
        "model_name": "deepseek-v4-flash",
        "runtime_surface": "browser",
        "runtime_capabilities": {
            "can_restart_engine": False,
            "can_pick_folder": False,
            "can_open_logs": False,
            "can_export_diagnostics": False,
        },
    }


@router.get("/works/{project_id}")
async def view_works(project_id: str):
    """查看成品 HTML（compat.py 生成完成返回的链接指向这里）。"""
    project = get_project(project_id)
    if project is None:
        return JSONResponse(status_code=404, content={"error": "未找到该项目"})
    versions = project.get("versions") or []
    html = (versions[-1].get("html") if versions else None) or project.get("html", "")
    if not html:
        return JSONResponse(status_code=404, content={"error": "该项目没有成品"})
    return HTMLResponse(content=html)
