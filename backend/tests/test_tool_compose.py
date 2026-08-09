"""测试 tool_compose——用 mock LLM 响应。"""
import json, pytest
from unittest.mock import patch, AsyncMock
from app.tools.compose import tool_compose


@pytest.fixture
def sample_material():
    return [{"title": "秦始皇统一", "snippet": "前221年", "content": ""}]


@pytest.fixture
def sample_design():
    return {"components": ["timeline", "cards"], "rationale": "测试", "structure": "顶时间轴", "visual_hint": "默认"}


@pytest.mark.asyncio
async def test_normal_compose(sample_material, sample_design):
    mock_response = json.dumps({"title": "秦始皇与长城", "subtitle": "大一统", "blocks": [
        {"component": "timeline", "position": 1, "html_hint": "时间轴", "claims": [
            {"text": "前221年统一", "source": "search_1", "confidence": "high"}
        ]}
    ], "fact_notes": "确定"}, ensure_ascii=False)

    with patch("app.tools.compose.chat_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = mock_response
        result = await tool_compose(sample_material, sample_design, "秦始皇")

    assert result["tool"] == "compose"
    assert result["title"] == "秦始皇与长城"
    assert len(result["blocks"]) == 1


@pytest.mark.asyncio
async def test_compose_with_fence(sample_material, sample_design):
    mock_response = '```json\n{"title": "测试", "subtitle": "", "blocks": [], "fact_notes": ""}\n```'

    with patch("app.tools.compose.chat_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = mock_response
        result = await tool_compose(sample_material, sample_design, "测试")

    assert result["title"] == "测试"


@pytest.mark.asyncio
async def test_compose_invalid_json(sample_material, sample_design):
    with patch("app.tools.compose.chat_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = "invalid json {{{"
        result = await tool_compose(sample_material, sample_design, "测试")

    assert result["title"] == "生成失败"


@pytest.mark.asyncio
async def test_compose_llm_error(sample_material, sample_design):
    with patch("app.tools.compose.chat_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.side_effect = TimeoutError("DeepSeek 超时")
        result = await tool_compose(sample_material, sample_design, "测试")

    assert result["title"] == "生成失败"
