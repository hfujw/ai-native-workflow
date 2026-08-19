"""历史管理测试：删除 + 列表 + 单条（projects 层 + API 层）。

用 monkeypatch 把 projects.json 指向临时文件，不碰真实数据。
"""
import pytest

from app import projects as projects_mod


@pytest.fixture
def tmp_projects(tmp_path, monkeypatch):
    """把 projects 文件指到临时路径并预置两条历史。"""
    monkeypatch.setattr(projects_mod, "_PROJECTS_FILE", str(tmp_path / "projects.json"))
    projects_mod.save_project({
        "id": "p1", "topic": "秦始皇修长城", "created_at": 100,
        "status": "success", "steps": 5, "cost": 0.1, "iterations": 1,
        "html": "<html>v1</html>",
    })
    projects_mod.save_project({
        "id": "p2", "topic": "郑和下西洋", "created_at": 200,
        "status": "success", "steps": 6, "cost": 0.2, "iterations": 1,
        "html": "<html>v2</html>",
    })
    return tmp_path


# ── projects 层 ──

def test_delete_project(tmp_projects):
    assert projects_mod.delete_project("p1") is True
    ids = [p["id"] for p in projects_mod.get_projects()]
    assert ids == ["p2"]


def test_delete_missing_project(tmp_projects):
    assert projects_mod.delete_project("nope") is False


# ── API 层 ──

def test_history_api_roundtrip(tmp_projects):
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)

    # 列表
    r = client.get("/api/history")
    assert r.status_code == 200
    assert [p["id"] for p in r.json()["projects"]] == ["p2", "p1"]

    # 单条
    r = client.get("/api/history/p1")
    assert r.status_code == 200
    assert r.json()["topic"] == "秦始皇修长城"

    # 删除
    r = client.delete("/api/history/p2")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert len(client.get("/api/history").json()["projects"]) == 1

    # 404
    r = client.get("/api/history/nope")
    assert r.status_code == 404
