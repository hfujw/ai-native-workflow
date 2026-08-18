"""生成历史持久化 — 每次生成（含迭代）存一个 project，保留**每个迭代版本**可回看。

位置：backend/data/projects.json（gitignored，最多保留 100 条）
schema：
{
  "id": "8f3a2b", "topic": "秦始皇修长城", "created_at": 1723350000,
  "status": "success", "steps": 7, "cost": 0.31, "iterations": 2,
  "versions": [
    {"iteration": 1, "html": "<!DOCTYPE html>...v1", "created_at": 1723350000},
    {"iteration": 2, "html": "<!DOCTYPE html>...v2", "created_at": 1723351000}
  ],
  "trace_path": "logs/traces/8f3a2b.jsonl"
}
"""

import json
import logging
import os
import time

logger = logging.getLogger(__name__)

_PROJECTS_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "projects.json")
_MAX_PROJECTS = 100


def _load() -> list[dict]:
    try:
        with open(_PROJECTS_FILE, encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _ensure_versions(project: dict) -> dict:
    """向后兼容：旧数据只有 html 没有 versions → 包成 version 1。"""
    if "versions" not in project:
        project["versions"] = [{
            "iteration": 1,
            "html": project.get("html", ""),
            "created_at": project.get("created_at", int(time.time())),
        }]
    return project


def _write(projects: list[dict]) -> None:
    """统一落盘（保留最近 100 条）。"""
    projects = projects[:_MAX_PROJECTS]
    try:
        os.makedirs(os.path.dirname(_PROJECTS_FILE), exist_ok=True)
        with open(_PROJECTS_FILE, "w", encoding="utf-8") as f:
            json.dump(projects, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("project 保存失败: %s", e)


def save_project(project: dict) -> None:
    """保存 project——同 id 合并，html 变化时追加新版本（迭代历史不丢）。"""
    projects = _load()
    existing = next((p for p in projects if p.get("id") == project.get("id")), None)

    if existing:
        _ensure_versions(existing)
        versions = existing["versions"]
        html = project.get("html", "")
        # html 变了才追加新版本（防止重复保存产生空版本）
        if not versions or versions[-1].get("html") != html:
            versions.append({
                "iteration": len(versions) + 1,
                "html": html,
                "created_at": project.get("created_at", int(time.time())),
            })
        existing.update({
            "topic": project.get("topic", existing.get("topic", "")),
            "status": project.get("status", existing.get("status", "unknown")),
            "steps": project.get("steps", existing.get("steps", 0)),
            "cost": project.get("cost", existing.get("cost", 0)),
            "iterations": len(versions),
            "trace_path": project.get("trace_path", existing.get("trace_path", "")),
            "file_path": project.get("file_path", existing.get("file_path", "")),
        })
        # 编排上下文（design/content/material）——LobeChat 迭代时恢复，让 refine 真正懂"上次怎么设计的"
        if project.get("state") is not None:
            existing["state"] = project["state"]
        # 对话消息：合并（迭代时追加新消息）
        if project.get("messages"):
            existing["messages"] = project["messages"]
        projects.remove(existing)
        projects.insert(0, existing)
    else:
        _ensure_versions(project)
        project.setdefault("messages", [])
        projects.insert(0, project)

    _write(projects)


def rename_project(project_id: str, new_topic: str) -> bool:
    """重命名历史作品。返回是否找到并改名。"""
    projects = _load()
    p = next((x for x in projects if x.get("id") == project_id), None)
    if p is None:
        return False
    p["topic"] = new_topic
    _write(projects)
    return True


def pin_project(project_id: str) -> bool:
    """置顶历史作品（移到列表最前）。返回是否找到。"""
    projects = _load()
    p = next((x for x in projects if x.get("id") == project_id), None)
    if p is None:
        return False
    projects.remove(p)
    projects.insert(0, p)
    _write(projects)
    return True


def delete_project(project_id: str) -> bool:
    """删除历史作品——级联删 workspace 文件 + trace 文件（不留孤儿）。返回是否真的删掉了。"""
    projects = _load()
    target = next((p for p in projects if p.get("id") == project_id), None)
    before = len(projects)
    projects = [p for p in projects if p.get("id") != project_id]
    if len(projects) == before:
        return False
    _write(projects)

    # 级联删除 workspace 文件（<project_id>_*.html）
    if target:
        workspace_dir = os.path.join(os.path.dirname(__file__), "..", "workspace")
        try:
            for name in os.listdir(workspace_dir):
                if name.startswith(f"{project_id}_") and name.endswith(".html"):
                    try:
                        os.remove(os.path.join(workspace_dir, name))
                    except OSError as e:
                        logger.warning("级联删 workspace 失败 %s: %s", name, e)
        except OSError:
            pass  # workspace 目录不存在

    # 级联删除 trace 文件
    trace_path = os.path.join(os.path.dirname(__file__), "..", "logs", "traces", f"{project_id}.jsonl")
    try:
        if os.path.isfile(trace_path):
            os.remove(trace_path)
    except OSError as e:
        logger.warning("级联删 trace 失败: %s", e)

    return True


def get_projects() -> list[dict]:
    """返回全部历史（新的在前，含 versions）。"""
    return [_ensure_versions(p) for p in _load()]


def get_project(project_id: str) -> dict | None:
    """按 id 取单个 project（含 versions）。"""
    project = next((p for p in _load() if p.get("id") == project_id), None)
    return _ensure_versions(project) if project else None


def get_project_messages(project_id: str) -> list:
    """按 id 取该 project 的对话消息（前端切换历史对话时恢复）。无则返回空列表。"""
    project = get_project(project_id)
    if not project:
        return []
    return project.get("messages", [])
