"""生成历史持久化 — 每次生成（含迭代）存一个 project，可回看/续。

位置：backend/data/projects.json（gitignored，最多保留 100 条）
schema：
{
  "id": "8f3a2b", "topic": "秦始皇修长城", "created_at": 1723350000,
  "status": "success", "steps": 7, "cost": 0.31, "iterations": 2,
  "html": "<!DOCTYPE html>...", "trace_path": "logs/traces/8f3a2b.jsonl"
}
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

_PROJECTS_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "projects.json")
_MAX_PROJECTS = 100


def _load() -> list[dict]:
    try:
        with open(_PROJECTS_FILE, encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_project(project: dict) -> None:
    """保存一个 project；同 id 覆盖，最多保留 100 条。"""
    projects = _load()
    projects = [p for p in projects if p.get("id") != project.get("id")]
    projects.insert(0, project)
    projects = projects[:_MAX_PROJECTS]
    try:
        os.makedirs(os.path.dirname(_PROJECTS_FILE), exist_ok=True)
        with open(_PROJECTS_FILE, "w", encoding="utf-8") as f:
            json.dump(projects, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("project 保存失败: %s", e)


def get_projects() -> list[dict]:
    """返回全部历史（新的在前）。"""
    return _load()


def get_project(project_id: str) -> dict | None:
    """按 id 取单个 project。"""
    return next((p for p in _load() if p.get("id") == project_id), None)
