"""LLM 调用断路器 — 防止 DeepSeek 挂了之后仍不断重试浪费时间和 Token。

状态机：CLOSED（正常）→ OPEN（熔断）→ HALF_OPEN（探测）→ CLOSED
连续 3 次失败 → 熔断 30 秒 → 试一次 → 成功恢复，失败继续熔断
"""

import logging
import time
from enum import Enum

try:
    import openai
except ImportError:  # pragma: no cover — openai 是硬依赖，防御式兜底
    openai = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class State(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, recovery_timeout: int = 30):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = State.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0.0

    async def call(self, coro):
        """包裹 LLM API 调用。熔断中直接抛异常，不浪费一次网络请求。"""
        if self.state == State.OPEN:
            if time.monotonic() - self.last_failure_time > self.recovery_timeout:
                self.state = State.HALF_OPEN
                logger.info("circuit_breaker=half_open")
            else:
                logger.warning("circuit_breaker=open — 拒绝请求")
                raise CircuitOpenError()

        try:
            result = await coro
            if self.state == State.HALF_OPEN:
                self.state = State.CLOSED
                self.failure_count = 0
                logger.info("circuit_breaker=closed — 已恢复")
            return result
        except Exception as e:
            # P3：认证错误（401/403）是 key 问题不是服务故障——不计数不熔断，
            # 避免坏 key 把断路器熔断成"服务全挂"
            if openai is not None and isinstance(
                e, (openai.AuthenticationError, openai.PermissionDeniedError)
            ):
                logger.warning("circuit_breaker=auth_error — 不熔断 | %s", type(e).__name__)
                raise
            self.failure_count += 1
            self.last_failure_time = time.monotonic()
            if self.failure_count >= self.failure_threshold:
                self.state = State.OPEN
                logger.warning("circuit_breaker=open — 连续 %d 次失败", self.failure_count)
            raise


class CircuitOpenError(Exception):
    """断路器打开时抛出，调用方直接返回友好提示。"""
    def __init__(self):
        super().__init__("AI 服务暂时不可用，请稍后重试")


# 全局单例
llm_breaker = CircuitBreaker()
