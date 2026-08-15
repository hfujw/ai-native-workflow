"""Phase B 测试——持久化层（trace / 历史 / 偏好）。"""
import pytest

from app import projects
from app.observability import trace
from app.preferences import get_preferences, update_preferences

# ═══════════════════════════════════════════════════════════════
# B1: trace 落盘
# ═══════════════════════════════════════════════════════════════

def test_trace_log_and_read(tmp_path, monkeypatch):
    monkeypatch.setattr(trace, "_TRACE_DIR", str(tmp_path))
    trace.log_trace("sess1", {"type": "decide", "step": 1, "tool": "design", "thought": "x"})
    trace.log_trace("sess1", {"type": "tool", "step": 1, "tool": "render", "summary": "ok", "cost_delta": 0.01})
    entries = trace.get_trace("sess1")
    assert len(entries) == 2
    assert entries[0]["tool"] == "design"
    assert entries[1]["type"] == "tool"
    assert entries[1]["session"] == "sess1"


def test_trace_missing_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(trace, "_TRACE_DIR", str(tmp_path))
    assert trace.get_trace("nope") == []


def test_trace_log_corrupt_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(trace, "_TRACE_DIR", str(tmp_path))
    (tmp_path / "bad.jsonl").write_text("这不是JSON\n", encoding="utf-8")
    assert trace.get_trace("bad") == []


# ═══════════════════════════════════════════════════════════════
# B2: 历史 projects
# ═══════════════════════════════════════════════════════════════

def test_projects_save_and_read(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "_PROJECTS_FILE", str(tmp_path / "projects.json"))
    projects.save_project({"id": "p1", "topic": "秦始皇", "status": "success",
                           "steps": 3, "cost": 0.1, "html": "<html/>", "iterations": 1})
    all_p = projects.get_projects()
    assert len(all_p) == 1
    assert all_p[0]["id"] == "p1"
    assert projects.get_project("p1")["topic"] == "秦始皇"
    assert projects.get_project("missing") is None


def test_projects_upsert_and_order(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "_PROJECTS_FILE", str(tmp_path / "projects.json"))
    projects.save_project({"id": "p1", "topic": "a"})
    projects.save_project({"id": "p1", "topic": "b"})  # 同 id 覆盖
    projects.save_project({"id": "p2", "topic": "c"})
    all_p = projects.get_projects()
    assert len(all_p) == 2
    assert all_p[0]["id"] == "p2"  # 新的在前
    assert all_p[1]["topic"] == "b"  # p1 被覆盖为新值


def test_projects_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "_PROJECTS_FILE", str(tmp_path / "none.json"))
    assert projects.get_projects() == []


# ═══════════════════════════════════════════════════════════════
# B3: 偏好存储
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_preferences_update_and_get():
    await update_preferences({"style_hints": ["暗色"]})
    prefs = await get_preferences()
    assert "暗色" in prefs["style_hints"]
    assert "learned_at" in prefs


@pytest.mark.asyncio
async def test_preferences_merge():
    await update_preferences({"style_hints": ["暗色"]})
    await update_preferences({"preferred_components": ["timeline"]})
    prefs = await get_preferences()
    assert "暗色" in prefs["style_hints"]
    assert "timeline" in prefs["preferred_components"]
