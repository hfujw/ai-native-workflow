"""生成参数（前端设置）→ orchestrator 会话级覆盖测试。"""

from app.agent.orchestrator import apply_gen_params


def _base_ctx() -> dict:
    return {
        "max_steps": 20,
        "budget_total": 1.0,
        "search_max": 8,
        "search_enabled": True,
    }


def test_params_override_defaults():
    ctx = _base_ctx()
    apply_gen_params(ctx, {
        "agentSteps": 5, "llmSteps": 3, "budget": 0.5,
        "searchMax": 2, "searchEnabled": False,
    })
    assert ctx["max_steps"] == 5
    assert ctx["budget_total"] == 0.5
    assert ctx["search_max"] == 2
    assert ctx["search_enabled"] is False
    assert ctx["llm_steps"] == 3


def test_params_empty_keeps_defaults():
    ctx = _base_ctx()
    apply_gen_params(ctx, None)
    assert ctx["max_steps"] == 20
    assert ctx["budget_total"] == 1.0
    assert ctx["search_max"] == 8
    assert ctx["search_enabled"] is True


def test_params_partial_override():
    ctx = _base_ctx()
    apply_gen_params(ctx, {"budget": 0.2})
    assert ctx["budget_total"] == 0.2
    assert ctx["max_steps"] == 20  # 未传的保持默认
    assert ctx["search_enabled"] is True  # 未传默认开启


def test_params_sanitize_bounds():
    ctx = _base_ctx()
    apply_gen_params(ctx, {"agentSteps": 0, "budget": -1, "searchMax": -5})
    assert ctx["max_steps"] == 1  # 至少 1 步
    assert ctx["budget_total"] == 0.0  # 至少 0
    assert ctx["search_max"] == 0


def test_params_cap_upper_bounds():
    """超大参数必须被上限拦住（防烧钱）：步数 ≤100、搜索 ≤20。"""
    ctx = _base_ctx()
    apply_gen_params(ctx, {"agentSteps": 99999, "searchMax": 999, "llmSteps": 99999})
    assert ctx["max_steps"] == 100
    assert ctx["search_max"] == 20
    assert ctx["llm_steps"] == 100


def test_generate_api_accepts_params_and_model():
    """REST /api/generate 能接收 params + model 且不炸（空主题仍 400）。"""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    r = client.post("/api/generate", json={
        "topic": "", "params": {"agentSteps": 5, "budget": 0.5}, "model": "deepseek-Pro",
    })
    assert r.status_code == 400
