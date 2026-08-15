"""LLM 客户端 — DeepSeek API 异步封装。

Key 全部来自前端设置（会话级绑定，随 WS/REST 发送）——后端不读 .env 的 key。
没有绑定任何 key → 调用时报"未配置 API Key"（没填就是没填）。
"""

import asyncio
import contextvars
import logging
import os
import time

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)
DEFAULT_TIMEOUT = 120
MAX_RETRIES = 2


class LLMNotConfiguredError(RuntimeError):
    """未配置 API Key——配置错误，不是临时故障：不重试、不降级，直接上抛。"""


def _assert_configured() -> None:
    """入口检查：当前会话有没有可用的 LLM 客户端。没有 → 明确报错（没填就是没填）。"""
    if _session_client.get() is None:
        raise LLMNotConfiguredError(
            "未配置 API Key——请在 Lumen 设置 → 模型 里填写所用模型的 API Key")

# 会话级客户端：用户在前端设置的 Key/Base（contextvars——只影响当前任务及其子任务，
# 不污染其他连接；不绑定则 _get_client 明确报错）
_session_client: contextvars.ContextVar = contextvars.ContextVar(
    "llm_session_client", default=None)

DEFAULT_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")


def bind_session_client(api_key: str | None = None, base_url: str | None = None) -> None:
    """绑定当前会话的 LLM 客户端（用户在前端设置的 API Key 生效）。

    必须在 asyncio.create_task 之前调用——contextvars 在创建任务时复制，
    子任务（orchestrator）才能继承绑定。没 key → 不绑定（调用时报未配置）。
    """
    key = (api_key or "").strip()
    if not key:
        _session_client.set(None)
        return
    _session_client.set(AsyncOpenAI(
        api_key=key,
        base_url=base_url or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        timeout=DEFAULT_TIMEOUT,
    ))


def clear_session_client() -> None:
    """清除当前会话绑定。"""
    _session_client.set(None)


def _get_client() -> AsyncOpenAI:
    """当前会话的客户端；没有绑定 → 明确报错（没填就是没填，不静默回落）。"""
    client = _session_client.get()
    if client is None:
        raise RuntimeError("未配置 API Key——请在 Lumen 设置 → 模型 里填写所用模型的 API Key")
    return client


def get_cost_summary(records: list[dict]) -> dict:
    """计算费用——按模型费率表计价（见 llm/pricing.py），未知模型兜底。"""
    # 防御：个别账本条目缺 token 字段时按 0 计，并打日志暴露问题记录
    for r in records:
        if "input_tokens" not in r or "output_tokens" not in r:
            logger.warning("账本条目缺 token 字段（不应发生）: %s", str(r)[:120])
    total_input = sum(r.get("input_tokens", 0) for r in records)
    total_output = sum(r.get("output_tokens", 0) for r in records)
    total_cache_hit = sum(r.get("cache_hit_tokens", 0) for r in records)
    from app.llm.pricing import compute_cost
    cost = compute_cost(records)
    return {
        "calls": len(records),
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_cache_hit_tokens": total_cache_hit,
        "estimated_cost_rmb": round(cost, 4),
        "records": records[-20:],
    }


async def chat(prompt: str, system: str = "", model: str = None, temperature: float = 0.7,
               max_tokens: int = 16384, session_records: list[dict] | None = None,
               label: str = "unknown", response_format: dict | None = None) -> str:
    """异步单轮对话，含自动重试。

    session_records: 传入则写入该会话独立账本；不传则不记账（已无全局账本）。
    label: 调用来源标签（如 "decide"/"render"），用于日志定位。
    response_format: 结构化输出（如 {"type": "json_object"}）——提升 JSON 可靠性。
    """
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    # 配置错误不重试：没填 key → 立即抛 LLMNotConfiguredError（入口检查）
    _assert_configured()

    last_error = None
    from app.llm.circuit_breaker import llm_breaker, CircuitOpenError
    for attempt in range(MAX_RETRIES + 1):
        try:
            create_kwargs = dict(
                model=model or DEFAULT_MODEL,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            if response_format:
                create_kwargs["response_format"] = response_format
            response = await llm_breaker.call(
                _get_client().chat.completions.create(**create_kwargs)
            )

            content = response.choices[0].message.content
            if content is None:
                logger.warning("LLM returned None content, retrying...")
                continue

            logger.debug("LLM REQUEST — system=%d chars, user=%d chars", len(system), len(prompt))
            if os.getenv("LOG_PROMPTS", "0") == "1":
                logger.debug("LLM SYSTEM:\n%s", system[:3000])
                logger.debug("LLM PROMPT:\n%s", prompt[:5000])
                logger.debug("LLM RESPONSE:\n%s", content[:5000])

            usage = response.usage
            if usage:
                entry = {
                    "input_tokens": usage.prompt_tokens,
                    "output_tokens": usage.completion_tokens,
                    "cache_hit_tokens": getattr(usage, "prompt_cache_hit_tokens", None) or 0,
                    "model": model or DEFAULT_MODEL,
                }
                # 会话账本：传入才记账；不传则不记（不再有全局账本）
                if session_records is not None:
                    session_records.append(entry)
                    logger.info("LLM tokens: in=%d out=%d total=%d | 累计¥%.4f",
                                usage.prompt_tokens, usage.completion_tokens,
                                usage.total_tokens,
                                get_cost_summary(session_records)["estimated_cost_rmb"])
            return content

        except CircuitOpenError:
            # 断路器已熔断（服务故障中）→ 不再重试，直接上抛，让编排层快速失败
            raise
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES:
                wait = 2 ** attempt
                logger.warning("LLM call failed (attempt %d/%d): %s, retrying in %ds...",
                               attempt + 1, MAX_RETRIES + 1, e, wait)
                await asyncio.sleep(wait)
            else:
                logger.error("LLM call failed after %d attempts: %s", MAX_RETRIES + 1, e)

    raise last_error or RuntimeError("LLM call failed with unknown error")


async def chat_json(prompt: str, system: str = "", model: str = None,
                    session_records: list[dict] | None = None) -> str:
    """异步 JSON 调用——优先 DeepSeek 结构化输出（json_object），失败降级普通调用。

    结构化输出能显著降低"LLM 返回围栏/多余文字导致 json.loads 失败"的概率。
    """
    try:
        return await chat(prompt, system=system, model=model, temperature=0.1,
                          session_records=session_records,
                          response_format={"type": "json_object"})
    except Exception as e:
        logger.warning("chat_json 结构化输出失败(%s)，降级普通调用", e)
        return await chat(prompt, system=system, model=model, temperature=0.1,
                          session_records=session_records)


async def chat_stream(prompt: str, system: str = "", model: str = None,
                      temperature: float = 0.3, max_tokens: int = 16384,
                      session_records: list[dict] | None = None,
                      label: str = "unknown"):
    """流式输出——逐 chunk yield 文本片段。

    不修改 chat() 签名。session_records 写入独立账本，label 用于日志定位。
    """
    import time as _time
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    # 配置错误不降级：没填 key → 立即抛 LLMNotConfiguredError
    _assert_configured()

    try:
        # DeepSeek 兼容层不一定支持 stream_options——报错就降级
        try:
            response = await _get_client().chat.completions.create(
                model=model or DEFAULT_MODEL,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                stream_options={"include_usage": True},
            )
        except Exception as e:
            logger.debug("stream_options 不支持，降级重试: %s", e)
            response = await _get_client().chat.completions.create(
                model=model or DEFAULT_MODEL,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )

        total_tokens = 0
        prompt_tokens = 0
        completion_tokens = 0
        cache_hit_tokens = 0
        completion_chars = 0
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                text = chunk.choices[0].delta.content
                yield text
                completion_chars += len(text)
            if chunk.usage:
                total_tokens = chunk.usage.total_tokens
                prompt_tokens = chunk.usage.prompt_tokens or 0
                completion_tokens = chunk.usage.completion_tokens or 0
                cache_hit_tokens = getattr(chunk.usage, "prompt_cache_hit_tokens", None) or 0

        # 兜底：DeepSeek 不一定返回 usage，拿不到精确值就用字符数估算
        # 1 token ≈ 4 字符（中文约 2 字符，英文约 4 字符，取 4 保守估计）
        if prompt_tokens == 0:
            prompt_tokens = max(1, len(prompt) // 4)
        if completion_tokens == 0:
            completion_tokens = max(1, completion_chars // 4)

        # 记账：传入会话账本才记；不传则不记（不再有全局账本）
        entry = {
            "input_tokens": prompt_tokens,
            "output_tokens": completion_tokens,
            "cache_hit_tokens": cache_hit_tokens,
            "model": model or DEFAULT_MODEL,
        }
        if session_records is not None:
            session_records.append(entry)

        if session_records is not None:
            logger.info("LLM stream tokens: in=%d out=%d total=%d | 累计¥%.4f",
                        prompt_tokens, completion_tokens, total_tokens,
                        get_cost_summary(session_records)["estimated_cost_rmb"])

    except Exception:
        raise
