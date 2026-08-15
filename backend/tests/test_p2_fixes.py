"""P2 修复回归测试——对抗性审查的 P2 遗留项。

覆盖：
- P2-5  dispatch 透传 LLM 的 params（search 用 LLM 的 query）
"""
from unittest.mock import AsyncMock, patch

import pytest

# ═══════════════════════════════════════════════════════════════
# P2-5：LLM 决策的 params 透传给工具
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_search_uses_llm_query_param():
    """LLM 决策的 search query 必须透传给 ResearcherAgent。"""
    from app.agent.supervisor import dispatch

    with patch("app.agent.supervisor.ResearcherAgent") as MockRA:
        instance = MockRA.return_value
        instance.run = AsyncMock(return_value={"tool": "search", "results": [], "count": 0, "level": "none"})

        ctx = {"user_input": "原始主题", "material": [], "cost_records": []}
        await dispatch(ctx, "search", {"query": "LLM想换的关键词"})

        assert instance.run.call_args.kwargs.get("topic") == "LLM想换的关键词"


@pytest.mark.asyncio
async def test_search_falls_back_to_user_input_without_params():
    """params 无 query 时退回原始主题。"""
    from app.agent.supervisor import dispatch

    with patch("app.agent.supervisor.ResearcherAgent") as MockRA:
        instance = MockRA.return_value
        instance.run = AsyncMock(return_value={"tool": "search", "results": [], "count": 0, "level": "none"})

        ctx = {"user_input": "原始主题", "material": [], "cost_records": []}
        await dispatch(ctx, "search", None)

        assert instance.run.call_args.kwargs.get("topic") == "原始主题"
