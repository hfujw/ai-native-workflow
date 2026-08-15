"""Prometheus 指标 — 面试时能说出"P99 渲染延迟 45s"。

3 Counter + 1 Histogram → 5 Counter + 2 Histogram + 1 Gauge。
暴露为 /metrics 端点，Prometheus 生态直接采集。
"""

from prometheus_client import Counter, Gauge, Histogram, generate_latest

# ── LLM 调用 ──

LLM_REQUESTS = Counter(
    "llm_requests_total",
    "Total LLM API calls",
    ["status", "tool"],  # status: success|timeout|error
)

LLM_LATENCY = Histogram(
    "llm_latency_seconds",
    "LLM API call latency",
    ["tool"],
    buckets=[1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0],
)

# ── WebSocket ──

WS_CONNECTIONS = Gauge(
    "ws_connections_active",
    "Current active WebSocket connections",
)

STATE_BACKEND = Gauge(
    "state_backend_available",
    "State backend availability (1=available, 0=down)",
    ["backend"],
)

# ── 生成全链路 ──

GENERATIONS = Counter(
    "generations_total",
    "Total generation attempts",
    ["status"],  # status: success|failed|rate_limited|timeout
)

GENERATION_DURATION = Histogram(
    "generation_duration_seconds",
    "End-to-end generation duration (WebSocket connect to page_ready)",
    buckets=[10.0, 20.0, 30.0, 45.0, 60.0, 90.0, 120.0, 180.0, 300.0],
)

GENERATION_STEPS = Histogram(
    "generation_steps",
    "Number of orchestrator steps per generation",
    buckets=[1, 2, 3, 5, 7, 10, 15, 20],
)

# ── RenderAgent 缓存 ──

RENDER_CACHE_HITS = Counter(
    "render_cache_hits_total",
    "RenderAgent cache hits",
)

RENDER_CACHE_MISSES = Counter(
    "render_cache_misses_total",
    "RenderAgent cache misses",
)

RENDER_CACHE_EVICTED = Counter(
    "render_cache_evicted_total",
    "RenderAgent cache entries evicted (expired or over limit)",
    ["reason"],  # reason: ttl_expired|capacity_limit
)


def metrics_text() -> str:
    """返回 Prometheus 文本格式的指标。"""
    return generate_latest().decode("utf-8")
