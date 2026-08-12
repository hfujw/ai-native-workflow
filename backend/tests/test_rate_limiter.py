"""测试 RateLimiter — IP 限流 + 日预算帽。"""
import pytest

from app.network.rate_limiter import RateLimiter


@pytest.fixture
def limiter():
    return RateLimiter()


@pytest.mark.asyncio
async def test_first_request_allowed(limiter):
    allowed, _ = await limiter.can_generate("1.2.3.4")
    assert allowed


@pytest.mark.asyncio
async def test_localhost_unlimited(limiter):
    for _ in range(100):
        allowed, _ = await limiter.can_generate("127.0.0.1")
        assert allowed


@pytest.mark.asyncio
async def test_exceeds_trial_limit(limiter):
    # can_generate 原子预留名额——第二次应拒绝（防并发绕过）
    allowed, _ = await limiter.can_generate("5.6.7.8")
    assert allowed
    allowed, reason = await limiter.can_generate("5.6.7.8")
    assert not allowed
    assert "用完" in reason


@pytest.mark.asyncio
async def test_release_trial(limiter):
    # 生成失败释放名额后可以重试
    allowed, _ = await limiter.can_generate("5.6.7.8")
    assert allowed
    await limiter.release_trial("5.6.7.8")
    allowed, _ = await limiter.can_generate("5.6.7.8")
    assert allowed


@pytest.mark.asyncio
async def test_daily_budget_cap(limiter):
    # 模拟花费已超预算
    await limiter.record_cost(5.0)
    allowed, reason = await limiter.can_generate("9.9.9.9")
    assert not allowed
    assert "额度已用完" in reason


@pytest.mark.asyncio
async def test_cost_tracking(limiter):
    # 用 stats() 读花费——不依赖内部 key 名（P2 已改为 date-keyed）
    await limiter.record_cost(0.10)
    await limiter.record_cost(0.15)
    stats = await limiter.stats()
    assert stats["daily_spent"] == 0.25


@pytest.mark.asyncio
async def test_daily_budget_resets_by_date():
    """日预算 key 带日期——新的一天自然归零（不依赖滑动 TTL）。"""
    from app.network.rate_limiter import RateLimiter

    limiter = RateLimiter()
    await limiter.record_cost(4.0)
    # 模拟"第二天"：直接写一个旧日期 key 不影响今天的额度
    from app.state import state
    await state.set(f"rate:daily_spent:2020-01-01", "4.9", ttl=86400)
    allowed, _ = await limiter.can_generate("1.1.1.1")
    assert allowed  # 旧日期的高花费不影响今天
