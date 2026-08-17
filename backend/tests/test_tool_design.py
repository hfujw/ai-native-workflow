"""测试 tool_design——用 mock LLM 响应，不调真实 API。"""
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.tools.design import tool_design, tool_compose


@pytest.fixture
def sample_material():
    return [
        {"title": "秦始皇统一六国", "snippet": "公元前221年", "content": ""},
        {"title": "长城修建", "snippet": "秦始皇征发民夫修建长城", "content": ""},
    ]


@pytest.mark.asyncio
async def test_normal_design(sample_material):
    """LLM 正常返回——解析成功。"""
    mock_response = json.dumps({"components": ["timeline", "cards"],
                                "rationale": "有明确时间线和人物", "structure": "顶时间轴下卡片",
                                "visual_hint": "秦汉黑红金"}, ensure_ascii=False)

    with patch("app.tools.design.chat_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = mock_response
        result = await tool_design(sample_material, "秦始皇修长城")

    assert result["tool"] == "design"
    assert result["components"] == ["timeline", "cards"]
    assert "时间线" in result["rationale"]


@pytest.mark.asyncio
async def test_design_with_fence(sample_material):
    """LLM 返回带 ```json ``` 围栏——strip_fence 清洗后正常。"""
    mock_response = '```json\n{"components": ["portrait"], "rationale": "人物核心", "structure": "单列", "visual_hint": "肖像风格"}\n```'

    with patch("app.tools.design.chat_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = mock_response
        result = await tool_design(sample_material, "秦始皇")

    assert result["components"] == ["portrait"]


@pytest.mark.asyncio
async def test_design_invalid_json(sample_material):
    """LLM 返回非法 JSON——降级为 encyclopedia。"""
    with patch("app.tools.design.chat_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = "这不是合法的 JSON {{{"
        result = await tool_design(sample_material, "秦始皇")

    assert result["tool"] == "design"
    assert result["components"] == ["encyclopedia"]
    assert "非法 JSON" in result["rationale"]


@pytest.mark.asyncio
async def test_design_empty_material():
    """无素材——直接降级，不调 LLM。"""
    result = await tool_design([], "随机话题")
    assert result["components"] == ["encyclopedia"]
    assert "无素材" in result["rationale"]


@pytest.mark.asyncio
async def test_design_llm_error(sample_material):
    """LLM API 异常——降级 encyclopedia。"""
    with patch("app.tools.design.chat_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.side_effect = TimeoutError("DeepSeek 超时")
        result = await tool_design(sample_material, "秦始皇")

    assert result["components"] == ["encyclopedia"]


# ── 方向 A：skill_config 注入（Skill 是编排策略）──

@pytest.mark.asyncio
async def test_design_skill_priority_injected(sample_material):
    """skill_config.design_priority 注入 design prompt——Skill 影响组件选择。"""
    mock_response = json.dumps({"components": ["datapanel", "cards"],
                                "rationale": "数据优先", "structure": "数据面板+卡片",
                                "visual_hint": "深色数据风"}, ensure_ascii=False)

    with patch("app.tools.design.chat_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = mock_response
        await tool_design(sample_material, "某数据主题", skill_config={
            "design_priority": ["datapanel", "comparison", "cards", "flowchart"],
            "compose_tone": "数据化", "max_paragraph_lines": 2, "target_age": "12-18",
        })

    sent_prompt = mock_llm.await_args.args[0]
    assert "datapanel" in sent_prompt  # 优先级组件出现在 prompt 里
    assert "风格约束" in sent_prompt


@pytest.mark.asyncio
async def test_design_skill_empty_priority_no_injection(sample_material):
    """无 design_priority → 不注入约束（prompt 保持原样）。"""
    mock_response = json.dumps({"components": ["timeline"], "rationale": "R",
                                "structure": "S", "visual_hint": "V"}, ensure_ascii=False)

    with patch("app.tools.design.chat_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = mock_response
        await tool_design(sample_material, "主题", skill_config={"compose_tone": "叙事感"})

    sent_prompt = mock_llm.await_args.args[0]
    assert "风格约束" not in sent_prompt


@pytest.mark.asyncio
async def test_compose_skill_tone_injected(sample_material):
    """skill_config.compose_tone 注入 compose prompt——Skill 影响文案语气。"""
    mock_response = json.dumps({"title": "T", "subtitle": "S", "blocks": [], "fact_notes": ""},
                               ensure_ascii=False)

    with patch("app.tools.design.chat_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = mock_response
        await tool_compose(sample_material, {"components": ["timeline"]}, "主题",
                           skill_config={"compose_tone": "数据化", "max_paragraph_lines": 2,
                                         "target_age": "12-18"})

    sent_prompt = mock_llm.await_args.args[0]
    assert "数据化" in sent_prompt
    assert "每段不超过 2 行" in sent_prompt
    assert "12-18" in sent_prompt
