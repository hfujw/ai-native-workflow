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
    # 模拟成功一次
    await limiter.record_success("5.6.7.8")
    allowed, reason = await limiter.can_generate("5.6.7.8")
    assert not allowed
    assert "用完" in reason


@pytest.mark.asyncio
async def test_daily_budget_cap(limiter):
    # 模拟花费已超预算
    await limiter.record_cost(5.0)
    allowed, reason = await limiter.can_generate("9.9.9.9")
    assert not allowed
    assert "额度已用完" in reason


@pytest.mark.asyncio
async def test_cost_tracking(limiter):
    from app.state import state
    await limiter.record_cost(0.10)
    await limiter.record_cost(0.15)
    spent = float(await state.get("rate:daily_spent") or 0)
    assert spent == 0.25
