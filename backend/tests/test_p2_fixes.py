"""P2 修复回归测试——对抗性审查的 P2 遗留项。

覆盖：
- P2-5  dispatch 透传 LLM 的 params（search 用 LLM 的 query）
- P2-7  rate_limiter.stats 返回真实花费（不再是硬编码假数据）
- P2-8  状态后端不可用 → fail-closed（限流不静默失效）
"""
from unittest.mock import AsyncMock, patch

import pytest

# ═══════════════════════════════════════════════════════════════
# P2-5：LLM 决策的 params 透传给工具
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_search_uses_llm_query_param():
    """LLM 决策的 search query 必须透传给 ResearcherAgent。"""
    from app.agents.supervisor import dispatch

    with patch("app.agents.supervisor.ResearcherAgent") as MockRA:
        instance = MockRA.return_value
        instance.run = AsyncMock(return_value={"tool": "search", "results": [], "count": 0, "level": "none"})

        ctx = {"user_input": "原始主题", "material": [], "cost_records": []}
        await dispatch(ctx, "search", {"query": "LLM想换的关键词"})

        assert instance.run.call_args.kwargs.get("topic") == "LLM想换的关键词"


@pytest.mark.asyncio
async def test_search_falls_back_to_user_input_without_params():
    """params 无 query 时退回原始主题。"""
    from app.agents.supervisor import dispatch

    with patch("app.agents.supervisor.ResearcherAgent") as MockRA:
        instance = MockRA.return_value
        instance.run = AsyncMock(return_value={"tool": "search", "results": [], "count": 0, "level": "none"})

        ctx = {"user_input": "原始主题", "material": [], "cost_records": []}
        await dispatch(ctx, "search", None)

        assert instance.run.call_args.kwargs.get("topic") == "原始主题"


# ═══════════════════════════════════════════════════════════════
# P2-7：stats 真实数据
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_stats_returns_real_spent():
    """stats 必须反映真实累计花费，不是硬编码 0.0。"""
    from app.network.rate_limiter import rate_limiter

    await rate_limiter.record_cost(1.23)
    stats = await rate_limiter.stats()

    assert stats["daily_spent"] == 1.23
    assert stats["daily_budget"] == 5.0


# ═══════════════════════════════════════════════════════════════
# P2-8：后端不可用 → fail-closed
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_can_generate_fails_closed_when_backend_down():
    """Redis 宕机时限流必须 fail-closed，不静默放行。"""
    import app.network.rate_limiter as rl
    from app.network.rate_limiter import rate_limiter

    class _DownBackend:
        available = False

    original_state = rl.state
    rl.state = _DownBackend()
    try:
        allowed, reason = await rate_limiter.can_generate("8.8.8.8")
        assert not allowed
        assert "不可用" in reason
    finally:
        rl.state = original_state
