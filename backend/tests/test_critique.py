"""批次 B：批评家创造闭环测试。

覆盖：
- B-1 critique_design 返回 issues（有批评）
- B-2 critique_design 失败 → 空列表（不阻塞）
- B-3 brainstorm 集成：批评家挑刺 → 修正设计
- B-4 降级方案不批评（成本优先）
- B-5 批评修正失败 → 沿用原设计
"""
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_critique_returns_issues():
    """批评家正常返回 issues。"""
    from app.llm.judge import critique_design

    async def fake_chat_json(prompt, system="", model=None, session_records=None):
        return '{"issues": [{"dimension": "visual", "problem": "配色太泛", "fix": "用秦汉黑红金"}]}'

    with patch("app.llm.judge.chat_json", new=fake_chat_json):
        issues = await critique_design({"components": ["cards"], "visual_hint": "简洁大方"},
                                       "秦始皇", [{"title": "秦始皇"}], [], "m")
    assert len(issues) == 1
    assert issues[0]["dimension"] == "visual"


@pytest.mark.asyncio
async def test_critique_failure_returns_empty():
    """批评家调用失败 → 空列表，不阻塞。"""
    from app.llm.judge import critique_design

    async def bad(prompt, system="", model=None, session_records=None):
        raise RuntimeError("挂了")

    with patch("app.llm.judge.chat_json", new=bad):
        issues = await critique_design({"components": ["cards"]}, "秦始皇", [], [], "m")
    assert issues == []


@pytest.mark.asyncio
async def test_critique_empty_design():
    """无设计 → 空列表。"""
    from app.llm.judge import critique_design

    assert await critique_design(None, "秦始皇", []) == []


@pytest.mark.asyncio
async def test_brainstorm_critic_fixes_design():
    """集成：综合出方案 → 批评家挑刺 → 修正。"""
    from app.agent.brainstorm import brainstorm_design

    plan = {"_angle": "visual", "_angle_name": "视觉型", "components": ["cards"],
            "structure": "S", "visual_hint": "V", "rationale": "R"}

    async def fake_synthesize(plans, user_input, material, session_records, model, preferences):
        return {"components": ["cards"], "structure": "S", "visual_hint": "简洁大方",
                "rationale": "R", "tool": "design", "_synthesized": True}

    async def fake_critique(design, user_input, material, session_records, model):
        return [{"dimension": "visual", "problem": "太泛", "fix": "黑金配色"}]

    async def fake_fix(design, issues, user_input, session_records, model):
        return {"components": ["cards"], "structure": "S", "visual_hint": "黑金配色",
                "rationale": "修正后", "tool": "design", "_critic_fixed": True}

    with patch("app.agent.brainstorm.spawn_creative_agents", new=AsyncMock(return_value=[plan])), \
         patch("app.agent.brainstorm.synthesize_design", new=fake_synthesize), \
         patch("app.llm.judge.critique_design", new=fake_critique), \
         patch("app.agent.brainstorm._fix_design", new=fake_fix):
        d = await brainstorm_design("秦始皇", [{"title": "秦始皇"}], [], "m")
    assert d.get("_critic_fixed") is True
    assert d["visual_hint"] == "黑金配色"


@pytest.mark.asyncio
async def test_brainstorm_skips_critique_on_fallback():
    """降级方案（非 _synthesized）→ 不批评。"""
    from app.agent.brainstorm import brainstorm_design

    fallback = {"components": ["encyclopedia"], "rationale": "降级", "tool": "design"}

    async def fake_synthesize(plans, user_input, material, session_records, model, preferences):
        return dict(fallback)

    with patch("app.agent.brainstorm.spawn_creative_agents", new=AsyncMock(return_value=[])), \
         patch("app.agent.brainstorm.synthesize_design", new=fake_synthesize), \
         patch("app.llm.judge.critique_design", new=AsyncMock()) as m:
        d = await brainstorm_design("秦始皇", [], [], "m")
    m.assert_not_called()
    assert d["components"] == ["encyclopedia"]


@pytest.mark.asyncio
async def test_critic_fix_failure_keeps_original():
    """修正失败 → 沿用原设计。"""
    from app.agent.brainstorm import _fix_design

    async def bad(prompt, system="", model=None, session_records=None):
        return "not json"

    with patch("app.agent.brainstorm.chat_json", new=bad):
        fixed = await _fix_design({"components": ["cards"]}, [{"problem": "x", "fix": "y"}],
                                  "秦始皇", [], "m")
    assert fixed is None
