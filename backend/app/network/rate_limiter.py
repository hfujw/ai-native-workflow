"""速率限制器 — IP 级免费试用 + 全站日预算硬帽。

通过 StateBackend 存储状态（当前 MemoryBackend，改 STATE_BACKEND=redis 即可切换）。
"""

import asyncio
import logging
from datetime import date

from app.state import state

logger = logging.getLogger(__name__)

DAILY_BUDGET = 5.0
TRIALS_PER_IP = 1
LOCALHOST_IPS = {"127.0.0.1", "::1", "localhost"}


class RateLimiter:
    """IP 限流 + 日预算帽——状态通过 StateBackend 持久化。"""

    def __init__(self):
        self._lock = asyncio.Lock()  # 保护 can_generate 的原子性

    # ── 查询 ──

    async def daily_budget_remaining(self) -> float:
        spent = await state.get("rate:daily_spent")
        return max(0.0, DAILY_BUDGET - float(spent or 0))

    async def trials_used(self, ip: str) -> int:
        today = str(date.today())
        return int(await state.get(f"rate:{ip}:{today}") or 0)

    async def stats(self) -> dict:
        """当前限流状态快照——从 StateBackend 读真实值（P2-7 修复假数据）。"""
        spent = float(await state.get("rate:daily_spent") or 0)
        return {"daily_budget": DAILY_BUDGET, "daily_spent": round(spent, 4), "trials_per_ip": TRIALS_PER_IP}

    # ── 准入 ──

    async def can_generate(self, ip: str) -> tuple[bool, str]:
        if ip in LOCALHOST_IPS:
            return True, ""

        # P2-8: 状态后端不可用（Redis 宕机）→ fail-closed，防限流静默失效烧预算
        if getattr(state, "available", True) is False:
            logger.error("状态后端不可用，拒绝放行（fail-closed）")
            return False, "服务状态存储不可用，请稍后再试"

        async with self._lock:
            spent = float(await state.get("rate:daily_spent") or 0)
            if spent >= DAILY_BUDGET:
                return False, "今日全站免费额度已用完，明天再来吧 🎨"

            today = str(date.today())
            trial_count = int(await state.get(f"rate:{ip}:{today}") or 0)
            if trial_count >= TRIALS_PER_IP:
                return False, "您今日的免费试用次数已用完，明天可以再来"

        return True, ""

    # ── 记录 ──

    async def record_success(self, ip: str):
        if ip in LOCALHOST_IPS:
            return
        today = str(date.today())
        count = await state.incr(f"rate:{ip}:{today}")
        await state.expire(f"rate:{ip}:{today}", 86400)
        await state.incr("rate:total_generations")
        logger.info("IP %s 试用成功 %d/%d", ip, count, TRIALS_PER_IP)

    async def record_cost(self, amount: float):
        # P2-6: get-then-set 加锁，防并发生成丢花费记录
        async with self._lock:
            spent = float(await state.get("rate:daily_spent") or 0)
            new_spent = spent + amount
            await state.set("rate:daily_spent", str(new_spent), ttl=86400)
        logger.info("花费 ¥%.4f | 累计 ¥%.4f / ¥%.0f（剩余 ¥%.2f）",
                    amount, new_spent, DAILY_BUDGET, max(0.0, DAILY_BUDGET - new_spent))


rate_limiter = RateLimiter()
