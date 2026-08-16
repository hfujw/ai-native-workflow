"""Phase C 测试——多轮迭代（refine_page）+ 偏好提取。"""
from unittest.mock import AsyncMock, patch

import pytest

# ═══════════════════════════════════════════════════════════════
# C1: refine_page 多轮迭代
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_refine_rerender_injects_hint():
    """rerender 路径：用户要求注入 visual_hint，重新渲染。"""
    from app.agent.orchestrator import refine_page

    async def fake_stream(*args, **kwargs):
        yield '{"action": "rerender", "hint": "换成暗色"}'

    with patch("app.agent.orchestrator.chat_stream", fake_stream), \
         patch("app.tools.render.RenderAgent") as MockRA:
        instance = MockRA.return_value
        instance.run = AsyncMock(return_value={"html": "<!DOCTYPE html><html></html>", "complete": True})
        result = await refine_page(
            {"components": ["cards"], "visual_hint": "浅色"}, {"blocks": []}, [],
            "<html/>", "测试", "换成暗色", None, [])

    assert result["action"] == "rerender"
    assert result["html"] == "<!DOCTYPE html><html></html>"
    called_design = instance.run.call_args.args[0]
    assert "换成暗色" in called_design["visual_hint"]


@pytest.mark.asyncio
async def test_refine_redesign_calls_designer():
    """redesign 路径：重设计+文案，再渲染。"""
    from app.agent.orchestrator import refine_page

    async def fake_stream(*args, **kwargs):
        yield '{"action": "redesign", "hint": "改成时间轴"}'

    with patch("app.agent.orchestrator.chat_stream", fake_stream), \
         patch("app.tools.design.DesignerAgent") as MockDA, \
         patch("app.tools.render.RenderAgent") as MockRA:
        da_instance = MockDA.return_value
        da_instance.run = AsyncMock(return_value={
            "design": {"components": ["timeline"]}, "content": {"blocks": [{"component": "timeline"}]}})
        ra_instance = MockRA.return_value
        ra_instance.run = AsyncMock(return_value={"html": "<html></html>", "complete": True})
        result = await refine_page(
            {"components": ["cards"]}, {"blocks": []}, [], "<html/>", "测试", "改成时间轴", None, [])

    assert result["action"] == "redesign"
    assert result["design"]["components"] == ["timeline"]
    assert result["content"]["blocks"][0]["component"] == "timeline"


@pytest.mark.asyncio
async def test_refine_falls_back_to_rerender_on_bad_decision():
    """refine 决策解析失败 → 默认 rerender，不崩。"""
    from app.agent.orchestrator import refine_page

    async def fake_stream(*args, **kwargs):
        yield "不是 JSON {{{"

    with patch("app.agent.orchestrator.chat_stream", fake_stream), \
         patch("app.tools.render.RenderAgent") as MockRA:
        instance = MockRA.return_value
        instance.run = AsyncMock(return_value={"html": "<html></html>", "complete": True})
        result = await refine_page({}, {"blocks": []}, [], "<html/>", "测试", "改一下", None, [])

    assert result["action"] == "rerender"  # 兜底到默认动作
