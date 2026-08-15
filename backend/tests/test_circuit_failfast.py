"""熔断快速失败测试——AI 服务故障时不循环重试刷屏。

覆盖：
- CB-1 chat() 熔断中不重试（一次调用直接抛 CircuitOpenError）
- CB-2 orchestrator 循环检测到熔断 → 立即失败（不跑满 20 步）
- CB-3 工具层（design）熔断中不降级
"""
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_chat_does_not_retry_when_circuit_open():
    """断路器 OPEN 时 chat() 直接抛错，不再重试 3 次。"""
    from app.llm import client as client_mod
    from app.llm.circuit_breaker import CircuitOpenError, State
    from app.llm.client import bind_session_client, clear_session_client

    bind_session_client("sk-test", None)

    class _OpenBreaker:
        async def call(self, coro):
            raise CircuitOpenError()

    with patch("app.llm.circuit_breaker.llm_breaker", _OpenBreaker()):
        with pytest.raises(CircuitOpenError):
            await client_mod.chat("你好", session_records=[])
    clear_session_client()


@pytest.mark.asyncio
async def test_orchestrator_fails_fast_when_circuit_open():
    """orchestrator 循环检测到熔断 → 直接 failed（reason=AI 服务不可用）。"""
    from app.agent.orchestrator import orchestrator_node
    from app.llm.circuit_breaker import State, llm_breaker

    # 伪造断路器为 OPEN（保存原状态，测完恢复）
    orig_state = llm_breaker.state
    orig_failure = llm_breaker.failure_count
    llm_breaker.state = State.OPEN
    llm_breaker.failure_count = 99
    try:
        result = await orchestrator_node({
            "session_id": "cb-test", "user_input": "恐龙",
            "_push": None, "_cost_records": [], "_preferences": {},
            "_params": None, "_model": "deepseek-chat",
        })
    finally:
        llm_breaker.state = orig_state
        llm_breaker.failure_count = orig_failure

    assert result["status"] == "failed"
    assert "AI 服务暂时不可用" in result.get("reason", "")
    assert result["steps"] == 0  # 一轮都没跑，直接失败


@pytest.mark.asyncio
async def test_design_does_not_degrade_when_circuit_open():
    """熔断中 design 不降级百科——直接上抛。"""
    from app.tools.design import tool_design
    from app.llm.circuit_breaker import CircuitOpenError

    async def boom(prompt, system="", model=None, session_records=None, **kw):
        raise CircuitOpenError()

    # design.py 在模块顶层 from app.llm.client import chat_json → patch design 命名空间
    with patch("app.tools.design.chat_json", new=boom):
        with pytest.raises(CircuitOpenError):
            await tool_design([{"title": "恐龙", "snippet": "内容"}], "恐龙", [])
