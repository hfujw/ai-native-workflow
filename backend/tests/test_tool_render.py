"""测试 tool_render——用 mock LLM 响应。"""
import pytest
from unittest.mock import patch, AsyncMock
from app.tools.render import tool_render


@pytest.fixture
def design():
    return {"components": ["cards"], "rationale": "测试", "structure": "单列", "visual_hint": "默认"}


@pytest.fixture
def content():
    return {"title": "测试", "subtitle": "", "blocks": []}


@pytest.mark.asyncio
async def test_normal_render(design, content):
    html = "<!DOCTYPE html>\n<html><head></head><body><h1>Hello</h1><script>console.log(1)</script></body></html>"

    with patch("app.tools.render.chat", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = html
        result = await tool_render(design, content)

    assert result["complete"] is True
    assert "</html>" in result["html"]
    assert len(result["html"]) > 0


@pytest.mark.asyncio
async def test_render_strips_fence(design, content):
    html = '```html\n<!DOCTYPE html>\n<html><body>test<script>x()</script></body></html>\n```'

    with patch("app.tools.render.chat", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = html
        result = await tool_render(design, content)

    assert "```" not in result["html"]
    assert "<!DOCTYPE html>" in result["html"]


@pytest.mark.asyncio
async def test_render_adds_doctype(design, content):
    html = "<html><body>no doctype<script>x()</script></body></html>"

    with patch("app.tools.render.chat", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = html
        result = await tool_render(design, content)

    assert result["html"].lstrip().lower().startswith("<!doctype")


@pytest.mark.asyncio
async def test_render_incomplete(design, content):
    html = "<!DOCTYPE html>\n<html><body>truncated"  # 缺 </html>

    with patch("app.tools.render.chat", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = html
        result = await tool_render(design, content)

    assert result["complete"] is False


@pytest.mark.asyncio
async def test_render_llm_error(design, content):
    with patch("app.tools.render.chat", new_callable=AsyncMock) as mock_llm:
        mock_llm.side_effect = TimeoutError("DeepSeek 超时")
        result = await tool_render(design, content)

    assert result["complete"] is True  # 降级 HTML 也是完整结构
    assert "生成失败" in result["html"]
