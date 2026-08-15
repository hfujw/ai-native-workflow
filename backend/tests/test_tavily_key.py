"""搜索服务会话级绑定测试——和模型选择一样：用户选服务 + 独立 Key/地址。

覆盖：
- S-1 bind 后 _search_service 返回绑定配置
- S-2 未绑定 / 空 Key → None（不联网，不回落任何配置）
- S-3 绑定只影响当前任务（contextvars 隔离）
- S-4 搜索请求用会话服务的 Key + 端点（mock httpx 验证请求体）
- S-5 自定义端点生效
"""
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _clear():
    from app.tools.search import _search_svc_ctx
    _search_svc_ctx.set(None)
    yield
    _search_svc_ctx.set(None)


def test_bind_returns_service():
    from app.tools.search import _search_service, bind_search_service

    bind_search_service({"name": "Tavily", "api_key": "tvly-123", "base_url": "https://api.tavily.com"})
    svc = _search_service()
    assert svc["api_key"] == "tvly-123"
    assert svc["name"] == "Tavily"


def test_bind_fills_default_endpoint():
    """自定义服务没填端点 → 默认 Tavily 端点。"""
    from app.tools.search import _search_service, bind_search_service

    bind_search_service({"name": "我的搜索", "api_key": "k"})
    assert _search_service()["base_url"] == "https://api.tavily.com"


def test_unbound_is_none():
    from app.tools.search import _search_service

    assert _search_service() is None


def test_blank_key_means_not_configured():
    """空白 Key = 未配置（没填就是没填，不回落 .env）。"""
    from app.tools.search import _search_service, bind_search_service

    bind_search_service({"name": "Tavily", "api_key": "   ", "base_url": "https://x"})
    assert _search_service() is None


@pytest.mark.asyncio
async def test_binding_isolated_between_tasks():
    """一个任务绑定后，另一个任务仍为 None。"""
    import asyncio
    from app.tools.search import _search_service, bind_search_service

    async def bound():
        bind_search_service({"name": "A", "api_key": "k-a"})
        await asyncio.sleep(0.05)
        return _search_service()

    async def plain():
        await asyncio.sleep(0.05)
        return _search_service()

    assert (await asyncio.create_task(bound()))["api_key"] == "k-a"
    assert await asyncio.create_task(plain()) is None


@pytest.mark.asyncio
async def test_search_uses_session_service_key_and_endpoint():
    """请求体带会话服务的 Key，发往会话服务的端点。"""
    from app.tools.search import _search_tavily, bind_search_service

    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"results": [{"title": "恐龙", "url": "https://x", "content": "内容"}]}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def post(self, url, json=None):
            captured["url"] = url
            captured["json"] = json
            return FakeResp()

    bind_search_service({"name": "我的网关", "api_key": "tvly-999", "base_url": "https://my-search.example.com"})
    with patch("app.tools.search.httpx.AsyncClient", FakeClient):
        results = await _search_tavily("恐龙")

    assert len(results) == 1
    assert captured["json"]["api_key"] == "tvly-999"
    assert captured["url"] == "https://my-search.example.com/search"


@pytest.mark.asyncio
async def test_search_without_service_returns_empty():
    """没配置搜索服务 → 不联网（返回空，不请求任何端点）。"""
    from app.tools.search import _search_tavily

    async def boom(*a, **k):
        raise AssertionError("未配置服务不应发起请求")

    with patch("app.tools.search.httpx.AsyncClient", boom):
        assert await _search_tavily("恐龙") == []
