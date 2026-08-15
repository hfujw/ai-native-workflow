"""H2 修复测试：deepseek-reasoner 不传 response_format（json_object 兼容）。

覆盖：
- H2-1 reasoner 模型 → chat_json 不传 response_format
- H2-2 普通模型 → 仍传 json_object
- H2-3 参数错误（400）不计数熔断（断路器豁免）
- H2-4 认证错误（401）仍不熔断（回归）
"""
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_chat_json_skips_response_format_for_reasoner():
    """reasoner → 不传 response_format（会被 API 拒）。"""
    from app.llm import client as client_mod

    captured = {}

    async def fake_chat(prompt, system="", model=None, temperature=0.7,
                        session_records=None, response_format=None, **kw):
        captured["response_format"] = response_format
        return '{"tool": "design"}'

    with patch.object(client_mod, "chat", new=fake_chat):
        out = await client_mod.chat_json("测试", model="deepseek-reasoner")
    assert out == '{"tool": "design"}'
    assert captured["response_format"] is None  # reasoner 不传


@pytest.mark.asyncio
async def test_chat_json_skips_response_format_for_v4_pro():
    """官方新命名 deepseek-v4-pro（推理模型）→ 同样不传 response_format。"""
    from app.llm import client as client_mod

    captured = {}

    async def fake_chat(prompt, system="", model=None, temperature=0.7,
                        session_records=None, response_format=None, **kw):
        captured["response_format"] = response_format
        return '{"tool": "design"}'

    with patch.object(client_mod, "chat", new=fake_chat):
        out = await client_mod.chat_json("测试", model="deepseek-v4-pro")
    assert captured["response_format"] is None


@pytest.mark.asyncio
async def test_chat_json_keeps_response_format_for_chat():
    """普通模型 → 仍传 json_object。"""
    from app.llm import client as client_mod

    captured = {}

    async def fake_chat(prompt, system="", model=None, temperature=0.7,
                        session_records=None, response_format=None, **kw):
        captured["response_format"] = response_format
        return '{"tool": "design"}'

    with patch.object(client_mod, "chat", new=fake_chat):
        await client_mod.chat_json("测试", model="deepseek-chat")
    assert captured["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_param_error_does_not_open_circuit():
    """400 参数错误 → 断路器不计数不熔断。"""
    from app.llm.circuit_breaker import CircuitBreaker, State

    class _BadRequest(Exception):
        status_code = 400

    breaker = CircuitBreaker(failure_threshold=2)
    async def boom():
        raise _BadRequest("bad param")

    for _ in range(5):  # 连续 5 次参数错误
        with pytest.raises(_BadRequest):
            await breaker.call(boom())

    assert breaker.state == State.CLOSED  # 参数错误不熔断
    assert breaker.failure_count == 0


@pytest.mark.asyncio
async def test_server_error_still_opens_circuit():
    """5xx 服务错误 → 仍正常熔断（回归）。"""
    from app.llm.circuit_breaker import CircuitBreaker, CircuitOpenError, State

    class _ServerError(Exception):
        status_code = 500

    breaker = CircuitBreaker(failure_threshold=2)
    async def boom():
        raise _ServerError("server down")

    # 前两次失败 → 达到阈值熔断
    with pytest.raises(_ServerError):
        await breaker.call(boom())
    with pytest.raises(_ServerError):
        await breaker.call(boom())
    assert breaker.state == State.OPEN
    # 熔断后拒绝请求 → CircuitOpenError
    with pytest.raises(CircuitOpenError):
        await breaker.call(boom())
