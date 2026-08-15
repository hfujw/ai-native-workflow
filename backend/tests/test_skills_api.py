"""Skill API 测试：列表 builtin 标记 / 安装 / 删除（临时目录，不碰运行时 skills/）。"""

import pytest

from app import skills as skills_mod


@pytest.fixture
def tmp_skills(tmp_path, monkeypatch):
    """把 skills 目录指到临时路径并播种内置。"""
    monkeypatch.setattr(skills_mod, "_SKILLS_DIR", str(tmp_path / "skills"))
    skills_mod._ensure_seeded()
    return tmp_path


def test_list_skills_marks_builtin(tmp_skills):
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    r = client.get("/api/skills")
    assert r.status_code == 200
    skills = r.json()["skills"]
    assert any(s["id"] == "pixel" and s["builtin"] is True for s in skills)


def test_install_skill(tmp_skills):
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    r = client.post("/api/skills/install", json={
        "id": "myskill",
        "markdown": "---\nname: 我的技能\ntype: 工具\ndesc: 测试\n---\n指令正文",
    })
    assert r.status_code == 200
    assert r.json()["id"] == "myskill"
    assert r.json()["builtin"] is False

    # 列表里能看到，且非 builtin
    skills = client.get("/api/skills").json()["skills"]
    assert any(s["id"] == "myskill" and s["builtin"] is False for s in skills)


def test_install_skill_rejects_bad_id(tmp_skills):
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    r = client.post("/api/skills/install", json={
        "id": "../evil", "markdown": "---\nname: x\n---\n",
    })
    assert r.status_code == 400


def test_install_skill_rejects_bad_markdown(tmp_skills):
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    r = client.post("/api/skills/install", json={"id": "bad", "markdown": "没有 frontmatter"})
    assert r.status_code == 400


def test_delete_skill(tmp_skills):
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    client.post("/api/skills/install", json={
        "id": "tmpdel", "markdown": "---\nname: 待删\ntype: 工具\n---\n",
    })
    r = client.delete("/api/skills/tmpdel")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert client.get("/api/skills").json()["skills"]  # 其他 skill 不受影响


def test_delete_builtin_rejected(tmp_skills):
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    r = client.delete("/api/skills/pixel")
    assert r.status_code == 400


def test_delete_missing_404(tmp_skills):
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    assert client.delete("/api/skills/nope").status_code == 404
