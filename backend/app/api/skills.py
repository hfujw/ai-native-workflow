"""Skill 端点 — 列出可用 skill（风格/工具）+ 安装/删除（我的 Skill）。"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.skills import delete_skill, install_skill, list_skills, load_skill

router = APIRouter()


@router.get("/api/skills")
async def get_skills(skill_type: str = None):
    """可用 skill 列表。skill_type 可选：'风格' / '工具' / 不传=全部。"""
    return {"skills": list_skills(skill_type)}


class _InstallRequest(BaseModel):
    id: str
    markdown: str


@router.post("/api/skills/install")
async def install_skill_endpoint(req: _InstallRequest):
    """安装一个 skill（前端"我的 Skill"下载用）。"""
    skill_id = req.id.strip()
    # 路径安全：id 不能含路径分隔符/上级跳转
    if not skill_id or any(ch in skill_id for ch in ("/", "\\", "..", " ")):
        return JSONResponse(status_code=400, content={"error": "skill id 不合法"})
    skill = install_skill(skill_id, req.markdown)
    if skill is None:
        return JSONResponse(status_code=400, content={"error": "skill 格式非法（缺 name）"})
    return skill


@router.delete("/api/skills/{skill_id}")
async def delete_skill_endpoint(skill_id: str):
    """删除一个 skill（内置 skill 不可删除）。"""
    skill = load_skill(skill_id)
    if skill is None:
        return JSONResponse(status_code=404, content={"error": "未找到该 skill"})
    if skill.get("builtin"):
        return JSONResponse(status_code=400, content={"error": "内置 skill 不可删除"})
    return {"ok": delete_skill(skill_id)}
