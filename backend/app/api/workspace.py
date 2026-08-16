"""工作区端点 — 删除产物文件（前端作品卡删除用）。"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.workspace import delete_page

router = APIRouter()


@router.delete("/api/workspace/{filename}")
async def delete_workspace_file(filename: str):
    """删除工作区里的一个产物文件。路径白名单校验在 delete_page 内（防穿越）。"""
    ok = delete_page(filename)
    if not ok:
        return JSONResponse(status_code=404, content={"error": "文件不存在或文件名非法"})
    return {"ok": True}
