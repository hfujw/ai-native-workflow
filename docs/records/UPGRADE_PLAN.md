# 时光像素 · 工程化升级完工文档

> 版本：v4.0 · 2026-08-06
> 状态：**全部完工** ✅
> 测试：21 passed, 0 failed

---

## 一、改了什么

### 新文件

| 文件 | 层级 | 功能 |
|------|------|------|
| `backend/app/config.py` | 配置 | `pydantic-settings` 集中管理——API Key、预算、限流、超时、工具参数，全部 env 可覆盖 |
| `backend/app/exceptions.py` | 异常 | `AppError` → `LLMError` / `LLMTimeoutError` / `SearchError` / `RenderError` / `RateLimitError` / `ConfigError`——用类型分类，不再字符串匹配 |
| `backend/app/rate_limiter.py` | 限流 | IP 级试用（1次/天）+ 全站日预算 ¥5 + 本地白名单 + 失败不扣，`asyncio.Lock` 并发安全 |
| `backend/app/demo.py` | Demo | 5 个预生成 HTML 的存取逻辑 + fallback 占位页 |
| `backend/app/metrics.py` | 可观测 | 3 Counter + 1 Histogram，`/metrics` 端点暴露 Prometheus 格式 |
| `backend/app/circuit_breaker.py` | 可靠性 | 三态断路器（CLOSED→OPEN→HALF_OPEN），连续 3 次失败熔断 30s |
| `backend/app/state/__init__.py` | 状态 | `state` 单例，根据 `STATE_BACKEND` 选择后端 |
| `backend/app/state/base.py` | 状态 | `StateBackend` 抽象基类——`get` / `set` / `incr` / `expire` 四方法 |
| `backend/app/state/memory.py` | 状态 | `MemoryBackend`——带 TTL 自动过期的内存实现，日期 key + expire 免手动清理 |
| `backend/app/state/agent_state.py` | 状态 | `AgentState` TypedDict——orchestrator 上下文字段声明，预留 LangGraph 迁移 |
| `backend/app/knowledge/vector_store.py` | RAG | ChromaDB + 中文 embedding（`text2vec-base-chinese`），语义检索"嬴政"→"秦始皇" |
| `.github/workflows/ci.yml` | CI | Push 自动跑 ruff + pytest --cov + docker build |
| `backend/Dockerfile` | 部署 | Playwright 官方镜像 + 非 root 用户 + HEALTHCHECK |
| `docker-compose.yml` | 部署 | 一键启动 backend + logs/demos 持久化 |
| `backend/tests/conftest.py` | 测试 | 共享 fixture |
| `backend/tests/pytest.ini` | 测试 | asyncio_mode = auto |
| `backend/tests/test_material_eval.py` | 测试 | `_evaluate_material`——0条/少相关/多相关/无关 |
| `backend/tests/test_strip_fence.py` | 测试 | `_strip_markdown_fence`——8 种 fence 格式 |
| `backend/tests/test_search_filter.py` | 测试 | `_filter_noise`——广告过滤 |
| `backend/tests/test_rate_limiter.py` | 测试 | `RateLimiter`——允许/拒绝/跨天/白名单/累计 |
| `backend/demos/` | Demo | 5 个 HTML 占位目录（本地跑一次替换） |

### 改动文件

| 文件 | 改动 |
|------|------|
| `backend/app/main.py` | lifespan 优雅关闭、全局超时、`html_chunk` 推送、`/metrics` + `/api/demos` + `/api/health` 端点、速率限制检查、print→logger |
| `backend/app/agents/orchestrator.py` | `session_id` 注入、流式 render 支持、向量搜索集成、结构化日志、推送到 `html_chunk` |
| `backend/app/tools.py` | `tool_search` async→`asyncio.to_thread`、新增 `tool_render_stream`（HTML 流式） |
| `backend/app/llm_client.py` | `_strip_markdown_fence` regex 增强、新增 `chat_stream()`、新增 `label` 参数、prompt 日志开关、Prometheus 埋点 |
| `backend/app/ws_manager.py` | `connect()` 连接上限 + 踢旧连接、`shutdown()` 优雅关闭、`send_page_ready()`、Prometheus 连接数 |
| `backend/app/knowledge/kb.py` | `"event"`→`"title"` 统一 |
| `backend/app/knowledge/verified_events.json` | `"event"`→`"title"` 全字段统一 |
| `backend/app/knowledge/verified_bagu.json` | 删 `difficulty` / `difficulty_dimensions` / `difficulty_range` |
| `backend/requirements.txt` | 删 bs4/websockets、补 playwright/pydantic-settings/prometheus-client/chromadb/ruff |
| `.gitignore` | 去重、补 `demos/*.html` / `.agents/` / `.playwright-mcp/` |
| `frontend/src/hooks/useWebSocket.js` | WS 断线重连、`html_chunk` 处理、`htmlStream` 状态、`loadDemo()` |
| `frontend/src/App.jsx` | demo 按钮 ✓ 标记 + hover 光晕、`handleTopicSelect` 路由、`htmlStream` 传递 |
| `frontend/src/components/StoryPanel.tsx` | 显影动画（framer-motion）+ 流式半成品 iframe |
| `frontend/src/components/SearchBubble.tsx` | "免费试用 · 每日 1 次"提示 |
| `frontend/src/components/DecisionLog.tsx` | 步骤进度线（搜→定→书→绘→鉴）+ 移动端 `max-w-[90vw]` |

---

## 二、架构全貌

```
                                ┌─────────────┐
                                │   用户浏览器   │
                                └──────┬──────┘
                                       │
              ┌────────────────────────┼────────────────────────┐
              │                        │                        │
              ▼                        ▼                        ▼
     ┌────────────────┐    ┌─────────────────────┐    ┌─────────────────┐
     │  演示按钮点击    │    │  自定义搜索（试用1次）  │    │  右侧标签云      │
     │  GET /api/demos │    │  WS /ws/generate    │    │  EventTags      │
     └───────┬────────┘    └──────────┬──────────┘    └────────┬────────┘
             │                        │                        │
             │                        ▼                        │
             │              ┌─────────────────┐                │
             │              │  rate_limiter    │                │
             │              │  IP检查 + 预算帽  │                │
             │              └────────┬────────┘                │
             │                       │                          │
             │                       ▼                          │
             │              ┌─────────────────┐                │
             │              │  orchestrator    │                │
             │              │  ReAct 主循环     │◄───────────────┘
             │              │                  │
             │              │  _decide() → LLM │──→ 5 个工具
             │              │       ↑          │    search(bing + KB + RAG)
             │              │       │          │    design
             │              │       │          │    compose
             │              │       │          │    render（流式 HTML）
             │              │       └──────────│    verify（Playwright）
             │              │   异常回退 + 策略切换│
             │              └────────┬────────┘
             │                       │
             │                       ▼
             │              ┌─────────────────┐
             │              │   WebSocket      │
             │              │   实时推送        │
             │              │   thinking       │
             │              │   tool_result    │
             │              │   html_chunk     │
             │              │   page_ready     │
             │              └────────┬────────┘
             │                       │
             ▼                       ▼
     ┌─────────────────────────────────────────┐
     │              StoryPanel                  │
     │   显影动画 + iframe 展示                  │
     └─────────────────────────────────────────┘
```

---

## 三、配置项速查

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `DEEPSEEK_API_KEY` | **必填** | API 密钥 |
| `DEEPSEEK_MODEL` | `deepseek-chat` | 模型名 |
| `DAILY_BUDGET` | `5.0` | 全站日预算（元） |
| `TRIALS_PER_IP` | `1` | 每 IP 每天试用次数 |
| `MAX_STEPS` | `20` | Agent 最大循环步数 |
| `GENERATION_TIMEOUT` | `300` | 单次生成超时（秒） |
| `LOG_PROMPTS` | `0` | 设为 `1` 记录完整 prompt |
| `STATE_BACKEND` | `memory` | `memory` / `redis`（未来） |

---

## 四、代码走读（6 条路径，从浏览器到后端再回来）

> 看代码时照着这些路径走，每一步旁边有文件:行号和一句话解释。
> 
> 🌐 = 浏览器端　　⚙️ = 后端　　🤖 = 调 LLM　　🔍 = 外部搜索

---

### 🗺️ 路径 1：输入"秦始皇修长城" → 完整生成

```
🌐 用户在输入框打字，点 "生成"
│
├─ frontend/src/hooks/useWebSocket.js:135
│  sendEvent("秦始皇修长城")
│  打开 WebSocket，发 {event: "秦始皇修长城"}
│
├─ frontend/src/components/DecisionLog.tsx:67
│  面板出现，脉冲绿点 + "正在唤醒 AI 策展人…"
│
▼ WebSocket ──────────────────────────────────────
│
⚙️ backend/app/main.py:188  generate_page()
│
├─ :191  ws_manager.connect()         ← 检查连接上限(20)
├─ :199  receive_json(30s 超时)      ← 等用户输入
├─ :211  rate_limiter.can_generate() ← IP 检查 + 日预算检查
├─ :220  logger.info("新请求 | ...") ← 结构化日志
├─ :223  推 "准备策展…" 到前端        ← 🌐 DecisionLog 显示
│
├─ :260  ⏱️ asyncio.wait_for(        ← 300s 超时保护
│          orchestrator_node(...))
│
│   ⚙️ backend/app/agents/orchestrator.py:58
│   │
│   ├─ [初始化]
│   │  :83  kb.py:61 get_event_by_keyword()    ← 关键词匹配 33 条 KB
│   │  :88  vector_store.py:59 vector_search() ← 🔍 ChromaDB 语义检索
│   │        ("嬴政"→"秦始皇修长城")
│   │
│   ├─ [循环]  while 步数<20 and 花费<¥1:
│   │
│   │  ┌─ Step 1: 思考
│   │  │  :109  _decide() → 🤖 chat() → LLM 返回 {"tool":"search"}
│   │  │  :112  push("thinking") → 🌐 DecisionLog 显示思考过程
│   │  │
│   │  ├─ Step 1: 行动
│   │  │  :133  _execute_tool("search")
│   │  │       → tools.py:24  tool_search()
│   │  │       → web_search.py:133  Bing 搜索 (asyncio.to_thread)
│   │  │       → 去重 + 广告过滤 + 相关性检查
│   │  │       → ctx["material"] 填充搜索结果
│   │  │
│   │  ├─ :146  搜索完评估素材质量
│   │  │       _evaluate_material() → high/medium/low
│   │  │       low → 触发诚实模式 ⚠️
│   │  │
│   │  ┌─ Step 2: 思考 → 🤖 {"tool":"design"}
│   │  ├─ Step 2: 行动 → tools.py:85  tool_design()
│   │  │               LLM 选叙事形式 (timeline/cards/encyclopedia)
│   │  │
│   │  ┌─ Step 3: 思考 → 🤖 {"tool":"compose"}
│   │  ├─ Step 3: 行动 → tools.py:144  tool_compose()
│   │  │               LLM 写文案 + 每个数字标来源
│   │  │
│   │  ┌─ Step 4: 思考 → 🤖 {"tool":"render"}
│   │  ├─ Step 4: 行动 → tools.py:242  tool_render_stream() 💧流式
│   │  │   ┌─ llm_client.py:129  chat_stream(stream=True)
│   │  │   │  逐 chunk ← 🤖 DeepSeek 一段段返回 HTML
│   │  │   │
│   │  │   ├─ yield {"html": accumulated, "complete": False}
│   │  │   │      ↓
│   │  │   │  orchestrator:373  push({"type":"html_chunk"})
│   │  │   │      ↓
│   │  │   │  main.py:239  push() → ws_manager.send_json()
│   │  │   │      ↓
│   │  │   │  🌐 useWebSocket.js:57  case 'html_chunk'
│   │  │   │     setHtmlStream(data.html)
│   │  │   │      ↓
│   │  │   │  StoryPanel.tsx:55  <iframe srcDoc={htmlStream}>
│   │  │   │     💧 用户看到页面一段段"长出来"
│   │  │   │
│   │  │   └─ yield {"html": code, "complete": True}  ← 最后一帧
│   │  │
│   │  ┌─ Step 5: 思考 → 🤖 {"tool":"verify"}
│   │  ├─ Step 5: 行动 → tools.py:245  tool_verify()
│   │  │   Phase 1: </html> 存在？ <script> 存在？ 占位符残留？
│   │  │   Phase 2: Playwright 真执行 → JS 报错检测
│   │  │   Phase 3: claims 有来源标注？ (>50%)
│   │  │
│   │  ├─ ✅ 通过 → :174 push("complete")
│   │  │          → main.py:251  ws_manager.send_page_ready()
│   │  │          → 🌐 useWebSocket.js:62  case 'page_ready'
│   │  │          → StoryPanel.tsx:66  显影动画 ✨ 展示成品
│   │  │          → :181 return {"status":"success"}
│   │  │
│   │  └─ ❌ 未通过 → :188 强制回退 render/compose
│   │                → 最多重试 2 次 → 超了→ "素材不匹配"
│   │
│   └─ [循环耗尽] :232 push("failed") → 🌐 FailureNotice
│
├─ :274  get_cost_summary()          ← 统计 token 花费
├─ :280  rate_limiter.record_cost()  ← 累加到日预算
├─ :283  GENERATIONS.inc()           ← Prometheus 指标
├─ :285  rate_limiter.record_success(ip) ← 扣减试用(仅成功)
└─ :313  ws_manager.disconnect()     ← 清理连接
```

---

### 🗺️ 路径 2：点演示按钮 → 秒开（零 API 费用）

```
🌐 frontend/src/App.jsx:80
   <motion.button> 秦始皇修长城 ✓ </motion.button>
   点击 → loadDemo("秦始皇修长城")
   (✓ 表示这段 HTML 已生成好，有缓存)

🌐 frontend/src/hooks/useWebSocket.js:174
   loadDemo()
   ├─ 关闭 WebSocket（不管跑没跑完）
   ├─ setPageHtml(null), setHtmlStream(''), setError(null)
   └─ fetch("/api/demos/秦始皇修长城")
         │
         ▼
⚙️ backend/app/main.py:165  get_demo()
         │
         ▼
⚙️ backend/app/demo.py:50  load_demo_html()
   ├─ "秦始皇修长城" ∉ DEMO_TOPICS？ → 404
   ├─ backend/demos/秦始皇修长城.html 存在？
   │   ├─ ✅ 打开文件，返回 HTML（cached=true）
   │   └─ ❌ 返回 _fallback_html() 占位页（cached=false）
         │
         ▼
🌐 loadDemo() 收到响应
   ├─ data.cached？ 📖 "已加载演示：秦始皇修长城"
   │              ⏳ "待生成——本地跑一次即可"
   └─ setPageHtml(data.html)
         │
         ▼
🌐 StoryPanel.tsx:66
   <AnimatePresence>
     <motion.div 从中心放大 + 亮度回归 ✨ 显影动画>
       <iframe srcDoc={html} />
```

---

### 🗺️ 路径 3：试用用完 → 被拒 + 引导

```
🌐 用户再次输入自定义主题 → 点"生成"
│
▼
⚙️ main.py:211  rate_limiter.can_generate(ip)
│
├─ rate_limiter.py:67  _reset_if_new_day()  ← 跨天了？重置所有计数
├─ :70  ip == "127.0.0.1"？ → ✅ 本地开发直接放行
├─ :73  _daily_spent >= ¥5？   → ❌ "今日全站免费额度已用完 🎨"
├─ :76  _successful_trials[ip] >= 1？ → ❌ "您今日的免费试用次数已用完"
└─ 返回 (False, reason)
│
▼
⚙️ main.py:215  ws_manager.send_failed(reason, DEMO_TOPICS)
│  suggestions = ["秦始皇修长城","Turing 破译 Enigma", ...]
│
▼
🌐 useWebSocket.js:69  case 'generation_failed'
│  setError({reason, suggestions})
│
▼
🌐 FailureNotice.tsx:29
│  ┌─────────────────────────────────┐
│  │ ⚠️ 生成失败                      │
│  │ 您今日的免费试用次数已用完         │
│  │                                 │
│  │ 建议尝试：                        │
│  │ [秦始皇修长城] [Turing破译Enigma] │
│  │ [Python装饰器]  [郑和下西洋]      │
│  └─────────────────────────────────┘
│
▼ 用户点建议按钮
🌐 App.jsx:21  handleTopicSelect("秦始皇修长城")
   DEMO_TOPICS.includes("秦始皇修长城") → loadDemo("秦始皇修长城")
   → 走路径 2 ✨ 秒开展示
```

---

### 🗺️ 路径 4：DeepSeek 挂了 → 熔断保护

```
🤖 llm_client.py:69  chat()
   │
   ├─ 第 1 次 API 调用 → ❌ Exception (timeout/5xx)
   │  :116 等 2^0=1s 重试
   ├─ 第 2 次 API 调用 → ❌ Exception
   │  :116 等 2^1=2s 重试
   └─ 第 3 次 API 调用 → ❌ Exception
      :121 进 error 分支 → raise last_error
         │
         ▼
⚙️ circuit_breaker.py:38  CircuitBreaker.call()
   failure_count: 1 → 2 → 3 💥
   state: CLOSED → OPEN
   │
   ├─ 后续 30s 内所有请求：
   │  :31  if state == OPEN → raise CircuitOpenError
   │  "AI 服务暂时不可用，请稍后重试"
   │
   └─ 30s 后：
      :29  state: OPEN → HALF_OPEN（试探一次）
      :35  成功 → CLOSED（恢复）  失败 → OPEN（继续熔断）
```

---

### 🗺️ 路径 5：素材不足 → 诚实降级

```
⚙️ orchestrator.py
   search 返回 0 条或结果全不相关
   │
   ▼
⚙️ :146  _evaluate_material(ctx["material"], "朱子钦")
   │
   ├─ material 为空？ → {"level":"none", "reason":"零素材"}
   ├─ 0 条相关？    → {"level":"low", "reason":"素材与主题不直接相关"}
   │
   ▼
⚙️ :149  ctx["honest_mode"] = True
   :151  push("⚠️ 素材与主题不直接相关。进入诚实模式")
   │
   ▼
⚙️ :297  _decide() 的 prompt 追加：
   "⚠️【诚实模式】禁止 design/compose，
    直接 render 一个诚实页面。不要编造。只生成一次。"
   │
   ▼
   LLM render 生成 → "关于「朱子钦」的资料有限，以下为诚实呈现…"
   │
   ▼
⚙️ :162  force_verify = True → 自动 verify
   诚实模式 verify：跳过内容匹配检查，只看 HTML 是否完整
   │
   ▼
   ✅ 通过 → 返回 HTML（标注"资料有限"）
   ❌ 不重试——诚实模式只生成一次
```

---

### 🗺️ 路径 6：CTRL+C → 优雅退出

```
⚙️ 终端：Ctrl+C 或 docker stop
   │
   ▼
⚙️ main.py:56  lifespan()
   yield 之后的 shutdown：
   │
   ├─ "正在关闭，等待飞行中请求完成…"
   │
   ▼
⚙️ ws_manager.py:48  shutdown(timeout=5.0)
   │
   ├─ for 每个在线用户：
   │    await ws.close(code=1001, reason="服务器维护中")
   │    WS_CONNECTIONS.dec()  ← Prometheus
   │
   ├─ self.connections.clear()
   │
   ▼
   "服务已关闭"
   ───────────────── 进程退出
```

---

## 🧭 想看代码时应该打开的顺序

| 顺序 | 文件 | 看什么 |
|------|------|--------|
| 1 | `backend/app/main.py` | 入口：WebSocket 连接 → 限流 → 超时 → 结果处理 |
| 2 | `backend/app/agents/orchestrator.py` | 核心：while 循环 → _decide → _execute_tool → 回退 |
| 3 | `backend/app/tools.py` | 5 个工具的具体实现 + 流式渲染 |
| 4 | `backend/app/llm_client.py` | LLM 调用封装 + fence + stream |
| 5 | `backend/app/rate_limiter.py` | IP 限流 + 日预算帽 |
| 6 | `backend/app/ws_manager.py` | WebSocket 连接管理 + 优雅关闭 |
| 7 | `backend/app/circuit_breaker.py` | 断路器状态机 |
| 8 | `backend/app/config.py` | 所有可配置项一览 |
| 9 | `backend/app/state/` | AgentState 定义 + StateBackend |
| 10 | `backend/app/knowledge/` | KB + 向量检索 |
| 11 | `frontend/src/hooks/useWebSocket.js` | 前端 WebSocket 逻辑 |
| 12 | `frontend/src/App.jsx` | 入口 + 布局 |
| 13 | `frontend/src/components/` | StoryPanel / DecisionLog / FailureNotice |

---

## 五、面试速查

| 能展示的技术点 | 代码在哪 | 面试怎么说 |
|-------------|---------|-----------|
| ReAct 编排 | `orchestrator.py:58` while 循环 | "LLM 每步自主决策，非固定流水线" |
| 防幻觉 | `orchestrator.py:242` + `tools.py:245` | "外置评估 + 溯源标注 + Playwright 真执行" |
| 诚实模式 | `orchestrator.py:146-154` | "素材不足自动降级，不编造" |
| 流式渲染 | `llm_client.py:129` + `tools.py:242` | "HTML 逐段生成，用户看到页面长出来" |
| 状态抽象 | `state/base.py` | "Memory/Redis 双后端，改一行配置切换" |
| 断路器 | `circuit_breaker.py` | "连续 3 次失败熔断 30s，防止级联故障" |
| 限流 + 预算 | `rate_limiter.py` | "IP 1次/天 + ¥5 硬帽，公网部署不破产" |
| RAG 语义检索 | `knowledge/vector_store.py` | "ChromaDB + 中文 embedding，嬴政→秦始皇" |
| Prometheus | `metrics.py` + `llm_client.py:100` | "/metrics 端点，P99 渲染延迟可观测" |
| CI/CD | `.github/workflows/ci.yml` | "push 自动 ruff + pytest + docker build" |
| 优雅关闭 | `main.py:56` lifespan | "飞行中请求不丢数据" |
| 结构化日志 | `orchestrator.py` 全部 log 行 | "session_id 串联完整请求生命周期" |
| Docker | `Dockerfile` + `docker-compose.yml` | "官方 Playwright 镜像，docker-compose up 一键启动" |
