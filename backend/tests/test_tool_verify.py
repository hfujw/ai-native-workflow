"""测试 tool_verify——纯规则测试，不需要 mock。"""
import pytest

from app.tools.verify import tool_verify


@pytest.fixture
def valid_html():
    return "<!DOCTYPE html>\n<html><head></head><body><h1>Test</h1><script>console.log(1)</script></body></html>"


@pytest.fixture
def content():
    return {"title": "测试", "subtitle": "", "blocks": [
        {"component": "cards", "position": 1, "html_hint": "卡片", "claims": [
            {"text": "事实A", "source": "search_1", "confidence": "high"},
            {"text": "事实B", "source": "llm_internal", "confidence": "medium"},
        ]}
    ]}


@pytest.mark.asyncio
async def test_verify_passes(valid_html, content):
    result = await tool_verify(valid_html, content)
    assert result["passed"] is True


@pytest.mark.asyncio
async def test_verify_missing_html_close():
    result = await tool_verify("<html><body>no close", {})
    assert result["passed"] is False
    assert any(i["category"] == "incomplete" for i in result["issues"])


@pytest.mark.asyncio
async def test_verify_no_script(valid_html):
    html = valid_html.replace("<script>console.log(1)</script>", "")
    result = await tool_verify(html, {})
    assert any(i["category"] == "no_js" for i in result["issues"])


@pytest.mark.asyncio
async def test_verify_placeholder():
    html = "<html><body>{{content}}</body></html>"
    result = await tool_verify(html, {})
    assert any(i["category"] == "placeholder" for i in result["issues"])


@pytest.mark.asyncio
async def test_verify_low_source_coverage():
    content = {"blocks": [{"component": "cards", "position": 1, "claims": [
        {"text": "无来源", "source": "", "confidence": "unknown"},
        {"text": "也无来源", "source": "", "confidence": "unknown"},
    ]}]}
    result = await tool_verify("<html><body><script>x()</script></body></html>", content)
    assert any(i["category"] == "fact_check" for i in result["issues"])


@pytest.mark.asyncio
async def test_verify_rollback_target():
    result = await tool_verify("<html><body>incomplete", {})
    assert result["rollback_target"] == "render"


@pytest.mark.asyncio
async def test_verify_passed_with_warning(valid_html):
    """有 warning 但不影响通过——比如缺 script。"""
    html = valid_html.replace("<script>console.log(1)</script>", "")
    result = await tool_verify(html, {})
    # 缺 script 只是 warning，不阻断通过
    has_critical = any(i["severity"] == "critical" for i in result["issues"])
    assert not has_critical  # 只缺 script → 不该产生 critical 问题
    assert result["passed"] is True  # 无 critical → 审查必须通过
