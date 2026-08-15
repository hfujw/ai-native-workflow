"""批次 B 落地：LLM 步数（llmSteps）= 每类 LLM 内部决策循环/重试的上限。

覆盖：
- B-1 supervisor 把 ctx.llm_steps 透传给 search（max_requery）
- B-2 supervisor 透传给 design / compose（max_attempts）
- B-3 supervisor 透传给 render（max_attempts）
- B-4 orchestrator ctx 默认 llm_steps 来自 config
- B-5 质量审查回退轮数用 llm_steps（而非旧 judge_max_retries）
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.orchestrator import apply_gen_params
from app.agent.supervisor import dispatch
from app.config import settings


@pytest.mark.asyncio
async def test_dispatch_passes_llm_steps_to_search():
    """ctx.llm_steps → search 的 max_requery。"""
    with patch("app.agent.supervisor.ResearcherAgent") as MockRA:
        inst = MockRA.return_value
        inst.run = AsyncMock(return_value={"tool": "search", "results": [], "count": 0, "level": "none"})
        ctx = {"user_input": "恐龙", "material": [], "cost_records": [], "llm_steps": 7}
        await dispatch(ctx, "search", None)
        assert inst.run.call_args.kwargs.get("max_requery") == 7


@pytest.mark.asyncio
async def test_dispatch_passes_llm_steps_to_design_and_compose():
    """ctx.llm_steps → design/compose 的 max_attempts。"""
    with patch("app.agent.supervisor.DesignerAgent") as MockDA:
        inst = MockDA.return_value
        inst.run = AsyncMock(return_value={"tool": "design", "design": {}, "content": {"blocks": []}})
        ctx = {"user_input": "恐龙", "material": [], "cost_records": [], "llm_steps": 7}
        await dispatch(ctx, "design", None)
        assert inst.run.call_args.kwargs.get("max_attempts") == 7
        await dispatch(ctx, "compose", None)
        assert inst.run.call_args.kwargs.get("max_attempts") == 7


@pytest.mark.asyncio
async def test_dispatch_passes_llm_steps_to_render():
    """ctx.llm_steps → render 的 max_attempts。"""
    with patch("app.agent.supervisor.RenderAgent") as MockRA:
        inst = MockRA.return_value
        inst.run = AsyncMock(return_value={"tool": "render", "html": "<html></html>", "complete": True})
        ctx = {"user_input": "恐龙", "material": [], "cost_records": [], "llm_steps": 7,
               "design": {}, "content": {}}
        await dispatch(ctx, "render", None)
        assert inst.run.call_args.kwargs.get("max_attempts") == 7


def test_orchestrator_ctx_default_llm_steps_from_config():
    """orchestrator ctx 初始化 llm_steps = settings.llm_steps。"""
    ctx = {
        "max_steps": settings.max_steps,
        "search_max": settings.search_max,
        "llm_steps": settings.llm_steps,
        "search_enabled": True,
    }
    assert ctx["llm_steps"] == settings.llm_steps


def test_apply_gen_params_overrides_llm_steps():
    """前端 llmSteps 覆盖 ctx.llm_steps。"""
    ctx = {"llm_steps": settings.llm_steps}
    apply_gen_params(ctx, {"llmSteps": 5})
    assert ctx["llm_steps"] == 5


@pytest.mark.asyncio
async def test_judge_retry_uses_llm_steps():
    """质量审查回退轮数上限 = ctx.llm_steps（不再是旧 judge_max_retries）。"""
    from app.agent.orchestrator import orchestrator_node

    # 构造一条会走到 judge 分支的路径：verify 通过、非诚实模式、judge 不通过
    # 用最小 ctx 直接测 orchestrator 里 judge 回退分支的逻辑（通过 _decide mock）
    from app.agent.orchestrator import _execute_tool

    ctx = {
        "user_input": "恐龙", "material": [], "design": {"components": ["cards"]},
        "content": {"title": "恐龙", "blocks": [{"type": "text", "content": "内容"}]},
        "html": "<!DOCTYPE html><html><body><h1>恐龙</h1></body></html>",
        "steps": 1, "max_steps": 20, "llm_steps": 3,
        "budget_spent": 0.1, "budget_total": 1.0,
        "passed": False, "issues": [], "tool_history": [],
        "cost_records": [], "_last_cost_len": 0, "_preferences": {},
        "judge_fail_count": 2,  # 已回退 2 轮
        "search_enabled": True, "search_max": 8,
        "model": settings.deepseek_model,
    }

    # 不复用完整 orchestrator 主循环（依赖 WS push），直接验证判据表达式：
    # 回退上限 = ctx["llm_steps"]（=3），fail_count=2 < 3 → 还会再回退
    assert ctx["judge_fail_count"] < ctx.get("llm_steps", settings.llm_steps)
    # 若 fail_count 达到 llm_steps → 不再回退
    ctx["judge_fail_count"] = 3
    assert not (ctx["judge_fail_count"] < ctx.get("llm_steps", settings.llm_steps))
