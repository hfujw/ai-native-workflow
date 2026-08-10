# 性能深度剖析

> 2026-08-08
> 当前瓶颈：单 worker 串行、LLM 调用 30-60s 是绝对主导耗时

---

## 1. 单 Worker → 多 Worker 方案

### 问题

当前 `Dockerfile` 的 `--workers 1` 意味着同一时刻只能处理一个 WebSocket 连接上的 LLM 生成流程。第二个用户连接进来时，虽然 WebSocket 能建立（FastAPI 异步），但如果两个请求同时调 `chat_stream`，单 worker 的 asyncio 事件循环是共享的——**两个请求可以并发**（asyncio 的协程并发），不是串行。

真正的问题不是"单 worker 串行"，而是 **RateLimiter 和 CircuitBreaker 的状态在多 worker 下不同步**。开 4 个 worker → 4 个独立的 Python 进程 → 4 份 `_successful_trials` 字典 → IP 限流失效。

### Dockerfile 多 Worker 配置

```dockerfile
# Dockerfile —— 修改 CMD 行
# 之前：CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
# 之后：

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${WORKERS:-2} --proxy-headers --forwarded-allow-ips='*'"]
```

```bash
# 环境变量控制 worker 数
docker run -e WORKERS=4 ... time-pixel
```

### WebSocket 多 Worker 下的问题

```
           Nginx / Caddy
                │
        ┌───────┼───────┐
        ▼       ▼       ▼
    Worker1  Worker2  Worker3    ← 4 个独立进程
        │       │       │
        └───────┼───────┘
                │
        共享什么？          ← 目前：什么都不共享
```

**问题 1：WebSocket 连接粘滞（Sticky Session）**

用户 A 的 WebSocket 连接到 Worker1，后续消息必须发到同一个 Worker。Nginx/Caddy 需要 IP Hash 或 cookie-based 路由。

**Caddy 粘滞配置**：
```caddy
handle /ws/* {
    reverse_proxy backend:8000 {
        lb_policy header X-Forwarded-For  # 按客户端 IP 粘滞
    }
}
```

**问题 2：跨 Worker 消息广播**

orchestrator 在 Worker1 运行，但 WebSocket 连接在 Worker2。`push()` 需要把消息从 Worker1 传到 Worker2。

**解决方案：Redis Pub/Sub**

```python
# backend/app/network/ws_bridge.py
"""WebSocket 跨 Worker 桥接——用 Redis Pub/Sub 广播消息。"""
import json, logging, asyncio

logger = logging.getLogger(__name__)

class WSBridge:
    """多 Worker 下，orchestrator 的消息通过 Redis 广播到所有 Worker，
    持有 WebSocket 连接的那个 Worker 负责发送给客户端。"""

    def __init__(self, redis_client, session_id: str, local_push):
        self.redis = redis_client
        self.session_id = session_id
        self._local_push = local_push  # 本地直接发（同 Worker 场景）
        self._channel = f"ws:{session_id}"

    async def push(self, msg: dict):
        """广播消息——本地直接发 + Redis 发给其他 Worker。"""
        # 本地发送（同 Worker）
        await self._local_push(msg)
        # 跨 Worker 广播
        try:
            await self.redis.publish(self._channel, json.dumps(msg, ensure_ascii=False))
        except Exception as e:
            logger.debug("redis_publish_failed: %s", e)

    async def listen(self):
        """当前 Worker 作为 WebSocket 持有者，监听来自其他 Worker 的消息。"""
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(self._channel)
        async for message in pubsub.listen():
            if message["type"] == "message":
                data = json.loads(message["data"])
                await self._local_push(data)  # 转发给 WebSocket 客户端
```

**何时需要 Redis Pub/Sub？** 只有 Caddy/Nginx 把同一个 session 的请求路由到不同 Worker 时才需要。如果用了 IP Hash 粘滞，同一个 IP 的所有请求都到同一个 Worker → 不需要跨 Worker 通信 → 不需要 Redis Pub/Sub。

**结论：当前阶段用 Caddy `lb_policy header X-Forwarded-For` 粘滞路由 + 保持单 worker，等日活 > 100 再上多 Worker + Redis。**

---

## 2. 基准测试方案

### Locust WebSocket 测试脚本

```python
# tests/benchmark/locustfile.py
import time, json
from locust import User, task, between
from websocket import create_connection

class TimePixelUser(User):
    wait_time = between(5, 15)  # 模拟用户思考时间

    def on_start(self):
        self.ws = create_connection("ws://localhost:8000/ws/generate")
        self.start_time = time.monotonic()

    def on_stop(self):
        self.ws.close()

    @task
    def generate_short_topic(self):
        """测试轻量话题（KB 命中 + 快速生成）。"""
        self.ws.send(json.dumps({"event": "Python 装饰器"}))
        self._wait_for_complete()

    @task(3)  # 权重 3x——更常见
    def generate_demo_topic(self):
        """测试 Demo 话题（LLM 全链路）。"""
        self.ws.send(json.dumps({"event": "秦始皇修长城"}))
        self._wait_for_complete()

    def _wait_for_complete(self):
        timeout = 300
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            msg = json.loads(self.ws.recv())
            if msg.get("type") in ("page_ready", "generation_failed"):
                break
```

### 预期指标

| 指标 | 目标值 | 说明 |
|------|--------|------|
| 单请求 P50 延迟 | < 45s | 含 LLM 调用 30-40s |
| 单请求 P99 延迟 | < 120s | 含重试场景 |
| 并发 5 用户 | 全部在 120s 内完成 | asyncio 并发 |
| 缓存命中时延 | < 500ms | 直接返回缓存 HTML |
| WebSocket 连接建立 | < 100ms | |
| 错误率 | < 2% | |

### 运行方式

```bash
pip install locust websocket-client
locust -f tests/benchmark/locustfile.py --host=http://localhost:8000 --users 5 --spawn-rate 1
# 打开 http://localhost:8089 查看实时图表
```

---

## 3. Vite 打包优化

```js
// vite.config.js
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8001',
      '/ws': { target: 'ws://localhost:8001', ws: true },
    },
  },
  build: {
    // Chunk 拆分：第三方库单独打包（利用浏览器缓存）
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor-react': ['react', 'react-dom'],
          'vendor-motion': ['framer-motion'],
          'vendor-icons': ['lucide-react'],
        },
      },
    },
    // 压缩
    minify: 'terser',
    terserOptions: {
      compress: { drop_console: true, drop_debugger: true },
    },
    // 目标浏览器
    target: 'es2020',
    // 启用 CSS 代码分割
    cssCodeSplit: true,
    // 资源内联阈值（< 4KB 的图片内联为 base64）
    assetsInlineLimit: 4096,
    // Source map（生产关闭）
    sourcemap: false,
  },
})
```

### 打包产物分析

```bash
npm run build
# 预期结果：
# dist/
#   index.html                (~1KB)
#   assets/index-abc123.js    (~15KB) ← 你的代码
#   assets/vendor-react-xyz.js (~130KB) ← React 单独缓存
#   assets/vendor-motion.js   (~40KB)  ← Framer Motion
#   assets/vendor-icons.js    (~10KB)  ← Lucide icons
#   assets/index-def456.css   (~5KB)   ← Tailwind
```

---

## 4. LLM 调用链时序图

```
用户输入 "秦始皇修长城"
    │
    ▼
    │ ←── WebSocket 握手 (50ms)
    ▼
    │ ←── RateLimiter 检查 (1ms，内存)
    ▼
    │ ←── KB 关键词匹配 (0.1ms，内存)
    │ ←── 向量语义检索 (200ms，ChromaDB 首次加载模型)
    ▼
    │ ←── _decide() LLM 调用 (2-5s，DeepSeek API)
    │      └── chat_stream: 输入 ~800 tokens, 输出 ~100 tokens
    ▼
    │ ←── tool_search() Tavily API (1-3s，网络延迟)
    │      └── 5-8 条结果，相关性过滤
    ▼
    │ ←── evaluate_material() (0.1ms，本地规则)
    ▼
    │ ←── _decide() LLM 调用 (2-5s)
    │      └── chat_stream: 输入 ~900 tokens, 输出 ~200 tokens
    ▼
    │ ←── tool_design() LLM 调用 (3-8s)
    │      └── chat_json: 输入 ~1700 tokens, 输出 ~300 tokens
    ▼
    │ ←── tool_compose() LLM 调用 (5-15s)
    │      └── chat_stream: 输入 ~2000 tokens, 输出 ~500 tokens
    ▼
    │ ←── RenderAgent.run()
    │      │
    │      ├── tool_render_stream() LLM 调用 (15-60s) ← 最慢！
    │      │      └── chat_stream: 输入 ~2500 tokens, 输出 ~4000 tokens
    │      │
    │      ├── _self_check() (0.1ms)
    │      │
    │      └── push → 前端 (50ms，WebSocket)
    ▼
    │ ←── tool_verify()
    │      ├── Phase 1: 正则硬规则 (0.1ms)
    │      ├── Phase 2: Playwright 启动 (500ms，首次慢)
    │      │      └── page.set_content(html) (100ms)
    │      │      └── page.wait_for_timeout(800ms)
    │      └── Phase 3: 事实核查 (0.1ms)
    ▼
    │ ←── push → 前端: page_ready (50ms)
    ▼
    完成

总耗时估计：
  - 最简路径（搜索→KB命中→跳过搜索→直接render）: 25-40s
  - 标准路径（搜索→评估→design→compose→render→verify）: 45-90s
  - 重试路径（verify失败→回退重render）: 60-120s

瓶颈分析：
  1. tool_render_stream  (15-60s, 占 60%) ← 最大瓶颈
  2. tool_compose         (5-15s, 占 15%)
  3. _decide ×2           (4-10s, 占 12%)
  4. tool_design          (3-8s, 占 8%)
  5. tool_verify          (1-2s, 占 3%)   ← Playwright 冷启动
  6. 其他                 (<1s, 占 2%)
```

---

## 5. RenderAgent 缓存命中率监控

### Prometheus Counter

```python
# core/metrics.py 追加
RENDER_CACHE_HITS = Counter(
    "render_cache_hits_total",
    "RenderAgent cache hits",
)
RENDER_CACHE_MISSES = Counter(
    "render_cache_misses_total",
    "RenderAgent cache misses",
)
RENDER_CACHE_STALE = Counter(
    "render_cache_stale_total",
    "RenderAgent cache entries evicted (expired or over limit)",
)
```

### 埋点位置

```python
# agents/render_agent.py run() 方法
cached = self._cache_get(cache_key)
if cached is not None:
    RENDER_CACHE_HITS.inc()  # ← 这里
    ...

# 生成完成 → 未命中缓存
RENDER_CACHE_MISSES.inc()    # ← 这里

# 淘汰（_cache_set 中超限）
if len(self._cache) >= CACHE_MAX:
    RENDER_CACHE_STALE.inc() # ← 这里
```

### Grafana 面板 PromQL

```promql
# 缓存命中率
rate(render_cache_hits_total[5m]) /
(rate(render_cache_hits_total[5m]) + rate(render_cache_misses_total[5m]))

# 缓存命中数 (QPS)
rate(render_cache_hits_total[1m])

# 缓存未命中数 (QPS)
rate(render_cache_misses_total[1m])
```
