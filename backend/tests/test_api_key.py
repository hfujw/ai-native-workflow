"""批次 D：会话级 API Key/Base 绑定（contextvars）——用户自定义 LLM 接入生效。

覆盖：
- D-1 bind 后 _get_client() 使用自定义 base_url
- D-2 未绑定回落默认客户端
- D-3 绑定只影响当前任务（contextvars 隔离）
- D-4 clear 后回落默认
- D-5 chat() 实际使用会话客户端（mock create）
"""
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def _clear_session():
    from app.llm.client import clear_session_client
    clear_session_client()
    yield
    clear_session_client()


# ═══════════════════════════════════════════════════════════════
# D-1：bind 后使用自定义配置
# ═══════════════════════════════════════════════════════════════

def test_bind_session_client_uses_custom_base():
    from app.llm.client import bind_session_client, _get_client

    bind_session_client("sk-test-123", "https://custom.example.com/v1")
    c = _get_client()
    assert c.api_key == "sk-test-123"
    assert str(c.base_url).rstrip("/") == "https://custom.example.com/v1"


def test_bind_partial_falls_back_to_env():
    """只给 key 不给 base → base 回落默认。"""
    from app.llm.client import bind_session_client, _get_client, DEFAULT_MODEL

    bind_session_client("sk-test-123", None)
    c = _get_client()
    assert c.api_key == "sk-test-123"
    # 默认 base 来自环境变量 DEEPSEEK_BASE_URL 或官方地址
    import os
    assert c.base_url == os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    assert DEFAULT_MODEL


# ═══════════════════════════════════════════════════════════════
# D-2：未绑定回落默认
# ═══════════════════════════════════════════════════════════════

def test_unbound_uses_default_client():
    from app.llm.client import _get_client, _default_client

    assert _get_client() is _default_client


# ═══════════════════════════════════════════════════════════════
# D-3：contextvars 隔离——绑定只影响当前任务
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_binding_isolated_between_tasks():
    """一个任务绑定后，另一个任务仍用默认客户端。"""
    import asyncio
    from app.llm.client import bind_session_client, _get_client, _default_client

    async def bound_task():
        bind_session_client("sk-task-a", "https://a.example.com")
        await asyncio.sleep(0.05)
        return _get_client()

    async def plain_task():
        await asyncio.sleep(0.05)
        return _get_client()

    bound_client = await asyncio.create_task(bound_task())
    plain_client = await asyncio.create_task(plain_task())
    assert bound_client.api_key == "sk-task-a"
    assert plain_client is _default_client


# ═══════════════════════════════════════════════════════════════
# D-4：clear 回落默认
# ═══════════════════════════════════════════════════════════════

def test_clear_session_client():
    from app.llm.client import bind_session_client, clear_session_client, _get_client, _default_client

    bind_session_client("sk-x", "https://x.example.com")
    assert _get_client() is not _default_client
    clear_session_client()
    assert _get_client() is _default_client


# ═══════════════════════════════════════════════════════════════
# D-5：chat() 走会话客户端
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_chat_uses_session_client():
    """绑定后 chat() 的 create 调用必须落在会话客户端上。"""
    from app.llm import client as client_mod
    from app.llm.client import bind_session_client

    fake_response = AsyncMock()
    fake_response.choices = [AsyncMock()]
    fake_response.choices[0].message.content = "你好"
    fake_response.usage = None

    fake_client = AsyncMock()
    fake_client.chat.completions.create = AsyncMock(return_value=fake_response)

    bind_session_client("sk-session", "https://session.example.com")
    with patch.object(client_mod, "_get_client", return_value=fake_client):
        out = await client_mod.chat("恐龙是什么", session_records=[])
    assert out == "你好"
    # create 确实被调用（参数里有 model/messages）
    assert fake_client.chat.completions.create.await_count == 1
