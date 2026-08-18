"""LLM 客户端 — DeepSeek API 异步封装。

Key 全部来自前端设置（会话级绑定，随 WS/REST 发送）——后端不读 .env 的 key。
没有绑定任何 key → 调用时报"未配置 API Key"（没填就是没填）。
"""

import asyncio
import contextvars
import logging
import os

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)
# HTTP 请求超时（秒）——必须 ≥ 最慢的 LLM 调用时长。
# render 生成完整教育网页一次要 16000 tokens（约 5 分钟），旧值 120s 会在生成中途
# 触发 httpx 连接超时 → 所有阶段连环"DeepSeek 超时"失败。提到 600s 对齐 generation_timeout。
DEFAULT_TIMEOUT = 600
MAX_RETRIES = 2


class LLMNotConfiguredError(RuntimeError):
    """未配置 API Key——配置错误，不是临时故障：不重试、不降级，直接上抛。"""


def _assert_configured() -> None:
    """入口检查：当前会话有没有可用的 LLM 客户端。没有 → 明确报错（没填就是没填）。"""
    if _session_client.get() is None:
        raise LLMNotConfiguredError(
            "未配置 API Key——请在 Lumen 设置 → 模型 里填写所用模型的 API Key")


def _describe_llm_error(e: Exception) -> str:
    """把 LLM 调用异常转成可读描述：优先 status code + 服务端真实消息。

    很多 OpenAI SDK 异常的 str() 不友好（或只含英文包装），这里尽量
    提取 HTTP 状态和响应 body 里的 message，方便定位是网络/限流/参数/key。
    """
    status = getattr(e, "status_code", None)
    if status is not None:
        # APIStatusError 系：body 里通常有 error.message
        body = getattr(e, "body", None)
        if isinstance(body, dict):
            err = body.get("error") or {}
            msg = err.get("message") if isinstance(err, dict) else None
            if msg:
                return f"HTTP {status} | {msg}"
        return f"HTTP {status} | {type(e).__name__} | {str(e)[:200]}"
    return f"{type(e).__name__} | {str(e)[:200]}"

# 会话级客户端：用户在前端设置的 Key/Base（contextvars——只影响当前任务及其子任务，
# 不污染其他连接；不绑定则 _get_client 明确报错）
_session_client: contextvars.ContextVar = contextvars.ContextVar(
    "llm_session_client", default=None)

# 模型必须由用户在前端填写（Composer 选择）——后端不再有默认模型，缺模型直接报错。
# 模型名归一化见 normalize_model()——DeepSeek 官方改名后（v4-flash/v4-pro），
# 用户前端可能存着各种变体（大小写、简名、旧名），统一模糊映射到官方名。


def normalize_model(model: str | None) -> str | None:
    """把用户传来的模型名映射到官方名；未知模型原样透传。

    DeepSeek 官方现行名：deepseek-v4-flash / deepseek-v4-pro。
    用户可能填各种变体（大小写、简名、旧名）——只要以 deepseek 开头就模糊映射：
      - 含 "pro" 或 "reasoner" → deepseek-v4-pro
      - 其他（flash/chat/裸 deepseek）→ deepseek-v4-flash
    """
    if not model:
        return model
    key = str(model).strip()
    low = key.lower()
    if low.startswith("deepseek"):
        if "pro" in low or "reasoner" in low:
            return "deepseek-v4-pro"
        return "deepseek-v4-flash"
    return key  # 未知模型（gpt-4o 等自定义网关）原样透传


def is_reasoning_model(model: str | None) -> bool:
    """推理模型（不支持 response_format=json_object）。

    注意：先归一化再判断——所有 pro/reasoner 变体都映射到 deepseek-v4-pro。
    """
    if not model:
        return False
    return normalize_model(model) == "deepseek-v4-pro"


def bind_session_client(api_key: str | None = None, base_url: str | None = None) -> None:
    """绑定当前会话的 LLM 客户端（用户在前端设置的 API Key 生效）。

    必须在 asyncio.create_task 之前调用——contextvars 在创建任务时复制，
    子任务（orchestrator）才能继承绑定。没 key → 不绑定（调用时报未配置）。
    """
    key = (api_key or "").strip()
    if not key:
        _session_client.set(None)
        return
    # 脱敏诊断日志：只记前 8 位 + 长度，帮定位"前端发的是完整 key 还是掩码"
    logger.info("bind_session_client | key=%s*** | len=%d | base=%s",
                key[:8], len(key), base_url or "(默认)")
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

    effective_model = normalize_model(model)  # 统一官方名；模型必须前端填，无默认
    if not effective_model:
        raise LLMNotConfiguredError("未配置模型——请在 Lumen 设置 → 模型 里填写所用模型")

    last_error = None
    from app.llm.circuit_breaker import CircuitOpenError, llm_breaker
    for attempt in range(MAX_RETRIES + 1):
        try:
            create_kwargs = dict(
                model=effective_model,
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
                    "model": effective_model,
                }
                # 会话账本：传入才记账；不传则不记（不再有全局账本）
                if session_records is not None:
                    session_records.append(entry)
                    logger.info("LLM tokens: in=%d out=%d total=%d",
                                usage.prompt_tokens, usage.completion_tokens,
                                usage.total_tokens)
            return content

        except CircuitOpenError:
            # 断路器已熔断（服务故障中）→ 不再重试，直接上抛，让编排层快速失败
            raise
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES:
                wait = 2 ** attempt
                logger.warning("LLM call failed (attempt %d/%d): %s, retrying in %ds...",
                               attempt + 1, MAX_RETRIES + 1, _describe_llm_error(e), wait)
                await asyncio.sleep(wait)
            else:
                logger.error("LLM call failed after %d attempts: %s", MAX_RETRIES + 1,
                             _describe_llm_error(e))

    raise last_error or RuntimeError("LLM call failed with unknown error")


async def chat_json(prompt: str, system: str = "", model: str = None,
                    session_records: list[dict] | None = None) -> str:
    """异步 JSON 调用——优先 DeepSeek 结构化输出（json_object），失败降级普通调用。

    结构化输出能显著降低"LLM 返回围栏/多余文字导致 json.loads 失败"的概率。
    ⚠️ 推理模型（deepseek-reasoner / deepseek-v4-pro）不支持 response_format=json_object
    （H2 修复）——推理模型下直接走普通调用，靠 prompt 要求 JSON + safe_parse_json 兜底。
    """
    if is_reasoning_model(model):
        # 推理模型：不传 response_format（会被拒），prompt 内已有 JSON 要求
        return await chat(prompt, system=system, model=model, temperature=0.1,
                          session_records=session_records)
    try:
        return await chat(prompt, system=system, model=model, temperature=0.1,
                          session_records=session_records,
                          response_format={"type": "json_object"})
    except Exception as e:
        logger.warning("chat_json 结构化输出失败(%s)，降级普通调用", _describe_llm_error(e))
        return await chat(prompt, system=system, model=model, temperature=0.1,
                          session_records=session_records)


async def chat_stream(prompt: str, system: str = "", model: str = None,
                      temperature: float = 0.3, max_tokens: int = 16384,
                      session_records: list[dict] | None = None,
                      label: str = "unknown"):
    """流式输出——逐 chunk yield 文本片段。

    不修改 chat() 签名。session_records 写入独立账本，label 用于日志定位。
    """
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    # 配置错误不降级：没填 key → 立即抛 LLMNotConfiguredError
    _assert_configured()

    effective_model = normalize_model(model)  # 模型必须前端填，无默认
    if not effective_model:
        raise LLMNotConfiguredError("未配置模型——请在 Lumen 设置 → 模型 里填写所用模型")

    # 建连可重试（此刻还没 yield 任何内容，重开是安全的）。
    # 一旦开始消费流就不再重试——流无法干净重开，中断直接上抛（_decide 有失败计数兜底）。
    response = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            # DeepSeek 兼容层不一定支持 stream_options——报错就降级
            try:
                response = await _get_client().chat.completions.create(
                    model=effective_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=True,
                    stream_options={"include_usage": True},
                )
            except Exception as e:
                logger.debug("stream_options 不支持，降级重试: %s", e)
                response = await _get_client().chat.completions.create(
                    model=effective_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=True,
                )
            break  # 建连成功，开始消费流
        except Exception as e:
            if attempt < MAX_RETRIES:
                wait = 2 ** attempt
                logger.warning("LLM stream 建连失败 (attempt %d/%d): %s, %ds 后重试…",
                               attempt + 1, MAX_RETRIES + 1, _describe_llm_error(e), wait)
                await asyncio.sleep(wait)
            else:
                logger.error("LLM stream 建连失败 after %d attempts: %s",
                             MAX_RETRIES + 1, _describe_llm_error(e))
                raise

    try:
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

        # 兜底：DeepSeek 不一定返回 usage，拿不到精确值就用字符数估算。
        # 中文约 1.5-2 字符/token、英文约 4 字符/token——取 2 偏高估
        # （护栏原则：宁可高估预算，不少算；旧的 //4 会低估中文，¥1 护栏可能穿透）
        if prompt_tokens == 0:
            prompt_tokens = max(1, len(prompt) // 2)
        if completion_tokens == 0:
            completion_tokens = max(1, completion_chars // 2)

        # 记账：传入会话账本才记；不传则不记（不再有全局账本）
        entry = {
            "input_tokens": prompt_tokens,
            "output_tokens": completion_tokens,
            "cache_hit_tokens": cache_hit_tokens,
            "model": effective_model,
        }
        if session_records is not None:
            session_records.append(entry)

        if session_records is not None:
            logger.info("LLM stream tokens: in=%d out=%d total=%d",
                        prompt_tokens, completion_tokens, total_tokens)

    except Exception:
        raise
