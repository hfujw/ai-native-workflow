"""MessageBus 链路测试——防止"Designer 求助 Researcher"这条三 Agent 链路静默退化。"""

import pytest

from app.agent.message_bus import MessageBus


@pytest.mark.asyncio
async def test_bus_register_send_recv():
    bus = MessageBus()
    bus.register("a")
    bus.register("b")
    await bus.send("b", {"type": "ping"})
    assert await bus.recv("b", timeout=1.0) == {"type": "ping"}


@pytest.mark.asyncio
async def test_bus_recv_timeout_returns_none():
    bus = MessageBus()
    bus.register("a")
    assert await bus.recv("a", timeout=0.05) is None


@pytest.mark.asyncio
async def test_bus_send_unregistered_dropped():
    bus = MessageBus()
    await bus.send("nobody", {"type": "x"})  # 不应抛异常，静默丢弃


@pytest.mark.asyncio
async def test_researcher_listen_serves_search_request():
    """完整求助链路：designer 注册 → researcher.listen 收到请求 → 回传结果。"""
    from app.tools.search import ResearcherAgent

    bus = MessageBus()
    bus.register("designer")
    bus.register("researcher")  # 真实流程里 DesignerAgent 会先注册求助目标

    # mock ResearcherAgent.run，避免真实搜索
    async def fake_run(topic, existing_material=None, session_records=None, push=None, model=None):
        assert topic == "求助主题"
        return {"results": [{"title": "素材A"}], "count": 1, "level": "medium"}

    import asyncio

    agent = ResearcherAgent()
    agent.run = fake_run
    listener = asyncio.create_task(agent.listen(bus))
    await bus.send("researcher", {
        "type": "search_request",
        "topic": "求助主题",
        "existing_material": [],
        "session_records": None,
        "reply_to": "designer",
    })
    reply = await bus.recv("designer", timeout=2.0)
    listener.cancel()
    try:
        await listener
    except (asyncio.CancelledError, Exception):
        pass

    assert reply is not None
    assert reply["type"] == "search_result"
    assert reply["results"][0]["title"] == "素材A"
