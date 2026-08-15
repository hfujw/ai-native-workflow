"""批次 A：发散-收敛设计（brainstorm）测试。

覆盖：
- A-1 三个创意子脑并行 spawn，成功方案返回
- A-2 子脑失败不阻塞其余（gather 容错）
- A-3 综合器把多视角合并成 1 个 design（components 并集）
- A-4 单视角成功时直接采用，不浪费综合调用
- A-5 全部失败 → 降级百科兜底
- A-6 综合器失败 → 回退第一个方案
- A-7 DesignerAgent 集成：主设计走 brainstorm（mock 验证调用）
"""
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_spawn_parallel_creative_agents():
    """三视角并行，返回全部成功方案。"""
    from app.agent.brainstorm import spawn_creative_agents

    async def fake_chat_json(prompt, system="", model=None, session_records=None):
        if "叙事设计师" in system:
            return '{"angle": "故事线", "components": ["timeline"], "structure": "S", "visual_hint": "V", "rationale": "R"}'
        if "视觉设计师" in system:
            return '{"angle": "视觉冲击", "components": ["cards"], "structure": "S", "visual_hint": "V", "rationale": "R"}'
        return '{"angle": "信息架构", "components": ["comparison"], "structure": "S", "visual_hint": "V", "rationale": "R"}'

    with patch("app.agent.brainstorm.chat_json", new=fake_chat_json):
        plans = await spawn_creative_agents("恐龙", [{"title": "恐龙", "snippet": "内容"}], [], "m")
    assert len(plans) == 3
    angles = {p["_angle"] for p in plans}
    assert angles == {"narrative", "visual", "informative"}


@pytest.mark.asyncio
async def test_one_creative_failure_does_not_block_others():
    """一个子脑失败 → 其余照常返回。"""
    from app.agent.brainstorm import spawn_creative_agents

    async def fake_chat_json(prompt, system="", model=None, session_records=None):
        if "叙事设计师" in system:
            raise RuntimeError("网络挂了")
        if "视觉设计师" in system:
            return '{"angle": "x", "components": ["cards"], "structure": "S", "visual_hint": "V", "rationale": "R"}'
        return None  # 信息型返回非法 → 失败

    with patch("app.agent.brainstorm.chat_json", new=fake_chat_json):
        plans = await spawn_creative_agents("恐龙", [{"title": "恐龙"}], [], "m")
    assert len(plans) == 1
    assert plans[0]["_angle"] == "visual"


@pytest.mark.asyncio
async def test_synthesize_merges_angles():
    """综合器收到多视角 → 输出含 components 的 design。"""
    from app.agent.brainstorm import synthesize_design

    plans = [
        {"_angle": "narrative", "_angle_name": "叙事型", "components": ["timeline"],
         "structure": "S1", "visual_hint": "V1", "rationale": "R1"},
        {"_angle": "visual", "_angle_name": "视觉型", "components": ["cards"],
         "structure": "S2", "visual_hint": "V2", "rationale": "R2"},
    ]
    async def fake_chat_json(prompt, system="", model=None, session_records=None):
        assert "叙事型" in prompt and "视觉型" in prompt  # 两个方案都进综合 prompt
        return '{"components": ["timeline", "cards"], "structure": "综合S", "visual_hint": "综合V", "rationale": "综合R"}'

    with patch("app.agent.brainstorm.chat_json", new=fake_chat_json):
        d = await synthesize_design(plans, "恐龙", [{"title": "恐龙"}], [], "m")
    assert d["components"] == ["timeline", "cards"]
    assert d["tool"] == "design"
    assert d.get("_synthesized") is True


@pytest.mark.asyncio
async def test_single_plan_used_without_synthesize_call():
    """单视角成功 → 直接采用，不再调综合器。"""
    from app.agent.brainstorm import synthesize_design

    plans = [{"_angle": "visual", "_angle_name": "视觉型", "components": ["cards"],
              "structure": "S", "visual_hint": "V", "rationale": "R"}]
    with patch("app.agent.brainstorm.chat_json", new=AsyncMock()) as m:
        d = await synthesize_design(plans, "恐龙", [], [], "m")
    m.assert_not_called()
    assert d["components"] == ["cards"]


@pytest.mark.asyncio
async def test_all_failed_falls_back():
    """全部子脑失败 → 百科兜底。"""
    from app.agent.brainstorm import brainstorm_design

    with patch("app.agent.brainstorm.spawn_creative_agents", new=AsyncMock(return_value=[])):
        d = await brainstorm_design("恐龙", [{"title": "恐龙"}], [], "m")
    assert d["components"] == ["encyclopedia"]


@pytest.mark.asyncio
async def test_synthesize_failure_uses_first_plan():
    """综合器异常 → 回退第一个方案。"""
    from app.agent.brainstorm import synthesize_design

    plans = [
        {"_angle": "narrative", "_angle_name": "叙事型", "components": ["timeline"],
         "structure": "S1", "visual_hint": "V1", "rationale": "R1"},
        {"_angle": "visual", "_angle_name": "视觉型", "components": ["cards"],
         "structure": "S2", "visual_hint": "V2", "rationale": "R2"},
    ]
    async def bad_chat_json(prompt, system="", model=None, session_records=None):
        raise RuntimeError("综合失败")

    with patch("app.agent.brainstorm.chat_json", new=bad_chat_json):
        d = await synthesize_design(plans, "恐龙", [], [], "m")
    assert d["components"] == ["timeline"]  # 第一个方案


@pytest.mark.asyncio
async def test_designer_agent_uses_brainstorm():
    """DesignerAgent 主设计路径调用 brainstorm_design。"""
    from app.tools.design import DesignerAgent

    with patch("app.tools.design.brainstorm_design", new=AsyncMock(return_value={
            "components": ["cards"], "structure": "S", "visual_hint": "V", "rationale": "R"})) as m, \
         patch("app.tools.design.tool_compose", new=AsyncMock(return_value={
            "title": "恐龙", "subtitle": "s",
            "blocks": [{"component": "cards", "position": 1,
                        "claims": [{"text": "恐龙", "source": "search_1", "confidence": "high"}]}],
            "fact_notes": "", "tool": "compose"})), \
         patch("app.tools.design.ResearcherAgent") as MockRA:
        inst = MockRA.return_value
        inst.listen = AsyncMock()
        agent = DesignerAgent()
        out = await agent.run([{"title": "恐龙", "snippet": "内容"}], "恐龙",
                              session_records=[], model="deepseek-chat")
        assert out["tool"] == "design"
        m.assert_awaited()  # 主设计路径确实走 brainstorm（覆盖度不足可能重试多次）
        assert out["design"]["components"] == ["cards"]
