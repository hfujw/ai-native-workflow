"""OpenAI 兼容网关测试 — /v1/responses 流式协议 + 新生成/迭代两条路径。"""

import json

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _events(text: str) -> list[dict]:
    """解析 SSE 文本 → 事件对象列表（跳过 [DONE]）。"""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data: "):
            continue
        payload = line[6:]
        if payload == "[DONE]":
            continue
        out.append(json.loads(payload))
    return out


def _assert_stream_types(events: list[dict]) -> None:
    types = [e["type"] for e in events]
    assert types[0] == "response.created"
    assert types[1] == "response.in_progress"
    assert "response.output_item.added" in types
    assert "response.content_part.added" in types
    assert types[-1] == "response.completed"  # 最后一个事件（[DONE] 已过滤）
    assert "response.output_text.done" in types


def test_responses_generate_streams_thinking(monkeypatch):
    """新生成：orchestrator 推送 → SSE 思考流 → 成品落盘 → completed。"""

    async def fake_orchestrator(state):
        push = state.get("_push")
        await push({"type": "thinking", "tool": "search", "thought": "先搜索关键事实"})
        await push({"type": "tool_result", "tool": "search", "summary": "找到 5 条素材"})
        await push({"type": "thinking", "tool": "render", "thought": "开始渲染页面"})
        await push({"type": "complete", "html": "<html>成品</html>"})
        return {"status": "success", "html": "<html>成品</html>"}

    monkeypatch.setattr("app.agent.orchestrator.orchestrator_node", fake_orchestrator)
    saved = {}

    def fake_save_page(sid, topic, html, iteration):
        saved["page"] = (sid, topic, html, iteration)
        return f"/works/{sid}.html"

    def fake_save_project(project):
        saved["project"] = project

    monkeypatch.setattr("app.workspace.save_page", fake_save_page)
    monkeypatch.setattr("app.projects.save_project", fake_save_project)

    with client.stream(
        "POST", "/v1/responses",
        json={"input": [{"role": "user", "content": "秦始皇是什么人"}], "model": "lumen-deep"},
    ) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        text = "".join(r.iter_text())

    events = _events(text)
    _assert_stream_types(events)

    # 思考文本出现在 delta 里
    deltas = "".join(
        e.get("delta", "") for e in events if e["type"] == "response.output_text.delta"
    )
    assert "先搜索关键事实" in deltas
    assert "找到 5 条素材" in deltas
    assert "✨ 成品已生成" in deltas

    # 落盘被执行
    assert saved["project"]["html"] == "<html>成品</html>"
    assert saved["project"]["messages"][0]["role"] == "user"


def test_responses_no_user_message_400(monkeypatch):
    """空 input → 400。"""

    async def fake_orchestrator(state):
        raise AssertionError("不应被调用")

    monkeypatch.setattr("app.agent.orchestrator.orchestrator_node", fake_orchestrator)

    with client.stream("POST", "/v1/responses", json={"input": [], "model": "x"}) as r:
        assert r.status_code == 400


def test_responses_iteration_refines(monkeypatch):
    """历史里已有成品标记 → 走 refine_page（迭代改页面）。"""

    async def fake_refine(design, content, material, html, user_input, instruction, push, records, model=None):
        await push({"type": "thinking", "tool": "render", "thought": "按用户要求重新渲染"})
        await push({"type": "complete", "html": "<html>改版</html>"})
        return {"html": "<html>改版</html>", "design": {}, "content": {}, "material": []}

    monkeypatch.setattr("app.agent.orchestrator.refine_page", fake_refine)
    called = {"refine": False}

    async def fake_orchestrator(state):
        called["refine"] = True
        raise AssertionError("有成品历史应走 refine，不该走新生成")

    monkeypatch.setattr("app.agent.orchestrator.orchestrator_node", fake_orchestrator)

    def fake_get_project(pid):
        return {"id": pid, "topic": "秦始皇", "versions": [{"html": "<html>旧版</html>"}]}

    monkeypatch.setattr("app.projects.get_project", fake_get_project)

    def fake_save_page(sid, topic, html, iteration):
        return f"/works/{sid}.html"

    def fake_save_project(project):
        pass

    monkeypatch.setattr("app.workspace.save_page", fake_save_page)
    monkeypatch.setattr("app.projects.save_project", fake_save_project)

    # 历史：assistant 消息带成品标记 + 8 位作品 id
    history_input = [
        {"role": "user", "content": "秦始皇是什么人"},
        {"role": "assistant", "content": "✨ 成品已生成 [abc12345]\nhttp://localhost:8001/works/abc12345"},
        {"role": "user", "content": "把配色改成蓝色"},
    ]

    with client.stream(
        "POST", "/v1/responses",
        json={"input": history_input, "model": "lumen-deep"},
    ) as r:
        assert r.status_code == 200
        text = "".join(r.iter_text())

    assert not called["refine"]  # 没走新生成
    events = _events(text)
    deltas = "".join(e.get("delta", "") for e in events if e["type"] == "response.output_text.delta")
    assert "按用户要求重新渲染" in deltas
    assert "改版" in deltas or "成品已生成" in deltas


def test_models_endpoint():
    r = client.get("/v1/models")
    assert r.status_code == 200
    data = r.json()
    assert data["object"] == "list"
    assert any(m["id"] == "lumen-deep" for m in data["data"])
