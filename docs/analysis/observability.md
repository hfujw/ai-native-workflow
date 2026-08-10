# 可观测性体系

> 2026-08-08
> 当前：Prometheus 指标 + 结构化日志
> 目标：Prometheus + OpenTelemetry 追踪 + Grafana 仪表盘 + AlertManager 告警

---

## 1. Prometheus 指标全集（已实现）

| 指标名 | 类型 | Labels | 说明 |
|--------|------|--------|------|
| `llm_requests_total` | Counter | status, tool | LLM API 调用次数（success/error） |
| `llm_latency_seconds` | Histogram | tool | LLM API 延迟（1s~120s buckets） |
| `llm_tokens_total` | Counter | direction, tool | Token 消耗（input/output） |
| `ws_connections_active` | Gauge | — | 活跃 WebSocket 连接数 |
| `generations_total` | Counter | status | 生成请求总数（success/failed/rate_limited/timeout） |
| `generation_duration_seconds` | Histogram | — | 端到端生成耗时（10s~300s buckets） |
| `generation_steps` | Histogram | — | orchestrator 步数分布（1~20 buckets） |
| `render_cache_hits_total` | Counter | — | RenderAgent 缓存命中 |
| `render_cache_misses_total` | Counter | — | RenderAgent 缓存未命中 |
| `render_cache_evicted_total` | Counter | reason | 缓存淘汰（ttl_expired/capacity_limit） |

---

## 2. OpenTelemetry 分布式追踪

### 安装

```bash
pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp
```

### 实现

```python
# backend/app/core/tracing.py
"""OpenTelemetry 追踪——每个 session 一个 Trace，贯穿全链路。"""

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.trace import Status, StatusCode
import logging

logger = logging.getLogger(__name__)

# 初始化 Tracer
provider = TracerProvider()
exporter = OTLPSpanExporter(endpoint="http://localhost:4318/v1/traces")
provider.add_span_processor(BatchSpanProcessor(exporter))
trace.set_tracer_provider(provider)

tracer = trace.get_tracer("time-pixel")


async def trace_session(session_id: str, user_input: str):
    """创建一个 session 级别的 Span，贯穿整个生成流程。"""
    with tracer.start_as_current_span(
        "generation",
        attributes={
            "session.id": session_id,
            "user.input": user_input[:100],  # 截断保护
        },
    ) as span:
        yield span


async def trace_llm_call(tool: str, model: str, tokens_in: int, tokens_out: int, duration_s: float):
    """记录一次 LLM 调用的 Span。"""
    with tracer.start_as_current_span(
        f"llm.{tool}",
        attributes={
            "llm.tool": tool,
            "llm.model": model,
            "llm.tokens_input": tokens_in,
            "llm.tokens_output": tokens_out,
            "llm.duration_s": round(duration_s, 2),
        },
    ):
        pass  # Span 自动结束，记录耗时


async def trace_tool_call(tool: str, status: str, detail: str = ""):
    """记录一次工具调用的 Span。"""
    with tracer.start_as_current_span(
        f"tool.{tool}",
        attributes={
            "tool.name": tool,
            "tool.status": status,
            "tool.detail": detail[:200],
        },
    ):
        pass
```

### Trace 链路示例

```
generation (session=abc123, input="秦始皇修长城")
├── llm.decide (3.2s, tokens: 800→120)
├── tool.search (1.5s, results=5)
├── llm.decide (2.8s, tokens: 900→180)
├── tool.design (5.1s, components=["timeline","cards"])
├── tool.compose (8.3s, blocks=2)
├── llm.render (28.7s, tokens: 2500→4200)  ← 瓶颈
│   └── render_agent.self_check (0.1ms, passed)
└── tool.verify (1.4s, passed, playwright=true)
```

### 集成到 orchestrator

```python
# orchestrator.py _decide()
from app.core.tracing import trace_llm_call

t0 = _time.monotonic()
async for chunk in chat_stream(...):
    ...
# 记录 Trace
tokens_in = len(summary) // 4   # 粗略
tokens_out = len(accumulated) // 4
await trace_llm_call("decide", "deepseek-chat", tokens_in, tokens_out, _time.monotonic() - t0)
```

---

## 3. Grafana 仪表盘

### 面板清单

| 面板 | 类型 | PromQL | 说明 |
|------|------|--------|------|
| **QPS** | Stat | `rate(generations_total[1m])` | 每秒生成请求数 |
| **P50 延迟** | Stat | `histogram_quantile(0.5, rate(generation_duration_seconds_bucket[5m]))` | 中位数耗时 |
| **P99 延迟** | Stat | `histogram_quantile(0.99, rate(generation_duration_seconds_bucket[5m]))` | 99 分位耗时 |
| **延迟分布** | Heatmap | `rate(generation_duration_seconds_bucket[5m])` | 耗时热力图 |
| **错误率** | Stat | `sum(rate(generations_total{status!="success"}[5m])) / sum(rate(generations_total[5m])) * 100` | 错误百分比 |
| **错误类型** | Pie | `sum(rate(generations_total[5m])) by (status)` | 错误分类 |
| **LLM 调用 QPS** | Graph | `sum(rate(llm_requests_total[1m])) by (tool)` | 各工具 LLM 调用频率 |
| **LLM P99 延迟** | Graph | `histogram_quantile(0.99, rate(llm_latency_seconds_bucket[5m])) by (tool)` | 各工具 LLM 耗时 |
| **Token 消耗** | Graph | `rate(llm_tokens_total[5m])` | 每 5 分钟 token 消耗 |
| **缓存命中率** | Gauge | `rate(render_cache_hits_total[5m]) / (rate(render_cache_hits_total[5m]) + rate(render_cache_misses_total[5m])) * 100` | RenderAgent 缓存命中率 % |
| **活跃连接** | Graph | `ws_connections_active` | WebSocket 连接数 |
| **日花费** | Stat | `increase(llm_tokens_total[24h]) / 1000000 * 3` 估算 | 24h LLM 花费 |

### Grafana JSON 片段（可导入）

关键面板的 JSON 配置见 `docs/grafana-dashboard.json`。核心指标已在上面列出，Grafana UI 中可以手动创建。

---

## 4. 告警规则

### Prometheus AlertManager 规则

```yaml
# backend/prometheus/alerts.yml
groups:
  - name: time-pixel
    rules:

      # ── 延迟告警 ──
      - alert: HighP99Latency
        expr: histogram_quantile(0.99, rate(generation_duration_seconds_bucket[5m])) > 120
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "P99 生成延迟超过 120s"
          description: "当前 P99 延迟 {{ $value | humanizeDuration }}，影响用户体验"

      # ── 错误率告警 ──
      - alert: HighErrorRate
        expr: |
          sum(rate(generations_total{status!="success"}[5m]))
          / sum(rate(generations_total[5m])) > 0.05
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "错误率超过 5%"
          description: "当前错误率 {{ $value | humanizePercentage }}，过去 5 分钟 {{ $labels.status }} 类错误"

      # ── LLM 调用失败率 ──
      - alert: HighLLMFailureRate
        expr: |
          sum(rate(llm_requests_total{status="error"}[5m]))
          / sum(rate(llm_requests_total[5m])) > 0.10
        for: 3m
        labels:
          severity: critical
        annotations:
          summary: "LLM 调用失败率超过 10%"
          description: "当前失败率 {{ $value | humanizePercentage }}，可能是 API Key 问题或 DeepSeek 服务异常"

      # ── LLM 熔断告警 ──
      - alert: CircuitBreakerOpen
        expr: increase(llm_requests_total{status="error"}[1m]) == 0 and ws_connections_active > 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "断路器可能已熔断——有活跃连接但无 LLM 调用"
          description: "检查 DeepSeek API 状态和 API Key 余额"

      # ── 日预算告警 ──
      - alert: DailyBudgetExhausted
        expr: |
          (increase(llm_tokens_total{direction="input"}[24h]) * 3
           + increase(llm_tokens_total{direction="output"}[24h]) * 6) / 1000000 > 4.5
        labels:
          severity: warning
        annotations:
          summary: "日预算接近耗尽"
          description: "过去 24 小时 LLM 花费约 ¥{{ $value }}，日预算 ¥5"

      # ── 缓存命中率下降 ──
      - alert: LowCacheHitRate
        expr: |
          rate(render_cache_hits_total[15m])
          / (rate(render_cache_hits_total[15m]) + rate(render_cache_misses_total[15m])) < 0.1
        for: 15m
        labels:
          severity: info
        annotations:
          summary: "RenderAgent 缓存命中率低于 10%"
          description: "可能 design+content 组合变化频繁，或缓存容量不足"

      # ── WebSocket 连接数异常 ──
      - alert: HighWSConnections
        expr: ws_connections_active > 18
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "WebSocket 连接数接近上限（20）"
          description: "当前 {{ $value }} 个连接，建议扩容或检查是否有连接泄漏"
```

### 告警路由

| 严重度 | 通知方式 | 示例 |
|--------|---------|------|
| critical | 电话/短信 | PagerDuty、阿里云短信 |
| warning | 即时消息 | 企业微信机器人、Slack Webhook |
| info | 邮件 | 日报汇总 |

### Slack Webhook 集成

```yaml
# backend/prometheus/alertmanager.yml
receivers:
  - name: 'slack'
    slack_configs:
      - api_url: 'https://hooks.slack.com/services/xxx'
        channel: '#alerts'
        title: '[{{ .Status | toUpper }}] {{ .CommonLabels.alertname }}'
        text: '{{ .CommonAnnotations.description }}'
```

---

## 5. 可观测性上线检查清单

- [ ] Prometheus `/metrics` 端点可访问（仅内网）
- [ ] Grafana 数据源已配置（Prometheus URL）
- [ ] 4 个核心面板已创建（QPS、P99、错误率、缓存命中率）
- [ ] 告警规则已部署到 AlertManager
- [ ] Slack/邮件通知渠道已测试
- [ ] 日志保留策略已确认（30 天 TimedRotatingFileHandler）
- [ ] OpenTelemetry Collector 已部署（Phase 2）
