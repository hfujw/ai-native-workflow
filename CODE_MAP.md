# 时光像素 · 功能→代码速查表

> 面试复习用。每个功能点后面跟着代码位置，可以直接打开指给面试官看。

---

## 1. 核心编排（"LLM 自己决定流程"）

| 功能 | 代码位置 | 怎么实现的 |
|------|---------|-----------|
| ReAct 主循环 | `agents/orchestrator.py:107` | `while steps < max_steps and budget < total:` |
| LLM 决策下一步 | `agents/orchestrator.py:319-331` | `_decide()` → 构建上下文 → `chat_stream()` → `json.loads()` → 返回 `{"tool":"search","thought":"..."}` |
| 决策上下文构建 | `agents/orchestrator.py:297-309` | 用户输入 + 步数 + 预算 + 素材摘要 + 最近3步 + 验证问题 |
| 流式思考推前端 | `agents/orchestrator.py:146-155` | `push({"type":"thinking","thought":clean_thought(...)})` |
| 心跳保活 | `agents/orchestrator.py:162-168` | `asyncio.create_task(heartbeat())` → 每4秒推pulse → `finally: hb.cancel()` |
| 搜索死循环防护 | `agents/orchestrator.py:312-317` | `search_rounds >= 3 or (>=2且全空) → 禁止再搜` |
| 诚实模式触发 | `agents/orchestrator.py:131-135` | LLM 返回 `honest:true` → `decision["tool"]="render"` |
| 强制回退 | `agents/orchestrator.py:113-126` | `force_next_tool` → 跳过_decide → 直接执行指定工具 |
| 强制 verify | `agents/orchestrator.py:201-210` | 诚实模式或连续2次render成功 → `force_verify=True` |
| 搜索后评估 | `agents/orchestrator.py:192-199` | `evaluate_material()` 纯规则 → 推建议给LLM |
| 终止条件 | `agents/orchestrator.py:202-246` | verify通过→success / 连续2次失败→abort / 步数预算耗尽 |

## 2. 3 个 Agent

### ResearcherAgent（搜索）

| 功能 | 代码位置 | 怎么实现的 |
|------|---------|-----------|
| Agent 入口 | `agents/researcher_agent.py:29-65` | `run(topic, existing_material)` → 内部循环 |
| Tavily 搜索 | `tools/search.py:23-56` | `_search_tavily()` → HTTP POST → `api.tavily.com/search` |
| 广告过滤 | `tools/search.py:15-16` | `_filter_noise()` → 18 个广告关键词 |
| 相关性检查 | `tools/search.py:78-90` | query 的每个词是否在 title+snippet 中出现 |
| 换词重搜 | `agents/researcher_agent.py:49-64` | 原词搜不到 → 换角度（历史/起源/发展/影响…）|
| 向量兜底 | `agents/researcher_agent.py:85-101` | ChromaDB + text2vec-base-chinese → "嬴政"→"秦始皇" |
| 评估素材质量 | `agents/evaluate.py:5-19` | 统计相关条目数 → high/medium/low/none |
| Bus 监听 | `agents/researcher_agent.py:103-121` | `listen(bus)` → 收到search_request → 执行 → 返回search_result |

### DesignerAgent（设计+文案）

| 功能 | 代码位置 | 怎么实现的 |
|------|---------|-----------|
| Agent 入口 | `agents/designer_agent.py:37-71` | `run(material, user_input, bus)` → 设计→自检→求助→重试 |
| 叙事设计 | `tools/design.py:35-62` | LLM 分析素材 → 选7种组件之一（timeline/cards/encyclopedia…）|
| 文案撰写 | `tools/compose.py:38-58` | LLM 写文案 → 每个claim标注source+confidence |
| 素材量检查 | `agents/designer_agent.py:78-85` | `_check_design_fit()` → flowchart需≥2条/timeline需≥3条 |
| 组件降级 | `agents/designer_agent.py:87-102` | 素材不够 → flowchart→encyclopedia |
| 来源覆盖率 | `agents/designer_agent.py:104-113` | `_source_coverage()` → source非unknown的claims占比 |
| 向Researcher求助 | `agents/designer_agent.py:40-57` | bus.send("search_request") → bus.recv("search_result") |
| 百科降级 | `agents/designer_agent.py:115-130` | `_fallback()` → 百科条目+诚实文案 |

### RenderAgent（渲染）

| 功能 | 代码位置 | 怎么实现的 |
|------|---------|-----------|
| Agent 入口 | `agents/render_agent.py:36-97` | `run(design, content, push)` → 查缓存→生成→自检→重试 |
| 流式生成 | `agents/render_agent.py:110-128` | `_generate()` → `tool_render_stream()` |
| 自检 | `agents/render_agent.py:130-158` | 标签闭合 + 最小200字节 + 占位符 |
| DOCTYPE补全 | `agents/render_agent.py:69-70` | `lstrip().lower().startswith("<!doctype")` |
| 修复指引 | `agents/render_agent.py:160-178` | `_patch_hint()` → design追加修复提示 |
| 缓存key | `agents/render_agent.py:186-199` | SHA256(components+rationale+structure+visual_hint) |
| 缓存命中 | `agents/render_agent.py:46-53` | 类级变量`_cache: ClassVar` → TTL 5分钟+上限50条 |
| 缓存淘汰 | `agents/render_agent.py:203-213` | LRU删最老 + TTL过期清理 |
| 安全推送 | `agents/render_agent.py:101-108` | `_safe_push()` → try/except WebSocket断开 |
| 空内容短路 | `agents/render_agent.py:73-76` | `len(html) < 200 → 直接返回失败` |

## 3. 工具层

| 功能 | 代码位置 | 怎么实现的 |
|------|---------|-----------|
| 搜索 | `tools/search.py:55-99` | Tavily → 去重 → 广告过滤 → 相关性检查 |
| 设计 | `tools/design.py:35-62` | LLM prompt → JSON → 7种组件可选 |
| 文案 | `tools/compose.py:38-58` | source + confidence 强制标注 |
| 流式渲染 | `tools/render.py:84-128` | `chat_stream()` → 300字符+有`>` 或 2秒超时 → 推前端 |
| 审查 | `tools/verify.py:11-53` | Phase1硬规则 → Phase2 Playwright → Phase3事实核查 |
| 工具注册表 | `tools/__init__.py:13-18` | `TOOL_MAP` dict → tool_name → function |
| 虚拟预算 | `tools/__init__.py:10` | `TOOL_COST` → search 0.03 / design 0.13 / render 0.15 / verify 0.05 |

## 4. LLM 调用层

| 功能 | 代码位置 | 怎么实现的 |
|------|---------|-----------|
| 非流式调用 | `llm/client.py:46-120` | `chat()` → 最多3次重试 → 断路器包裹 → token记账 |
| 流式调用 | `llm/client.py:130-208` | `chat_stream()` → yield逐chunk → 字符估算fallback |
| stream_options降级 | `llm/client.py:146-163` | try带`include_usage` → except重试不带 |
| 断路器 | `llm/circuit_breaker.py:20-51` | CLOSED→连续3次失败→OPEN(30s)→HALF_OPEN→试探 |
| 围栏清洗 | `llm/parser.py:9-17` | `strip_fence()` → regex去掉 ```json ``` 包围 |
| thought清洗 | `llm/parser.py:20-41` | `clean_thought()` → 截断"我对XXX不太熟悉"等冗余开场白 |
| Token记账 | `llm/client.py:85-104` | `session_records.append({input_tokens, output_tokens, model})` |

## 5. 知识库

| 功能 | 代码位置 | 怎么实现的 |
|------|---------|-----------|
| 关键词匹配 | `knowledge/kb.py:61-92` | alias精确+3 / title匹配+3 / keyword子串+0.5 → best_score≥1 |
| 向量检索 | `knowledge/vector_store.py:72-97` | ChromaDB → text2vec-base-chinese → 距离<1.5 |
| KB初始化 | `knowledge/vector_store.py:56-69` | 161条话题 → embedding → ChromaDB持久化 |
| 话题数据 | `knowledge/verified_events.json` | 161条（计算机史/中国史/科学/艺术/体育…）|

## 6. 消息总线

| 功能 | 代码位置 | 怎么实现的 |
|------|---------|-----------|
| 注册Agent | `agents/message_bus.py:24-27` | `register(name)` → 创建asyncio.Queue |
| 发送消息 | `agents/message_bus.py:29-34` | `send(target, msg)` → `queue.put(msg)` |
| 接收消息 | `agents/message_bus.py:36-46` | `recv(name, timeout)` → `queue.get()` |
| Supervisor分发 | `agents/supervisor.py:19-39` | `TOOL_HANDLERS` dict → tool_name → handler |
| 实际调用 | `agents/supervisor.py:42-55` | `dispatch(ctx, tool_name)` → handler(ctx, bus) |

## 7. 安全

| 功能 | 代码位置 | 怎么实现的 |
|------|---------|-----------|
| 输入长度限制 | `config.py:45` + `main.py:212-221` | `input_max_length=500` → 超长拒绝 |
| IP 限流 | `network/rate_limiter.py:46-66` | `can_generate(ip)` → StateBackend + 每日重置 |
| 日预算帽 | `network/rate_limiter.py:76-81` | `record_cost(amount)` → `state.set("rate:daily_spent")` |
| IP 连接限制 | `network/ws_manager.py:48-55` | `max_connections_per_ip=3` → 超额拒绝 |
| WS 断开取消任务 | `main.py:365-368` | `WebSocketDisconnect` → `orch_task.cancel()` |
| 断路器 | `llm/circuit_breaker.py` | 3次失败熔断30s |
| 友好错误 | `main.py:126-140` | `_friendly_error()` → 6种错误映射到中文提示 |
| 日志脱敏 | `core/config.py` | API Key只在内存中，不写日志 |
| sandbox | `StoryPanel.tsx:106` | `allow-scripts` 但不 `allow-same-origin` |

## 8. 前端

| 功能 | 代码位置 | 怎么实现的 |
|------|---------|-----------|
| WS连接 | `hooks/useWebSocket.js:20-27` | `new WebSocket(ws://host/ws/generate)` |
| 8种消息处理 | `hooks/useWebSocket.js:38-98` | thinking/thinking_stream/tool_result/html_chunk/page_ready/failed/heartbeat |
| 断线重连 | `hooks/useWebSocket.js:116-133` | 指数退避 ×3次（1s→2s→4s）|
| 步骤进度线 | `DecisionLog.tsx:145-148` | 4步：搜→设→绘→鉴 |
| 光标聚光灯 | `RevealLayer.tsx:18-63` | Canvas 2D → radialGradient → maskImage |
| 流式渲染 | `StoryPanel.tsx:19-26` | `contentDocument.write()` 不换srcdoc（不频闪）|
| 显影动画 | `StoryPanel.tsx:88-93` | framer-motion opacity+scale+brightness |
| Demo 加载 | `hooks/useWebSocket.js:174-206` | `GET /api/demos/:name` → setPageHtml |

## 9. 部署

| 功能 | 代码位置 | 怎么实现的 |
|------|---------|-----------|
| Docker镜像 | `Dockerfile` | Playwright官方镜像 + 非root用户 + HEALTHCHECK |
| 反代+HTTPS | `Caddyfile` | 自动Let's Encrypt + WebSocket代理 + Gzip |
| 一键部署 | `docker-compose.yml` | Caddy + Backend + 卷挂载 |
| CI | `.github/workflows/ci.yml` | push→ ruff + pytest + docker build |
| Health探针 | `main.py:105-125` | `/api/health/live`(进程) + `/api/health/ready`(依赖) |
| 日志轮转 | `main.py:27-33` | TimedRotatingFileHandler → 每天午夜 → 保留30天 |

## 10. 监控

| 功能 | 代码位置 | 怎么实现的 |
|------|---------|-----------|
| Prometheus指标 | `core/metrics.py:9-69` | 5 Counter + 2 Histogram + 1 Gauge |
| /metrics端点 | `main.py:190-192` | `metrics_text()` → Prometheus格式 |
| 生成耗时 | `main.py:341-346` | `GENERATION_DURATION.observe()` |
| 缓存命中率 | `render_agent.py:50,86,205,217` | `RENDER_CACHE_HITS/MISSES/EVICTED` |
| LLM调用埋点 | `llm/client.py:97-99` | `LLM_REQUESTS + LLM_LATENCY` |
| Token统计 | `llm/client.py:85-104,167-183` | `session_records` → `get_cost_summary()` |

## 11. 面试数字速记

| 数字 | 含义 | 代码 |
|------|------|------|
| 20 | 最大步数 | `config.py:28` |
| ¥1 | 单次预算 | `config.py:29` |
| 8 | 最多搜索轮数 | `config.py:30` |
| 16384 | render max_tokens | `config.py:60` |
| 500 | 输入最大长度 | `config.py:45` |
| 3 | 断路器阈值 | `circuit_breaker.py:21` |
| 30s | 断路器恢复 | `circuit_breaker.py:21` |
| 50 | 缓存上限 | `render_agent.py:20` |
| 300s | 缓存TTL | `render_agent.py:21` |
| 200B | HTML最小检查 | `render_agent.py:135` |
| 2s | 渲染推送窗口 | `render.py:119` |
| 20 | WS最大连接 | `ws_manager.py:10` |
| 3 | 单IP最大连接 | `config.py:46` |
| 30天 | 日志保留 | `main.py:27-33` |
| 161条 | KB条目数 | `verified_events.json` |
| 36 | 测试用例数 | `tests/` |
