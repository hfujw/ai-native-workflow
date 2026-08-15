"""测试 RenderAgent——自检、缓存、空内容短路。"""
import pytest

from app.tools.render import RenderAgent


@pytest.fixture
def agent():
    return RenderAgent()


@pytest.fixture
def design():
    return {"components": ["cards"], "rationale": "测试", "structure": "单列", "visual_hint": "默认"}


@pytest.fixture
def content():
    return {"title": "测试", "subtitle": "", "blocks": []}


def _valid_html():
    return "<!DOCTYPE html>\n<html><head><meta charset='UTF-8'><title>Test</title></head><body><h1>Hello World</h1><p>" + "Lorem ipsum dolor sit amet " * 10 + "</p><script>console.log(1)</script></body></html>"


def test_self_check_passes_for_valid_html(agent):
    issues = agent._self_check(_valid_html())
    assert len(issues) == 0


def test_self_check_detects_missing_html_tag(agent):
    html = "<body><h1>No html tag</h1></body>" + "x" * 200
    issues = agent._self_check(html)
    assert any("missing_html" in i for i in issues)


def test_self_check_detects_missing_body_tag(agent):
    html = "<!DOCTYPE html>\n<html><head></head><h1>No body</h1></html>" + "y" * 200
    issues = agent._self_check(html)
    assert any("missing_body" in i for i in issues)


def test_self_check_detects_placeholder(agent):
    html = _valid_html().replace("Hello World", "{{content}}")
    issues = agent._self_check(html)
    assert "placeholder_left" in issues


def test_self_check_detects_too_short(agent):
    issues = agent._self_check("short")
    assert "content_too_short" in issues


def test_cache_key_excludes_dynamic_fields(agent, design, content):
    key1 = agent._cache_key(design, content)
    design_with_ts = {**design, "generated_at": "2026-08-08T00:00:00", "_session_id": "abc123"}
    key2 = agent._cache_key(design_with_ts, content)
    assert key1 == key2


def test_cache_set_and_get(agent, design, content):
    key = "test_key_123"
    agent._cache_set(key, "<html>test</html>")
    cached = agent._cache_get(key)
    assert cached == "<html>test</html>"


def test_patch_hint_adds_fix_guidance(agent, design):
    issues = ["missing_</html>", "placeholder_left"]
    patched = agent._patch_hint(design, issues)
    assert "visual_hint" in patched
    assert "截断" in patched["visual_hint"]
    assert "占位符" in patched["visual_hint"]
