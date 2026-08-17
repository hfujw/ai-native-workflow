"""Phase B 测试——持久化层（trace / 历史 / 工作区）。偏好已砍，不再测试。"""
import os

from app import projects
from app.observability import trace

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
# B4: 页面工作区（每对话一页，落成独立 HTML 文件）
# ═══════════════════════════════════════════════════════════════

def test_workspace_save_page(tmp_path, monkeypatch):
    from app import workspace
    monkeypatch.setattr(workspace, "_WORKSPACE_DIR", str(tmp_path))
    path = workspace.save_page("s123", "Linux 诞生记: 1991 那个爱好项目", "<html>hi</html>")
    assert os.path.isfile(path)
    assert "s123" in os.path.basename(path)  # 文件名带会话 id
    assert path.endswith("_v1.html")  # 首版 = v1
    with open(path, encoding="utf-8") as f:
        assert f.read() == "<html>hi</html>"


def test_workspace_iteration_makes_new_version(tmp_path, monkeypatch):
    """迭代修改 → 生成新版本文件（不覆盖旧版）。"""
    from app import workspace
    monkeypatch.setattr(workspace, "_WORKSPACE_DIR", str(tmp_path))
    p1 = workspace.save_page("s", "主题", "<html>v1</html>", 1)
    p2 = workspace.save_page("s", "主题", "<html>v2</html>", 2)
    assert os.path.isfile(p1) and os.path.isfile(p2)  # 两版都在，不覆盖
    assert p1 != p2


def test_workspace_delete_page(tmp_path, monkeypatch):
    """删除产物文件 + 路径穿越防护。"""
    from app import workspace
    monkeypatch.setattr(workspace, "_WORKSPACE_DIR", str(tmp_path))
    p = workspace.save_page("s", "主题", "<html>x</html>", 1)
    name = os.path.basename(p)
    assert workspace.delete_page(name) is True
    assert not os.path.isfile(p)
    assert workspace.delete_page(name) is False  # 已删
    assert workspace.delete_page("../evil.html") is False  # 路径穿越被拒


def test_workspace_save_page_skips_empty(tmp_path, monkeypatch):
    from app import workspace
    monkeypatch.setattr(workspace, "_WORKSPACE_DIR", str(tmp_path))
    assert workspace.save_page("s2", "t", "") == ""  # 空 html 不落盘
    assert workspace.save_page("s2", "t", None) == ""


# ═══════════════════════════════════════════════════════════════
# B5: 思考回放端点（"AI 是怎么想到这些的"）
# ═══════════════════════════════════════════════════════════════

def test_trace_endpoint(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app import projects
    from app.main import app
    from app.observability import trace
    monkeypatch.setattr(trace, "_TRACE_DIR", str(tmp_path))
    monkeypatch.setattr(projects, "_PROJECTS_FILE", str(tmp_path / "projects.json"))
    projects.save_project({"id": "p1", "topic": "恐龙", "html": "<html/>", "iterations": 1})
    trace.log_trace("p1", {"type": "decide", "step": 1, "tool": "search", "thought": "先搜索证据"})
    trace.log_trace("p1", {"type": "tool", "step": 1, "tool": "search", "summary": "找到 3 条"})

    client = TestClient(app)
    r = client.get("/api/history/p1/trace")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2
    assert data["entries"][0]["tool"] == "search"
    assert client.get("/api/history/nope/trace").status_code == 404
