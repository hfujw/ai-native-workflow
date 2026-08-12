"""速率限制器 — IP 级免费试用 + 全站日预算硬帽。

通过 StateBackend 存储状态（当前 MemoryBackend，改 STATE_BACKEND=redis 即可切换）。

设计要点（2026-08-12 对抗性审查修复后）：
- 预算/试用次数读 config（.env 可覆盖）。
- 日预算 key 带日期 `rate:daily_spent:{today}`——按日历日重置。
- 试用名额**原子预留**：can_generate 时 `state.incr` 占用名额（防并发绕过 1 次/IP），
  生成失败用 `release_trial` 释放——语义是"每天成功 1 次"。
- 日预算仍是软帽：cost 在生成后记录，无法事先知道，并发下可能轻微超出（见 FULL_TRACE 遗留）。
"""

import asyncio
import logging
from datetime import date

from app.core.config import settings
from app.state import state

logger = logging.getLogger(__name__)

LOCALHOST_IPS = {"127.0.0.1", "::1", "localhost"}


class RateLimiter:
    """IP 限流 + 日预算帽——状态通过 StateBackend 持久化。"""

    def __init__(self):
        # 只保护 record_cost 的 get-then-set（预算写入）；试用名额走 state.incr 天然原子
        self._lock = asyncio.Lock()

    @staticmethod
    def _daily_spent_key(today: str | None = None) -> str:
        """日预算 key 带日期——新的一天自然生成新 key，旧 key TTL 到期自动清理。"""
        return f"rate:daily_spent:{today or str(date.today())}"

    # ── 查询 ──

    async def daily_budget_remaining(self) -> float:
        spent = await state.get(self._daily_spent_key())
        return max(0.0, settings.daily_budget - float(spent or 0))

    async def trials_used(self, ip: str) -> int:
        today = str(date.today())
        return int(await state.get(f"rate:{ip}:{today}") or 0)

    async def stats(self) -> dict:
        """当前限流状态快照——从 StateBackend 读真实值。"""
        spent = float(await state.get(self._daily_spent_key()) or 0)
        return {
            "daily_budget": settings.daily_budget,
            "daily_spent": round(spent, 4),
            "trials_per_ip": settings.trials_per_ip,
        }

    # ── 准入 ──

    async def can_generate(self, ip: str) -> tuple[bool, str]:
        if ip in LOCALHOST_IPS:
            return True, ""

        # 状态后端不可用（Redis 宕机）→ fail-closed，防限流静默失效烧预算
        if getattr(state, "available", True) is False:
            logger.error("状态后端不可用，拒绝放行（fail-closed）")
            return False, "服务状态存储不可用，请稍后再试"

        today = str(date.today())

        # 日预算：软帽（记录在生成后，可能轻微超出——见模块 docstring）
        spent = float(await state.get(self._daily_spent_key(today)) or 0)
        if spent >= settings.daily_budget:
            return False, "今日全站免费额度已用完，明天再来吧 🎨"

        # 试用名额：原子预留（state.incr 原子）——防并发绕过 1 次/IP
        count = await state.incr(f"rate:{ip}:{today}")
        await state.expire(f"rate:{ip}:{today}", 86400)
        if count > settings.trials_per_ip:
            await state.incr(f"rate:{ip}:{today}", -1)  # 超限——释放这次占用
            return False, "您今日的免费试用次数已用完，明天可以再来"

        return True, ""

    # ── 记录 ──

    async def record_success(self, ip: str):
        # 名额已在 can_generate 原子预留，这里不再 incr——只续期 + 打点
        if ip in LOCALHOST_IPS:
            return
        today = str(date.today())
        await state.expire(f"rate:{ip}:{today}", 86400)
        await state.incr("rate:total_generations")
        count = int(await state.get(f"rate:{ip}:{today}") or 0)
        logger.info("IP %s 试用成功 %d/%d", ip, count, settings.trials_per_ip)

    async def release_trial(self, ip: str):
        """生成失败——释放占用的试用名额，让用户可以重试。"""
        if ip in LOCALHOST_IPS:
            return
        today = str(date.today())
        count = int(await state.get(f"rate:{ip}:{today}") or 0)
        if count > 0:
            await state.incr(f"rate:{ip}:{today}", -1)

    async def record_cost(self, amount: float):
        # get-then-set 加锁，防并发生成丢花费记录
        today = str(date.today())
        async with self._lock:
            key = self._daily_spent_key(today)
            spent = float(await state.get(key) or 0)
            new_spent = spent + amount
            await state.set(key, str(new_spent), ttl=86400)
        logger.info("花费 ¥%.4f | 累计 ¥%.4f / ¥%.2f（剩余 ¥%.2f）",
                    amount, new_spent, settings.daily_budget,
                    max(0.0, settings.daily_budget - new_spent))


rate_limiter = RateLimiter()
