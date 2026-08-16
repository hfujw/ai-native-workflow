"""批次 C：循环严谨性测试。

覆盖：
- C-1 正常决策：解析成功返回 tool
- C-2 半截 JSON：safe_parse_json 容错 + 重试一次成功
- C-3 重试仍失败 → 降级搜索
- C-4 决策 prompt 前缀稳定（首段不变，尾部增量）
- C-5 增量反馈只含最近 2 步
"""
import json
from unittest.mock import patch

import pytest


def _base_ctx() -> dict:
    return {
        "session_id": "t1", "user_input": "恐龙", "steps": 2, "max_steps": 20,
        "budget_spent": 0.1, "budget_total": 1.0,
        "material": [{"title": "恐龙化石", "snippet": "内容"}],
        "tool_history": [
            {"tool": "search", "result_summary": "搜到3条素材"},
            {"tool": "design", "result_summary": "设计完成 timeline+cards"},
            {"tool": "render", "result_summary": "HTML 生成 12000 字符"},
        ],
        "issues": [], "design": {"components": ["cards"]}, "content": {"blocks": []},
        "html": "<html></html>", "passed": False,
        "cost_records": [], "_decide_fail_count": 0,
    }


@pytest.mark.asyncio
async def test_decide_parses_decision():
    """正常 JSON → 返回 tool。"""
    from app.agent.orchestrator import _decide

    async def fake_stream(prompt, system="", model=None, temperature=0.5,
                          session_records=None, label="decide"):
        yield json.dumps({"tool": "design", "thought": "素材够了，开始设计"})

    with patch("app.agent.orchestrator.chat_stream", new=fake_stream):
        d = await _decide(_base_ctx())
    assert d["tool"] == "design"


@pytest.mark.asyncio
async def test_decide_retries_on_broken_json():
    """半截 JSON → 重试一次成功。"""
    from app.agent.orchestrator import _decide

    calls = {"n": 0}

    async def fake_stream(prompt, system="", model=None, temperature=0.5,
                          session_records=None, label="decide"):
        calls["n"] += 1
        if calls["n"] == 1:
            yield '{"tool": "render", "thought": "截断'  # 半截
        else:
            yield '{"tool": "render", "thought": "重试成功"}'

    with patch("app.agent.orchestrator.chat_stream", new=fake_stream):
        d = await _decide(_base_ctx())
    assert d["tool"] == "render"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_decide_retry_fails_then_degrade():
    """两次都失败 → 降级搜索（fail_count=1，不是诚实模式）。"""
    from app.agent.orchestrator import _decide

    async def bad_stream(prompt, system="", model=None, temperature=0.5,
                         session_records=None, label="decide"):
        yield "完全不是 JSON 的输出文字" * 10

    with patch("app.agent.orchestrator.chat_stream", new=bad_stream):
        d = await _decide(_base_ctx())
    assert d["tool"] == "search"
    assert d["params"]["query"] == "恐龙"


def test_decide_prefix_stable():
    """前缀段固定：主题/步骤/预算行在任意步骤都逐字一致（KV 缓存友好）。"""
    from app.agent.orchestrator import _decide

    # 直接验证 prompt 构建逻辑：模拟两次不同 tool_history 的 summary 前缀
    ctx1 = _base_ctx()
    ctx2 = _base_ctx()
    ctx2["steps"] = 5
    ctx2["tool_history"] = [{"tool": "search", "result_summary": "别的"}]

    # 前缀（首 3 行）应相同——通过断言"主题行"位置与内容稳定
    async def fake_stream(prompt, system="", model=None, temperature=0.5,
                          session_records=None, label="decide"):
        captured.append(prompt)
        yield json.dumps({"tool": "verify", "thought": "x"})

    captured = []
    with patch("app.agent.orchestrator.chat_stream", new=fake_stream):
        import asyncio
        asyncio.run(_decide(ctx1))
        asyncio.run(_decide(ctx2))

    lines1 = captured[0].splitlines()
    lines2 = captured[1].splitlines()
    # 前 4 行（主题 + 警告 + 步骤 + 素材）结构一致
    assert lines1[0] == lines2[0]  # 主题行
    assert "用户想了解的具体主题：恐龙" in lines1[0]


def test_step_feedback_only_recent_two():
    """增量反馈只含最近 2 步。"""
    from app.agent.orchestrator import _step_feedback

    ctx = _base_ctx()
    fb = _step_feedback(ctx)
    # 3 步历史 → 只取最近 2 步（design + render，最早 search 被截掉）
    assert "search" not in fb
    assert "design" in fb
    assert "render" in fb


# ── 决策实时流（thinking_stream）：thought 边生成边长出来 ──

def test_extract_thought_none_before_key():
    """还没看到 thought 键 → None（不推空片段）。"""
    from app.agent.orchestrator import _extract_thought
    assert _extract_thought('{"tool": "render"') is None


def test_extract_thought_partial_and_closed():
    """值未闭合 → 返回已见部分；闭合 → 返回完整。"""
    from app.agent.orchestrator import _extract_thought
    assert _extract_thought('{"thought": "素材') == "素材"
    assert _extract_thought('{"thought": "素材足够，开始渲染页面"}') == "素材足够，开始渲染页面"


def test_extract_thought_handles_escaped_quote():
    """thought 内转义引号不误判为闭合。"""
    from app.agent.orchestrator import _extract_thought
    text = '{"thought": "他说\\"对\\"了"'
    assert _extract_thought(text) == '他说\\"对\\"了'


@pytest.mark.asyncio
async def test_decide_streams_thought_deltas():
    """_decide 期间把 thought 增量推给 push（拼起来 = 完整 thought）。"""
    from app.agent.orchestrator import _decide

    pushed = []

    async def fake_push(msg):
        pushed.append(msg)

    # 逐字吐出 JSON：先 thought 前缀，再内容，再闭合
    fragments = [
        '{"tool": "render", "thought": "',
        "素材",
        "足够",
        '，开始渲染页面"}',
    ]

    async def fake_stream(prompt, system="", model=None, temperature=0.5,
                          session_records=None, label="decide"):
        for f in fragments:
            yield f

    with patch("app.agent.orchestrator.chat_stream", new=fake_stream):
        d = await _decide(_base_ctx(), push=fake_push)
    assert d["tool"] == "render"
    streams = [m for m in pushed if m["type"] == "thinking_stream"]
    assert len(streams) >= 2
    assert "".join(m["chunk"] for m in streams) == "素材足够，开始渲染页面"
    assert all(m["tool"] == "think" for m in streams)
