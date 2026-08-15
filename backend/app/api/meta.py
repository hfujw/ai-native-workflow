"""内容类端点：示例话题列表 + 评测报告（产品功能，非部署探针）。"""

import json
import logging
import os

from fastapi import APIRouter

from app.knowledge.kb import get_all_events

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/events")
async def list_events(category: str = None):
    """返回示例话题列表。category 可选过滤：'computer_history' / 'bagu' / 不传=全部。"""
    events = get_all_events(category=category if category else None)
    result = []
    for e in events:
        name = e.get("title", "")
        result.append({
            "name": name,
            "category": e.get("category", "computer_history"),
        })
    return {"events": result, "total": len(result)}


@router.get("/api/eval")
async def get_eval():
    """返回评测报告（由 scripts/eval_run.py 生成）。没跑过返回占位。"""
    report_path = os.path.join("data", "eval_report.json")
    try:
        with open(report_path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"status": "not_run",
                "message": "评测还没跑过——用 `cd backend && ..\\venv\\Scripts\\python scripts/eval_run.py` 生成"}
