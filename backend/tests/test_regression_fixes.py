"""回归测试——对抗性审查（2026-08-11）修复项的防复发。

覆盖：
- P0-1  ctx["issues"] 统一为 dict；_decide 遇到混合类型不崩
- P1-3  chat()/chat_stream() 不传 session_records 时不引用已删除的 _cost_records
"""
import json
from unittest.mock import AsyncMock, patch

import pytest

# ═══════════════════════════════════════════════════════════════
# P0-1：issues 类型统一（orchestrator.py:204 曾塞字符串 → .get() 崩）
# ═══════════════════════════════════════════════════════════════

def _ctx_with_render_fail() -> dict:
    """修复后的 orchestrator 在 render 截断时写入的 ctx 形态。"""
    return {
        "user_input": "测试主题",
        "steps": 1,
        "max_steps": 20,
        "budget_spent": 0.15,
        "budget_total": 1.0,
        "material": [],
        "design": None,
        "content": None,
        "html": "",
        "passed": False,
        "issues": [{"severity": "critical", "category": "incomplete",
                    "description": "render自动失败：HTML截断"}],
        "tool_history": [{"tool": "render", "result_summary": "HTML 生成完毕，0 字符，结构截断需重试"}],
        "cost_records": [],
    }


async def _decide(ctx: dict):
    """调用 orchestrator._decide，chat_stream mock 成固定 JSON。"""
    from app.agent.orchestrator import _decide
    payload = json.dumps({"tool": "render", "thought": "重新渲染"})

    async def fake_stream(*args, **kwargs):
        yield payload

    with patch("app.agent.orchestrator.chat_stream", fake_stream):
        return await _decide(ctx)


@pytest.mark.asyncio
async def test_render_fail_issue_is_dict():
    """render 截断的 issue 必须是 dict——字符串会让后续 .get() 崩溃。"""
    ctx = _ctx_with_render_fail()
    assert all(isinstance(i, dict) for i in ctx["issues"])


@pytest.mark.asyncio
async def test_decide_survives_dict_issues():
    """纯 dict issues 下 _decide 正常出决策。"""
    decision = await _decide(_ctx_with_render_fail())
    assert decision["tool"] == "render"


@pytest.mark.asyncio
async def test_decide_survives_mixed_issues():
    """即使 issues 混入历史字符串，_decide 也不崩（isinstance 防御）。"""
    ctx = _ctx_with_render_fail()
    ctx["issues"].append("历史遗留字符串 issue")  # 兼容旧数据形态
    decision = await _decide(ctx)
    assert decision["tool"] == "render"


# ═══════════════════════════════════════════════════════════════
# P1-3：chat/chat_stream 不传 session_records 时不再引用 _cost_records
# ═══════════════════════════════════════════════════════════════

class _Choice:
    def __init__(self):
        self.message = type("M", (), {"content": "ok"})()


class _Usage:
    prompt_tokens = 10
    completion_tokens = 20
    total_tokens = 30


class _FakeResp:
    choices = [_Choice()]
    usage = _Usage()


@pytest.mark.asyncio
async def test_chat_without_session_records_no_nameerror():
    """chat() 无 session_records 时不再触发 NameError（_cost_records 已删）。"""
    import app.llm.circuit_breaker as cb
    from app.llm import client as llm_client

    async def fake_create(**kwargs):
        return _FakeResp()

    class _PassThroughBreaker:
        async def call(self, coro):
            return await coro

    with patch.object(llm_client._default_client.chat.completions, "create",
                      AsyncMock(side_effect=fake_create)), \
         patch.object(cb, "llm_breaker", _PassThroughBreaker()):
        text = await llm_client.chat("你好", session_records=None)

    assert text == "ok"


class _Delta:
    content = "片段"


class _StreamChoice:
    delta = _Delta()


class _Chunk:
    choices = [_StreamChoice()]
    usage = None


@pytest.mark.asyncio
async def test_chat_stream_without_session_records_no_nameerror():
    """chat_stream() 无 session_records 时不再触发 NameError。"""
    from app.llm import client as llm_client

    async def fake_stream_create(**kwargs):
        async def gen():
            yield _Chunk()
        return gen()

    with patch.object(llm_client._default_client.chat.completions, "create",
                      AsyncMock(side_effect=fake_stream_create)):
        chunks = [c async for c in llm_client.chat_stream("你好", session_records=None)]

    assert chunks == ["片段"]
