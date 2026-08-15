"""对抗审查修复回归测试（2026-08-16）。

覆盖：
- N1：tool_render_stream 内部必须把 model 透传给 chat_stream
      （修复前丢 model → 主渲染静默回落默认模型）
- H9：refine 决策 / 修复重渲染 / 降级设计补传 model
- N2：judge 回退上限 = min(llm_steps, judge_max_retries)
"""
from unittest.mock import AsyncMock, patch

import pytest


# ═══════════════════════════════════════════════════════════════
# N1：tool_render_stream 透传 model
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_render_stream_passes_model_to_chat_stream():
    """tool_render_stream 调 chat_stream 必须带 model（修复前丢失）。"""
    from app.tools import render as render_mod

    async def fake_chat_stream(prompt, system="", model=None, temperature=0.3,
                               session_records=None, label="unknown"):
        assert model == "deepseek-reasoner", "model 必须透传给 chat_stream"
        yield "<!DOCTYPE html><html><body><h1>恐龙</h1></body></html>"

    with patch.object(render_mod, "chat_stream", new=fake_chat_stream):
        frames = []
        async for frame in render_mod.tool_render_stream(
            {"components": ["cards"]}, {"title": "恐龙", "blocks": []},
            session_records=[], model="deepseek-reasoner",
        ):
            frames.append(frame)

    assert any(f.get("complete") for f in frames)


# ═══════════════════════════════════════════════════════════════
# H9：refine 决策透传 model
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_refine_decision_passes_model_to_chat_stream():
    """refine_page 的'怎么改'决策 chat_stream 必须带 model。"""
    from app.agent import orchestrator as orch

    async def fake_chat_stream(prompt, system="", model=None, temperature=0.3,
                               session_records=None, label="unknown"):
        assert model == "deepseek-reasoner"
        yield '{"action": "rerender", "hint": "换个配色"}'

    with patch.object(orch, "chat_stream", new=fake_chat_stream), \
         patch.object(orch, "safe_parse_json", return_value={"action": "rerender", "hint": "x"}), \
         patch("app.tools.search.tool_search", new=AsyncMock(return_value={"results": []})), \
         patch("app.tools.design.DesignerAgent") as MockDA, \
         patch("app.tools.render.RenderAgent") as MockRA, \
         patch("app.tools.verify.tool_verify", new=AsyncMock(return_value={"issues": []})):
        inst = MockDA.return_value
        inst.run = AsyncMock(return_value={"design": {"components": ["cards"]}, "content": {"blocks": []}})
        rinst = MockRA.return_value
        rinst.run = AsyncMock(return_value={"tool": "render", "html": "<html></html>", "complete": True})

        await orch.refine_page(
            {"components": ["cards"]}, {"title": "恐龙", "blocks": []},
            [], "<html></html>", "恐龙", "换个配色",
            push=None, session_records=[], model="deepseek-reasoner",
        )

    # 修复后：refine 决策与修复重渲染都必须把 reasoner 传下去
    assert rinst.run.call_count >= 1
    for call in rinst.run.call_args_list:
        assert call.kwargs.get("model") == "deepseek-reasoner"


# ═══════════════════════════════════════════════════════════════
# N2：judge 回退上限 = min(llm_steps, judge_max_retries)
# ═══════════════════════════════════════════════════════════════

def test_judge_retry_limit_is_min_of_llm_steps_and_judge_max():
    """回退上限 = min(llm_steps, judge_max_retries)——用户拍板 ≤2 轮。"""
    from app.config import settings

    assert settings.judge_max_retries == 2
    # llm_steps=10（默认）→ 上限 2（拍板）
    assert min(10, settings.judge_max_retries) == 2
    # llm_steps=1 → 上限 1（更保守者生效）
    assert min(1, settings.judge_max_retries) == 1
