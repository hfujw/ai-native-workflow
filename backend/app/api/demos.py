"""Demo 页面端点。"""

from fastapi import APIRouter

from app.demo import load_demo_html

router = APIRouter()


@router.get("/api/demos/{name}")
async def get_demo(name: str):
    """返回预生成的演示 HTML。"""
    html, cached = load_demo_html(name)
    if html is None:
        return {"error": "未找到该演示"}, 404
    return {"html": html, "name": name, "cached": cached}


@router.get("/api/demos")
async def list_demos():
    """返回可用演示列表及就绪状态。"""
    from app.demo import list_demo_status
    return {"demos": list_demo_status()}
