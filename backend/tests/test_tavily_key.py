"""搜索凭证（Tavily）会话级绑定测试——与 LLM 凭证独立管理。

覆盖：
- T-1 bind 后 _effective_tavily_key 用会话 key
- T-2 未绑定回落 .env 配置
- T-3 绑定只影响当前任务（contextvars 隔离）
- T-4 _search_tavily 实际使用会话 key（mock httpx 验证请求体）
"""
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def _clear():
    from app.tools.search import _tavily_key_ctx
    _tavily_key_ctx.set(None)
    yield
    _tavily_key_ctx.set(None)


def test_bind_uses_session_key():
    from app.tools.search import _effective_tavily_key, bind_tavily_key

    bind_tavily_key("tvly-session-123")
    assert _effective_tavily_key() == "tvly-session-123"


def test_unbound_falls_back_to_env(monkeypatch):
    from app.tools.search import _effective_tavily_key

    from app.config import settings
    monkeypatch.setattr(settings, "tavily_api_key", "tvly-env-456")
    assert _effective_tavily_key() == "tvly-env-456"


def test_bind_ignores_blank():
    from app.tools.search import _effective_tavily_key, bind_tavily_key

    bind_tavily_key("   ")
    from app.config import settings
    assert _effective_tavily_key() == settings.tavily_api_key.strip()


@pytest.mark.asyncio
async def test_binding_isolated_between_tasks():
    """一个任务绑定后，另一个任务仍用默认。"""
    import asyncio
    from app.tools.search import _effective_tavily_key, bind_tavily_key

    async def bound():
        bind_tavily_key("tvly-a")
        await asyncio.sleep(0.05)
        return _effective_tavily_key()

    async def plain():
        await asyncio.sleep(0.05)
        return _effective_tavily_key()

    assert await asyncio.create_task(bound()) == "tvly-a"
    from app.config import settings
    assert await asyncio.create_task(plain()) == settings.tavily_api_key.strip()


@pytest.mark.asyncio
async def test_search_tavily_uses_session_key():
    """_search_tavily 请求体带会话 key（独立于 LLM 凭证）。"""
    from app.tools.search import _search_tavily, bind_tavily_key

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

    bind_tavily_key("tvly-session-999")
    with patch("app.tools.search.httpx.AsyncClient", FakeClient):
        results = await _search_tavily("恐龙")

    assert len(results) == 1
    assert captured["json"]["api_key"] == "tvly-session-999"
    assert captured["url"] == "https://api.tavily.com/search"
