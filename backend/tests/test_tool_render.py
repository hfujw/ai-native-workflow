"""测试 tool_render——用 mock LLM 响应。"""
from unittest.mock import AsyncMock, patch

import pytest

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


# ── 方向 B：交互基因（DOM 提示 + 后端注入脚本，不靠 LLM 写脚本）──

@pytest.mark.asyncio
async def test_render_interaction_dom_hint_in_prompt(design, content):
    """skill_assets 带 _interaction=count-up → prompt 出现交互 DOM 提示（不出现脚本本身）。"""
    html = "<!DOCTYPE html>\n<html><body><h1>标题</h1></body></html>"
    with patch("app.tools.render.chat", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = html
        await tool_render(design, content, skill_assets={
            "interactions.js": "var x = 1;",
            "_interaction": "count-up",
        })
    sent_prompt = mock_llm.await_args.args[0]
    assert "交互增强" in sent_prompt
    assert "count-up" in sent_prompt          # DOM 类名提示给 LLM
    assert "var x = 1;" not in sent_prompt    # 脚本本身不塞进 prompt（避免 LLM 耗 token）


@pytest.mark.asyncio
async def test_render_injects_script_into_output(design, content):
    """render 完成后，interactions.js 自动注入到 </body> 前（后端注入，不靠 LLM）。"""
    html = "<!DOCTYPE html>\n<html><body><h1>标题</h1></body></html>"
    with patch("app.tools.render.chat", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = html
        result = await tool_render(design, content, skill_assets={
            "interactions.js": "// progress bar",
            "_interaction": "reading-progress",
        })
    assert "// progress bar" in result["html"]
    assert "<script>" in result["html"]
    assert result["html"].index("<script>") < result["html"].index("</body>")


@pytest.mark.asyncio
async def test_render_no_interaction_no_injection(design, content):
    """无 interactions.js → 产物不注入脚本、prompt 无交互提示（像素风等）。"""
    html = "<!DOCTYPE html>\n<html><body><h1>标题</h1></body></html>"
    with patch("app.tools.render.chat", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = html
        result = await tool_render(design, content, skill_assets={"template.html": "<div/>"})
    sent_prompt = mock_llm.await_args.args[0]
    assert "交互增强" not in sent_prompt
    assert "<script>" not in result["html"]
