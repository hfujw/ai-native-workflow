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
        self.last_error: Exception | None = None  # 最近一次真实失败原因（诊断用）

    async def call(self, coro):
        """包裹 LLM API 调用。熔断中直接抛异常，不浪费一次网络请求。"""
        if self.state == State.OPEN:
            if time.monotonic() - self.last_failure_time > self.recovery_timeout:
                self.state = State.HALF_OPEN
                logger.info("circuit_breaker=half_open")
            else:
                logger.warning("circuit_breaker=open — 拒绝请求（上次失败: %s）",
                               _describe_error(self.last_error))
                raise CircuitOpenError(self.last_error)

        try:
            result = await coro
            if self.state == State.HALF_OPEN:
                self.state = State.CLOSED
                self.failure_count = 0
                logger.info("circuit_breaker=closed — 已恢复")
            return result
        except Exception as e:
            # 认证错误（401/403）= key 问题；参数错误（400/422）= 调用方 bug。
            # 都不是服务故障——不计数不熔断（重试也没用，熔断会误伤整个服务）
            if openai is not None and isinstance(
                e, (openai.AuthenticationError, openai.PermissionDeniedError)
            ):
                logger.warning("circuit_breaker=auth_error — 不熔断 | %s", type(e).__name__)
                raise
            status = getattr(e, "status_code", None)
            if status in (400, 422):
                logger.warning("circuit_breaker=param_error — 不熔断 | %s", _describe_error(e))
                raise
            self.last_error = e  # 记住真实原因，熔断时报给用户
            self.failure_count += 1
            self.last_failure_time = time.monotonic()
            if self.failure_count >= self.failure_threshold:
                self.state = State.OPEN
                logger.warning("circuit_breaker=open — 连续 %d 次失败，原因: %s",
                               self.failure_count, _describe_error(e))
            raise


def _describe_error(e: Exception | None) -> str:
    """把真实异常转成可读原因（带类型，方便诊断是网络/限流/参数）。"""
    if e is None:
        return "未知"
    # OpenAI SDK 异常：尽量提取 status + message
    status = getattr(e, "status_code", None)
    if status is not None:
        return f"HTTP {status} | {type(e).__name__} | {str(e)[:200]}"
    return f"{type(e).__name__} | {str(e)[:200]}"


class CircuitOpenError(Exception):
    """断路器打开时抛出——携带真实失败原因，方便用户/日志诊断。"""
    def __init__(self, cause: Exception | None = None):
        self.cause = cause
        super().__init__(f"AI 服务暂时不可用，请稍后重试（原因: {_describe_error(cause)}）")


# 全局单例
llm_breaker = CircuitBreaker()
