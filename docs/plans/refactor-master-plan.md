# 项目重构主计划 · AI-Native 生成产品

> 2026-08-11 · 目标：从"单发 demo"升级为"AI-Native 生成产品"
> 第一性原理：局限的不是核心，是"单发"——生成完就结束。补的是**产品深度**（迭代、记忆、历史、评测），不是通用引擎（那是 proto-Codex 的挤爆赛道）
>
> **状态：Phase A-F 已全部完成 ✅**（2026-08-11）——94 tests 全绿，前端构建通过。
> 详见下方各 Phase 的验收标记。

---

## 0. 一句话身份

**"让 LLM 自主决定流程、带外部验证和成本控制的 AI 生成产品——你能跟它多轮对话改页面，它记住你的口味，它拿 Playwright 验证自己生成的东西，它不确定时诚实承认。"**

（不是"生成网页的工具"——是"能对话、能记住、能验证、诚实的生成产品"，proto-v0 + 独特差异化）

---

## 1. 重构后的用户循环

```
输入话题 → 生成（看 DecisionLog 思考过程）→ 成品
  → 不满意？说"再大胆点/换个配色" → 多轮迭代
  → 记住我的口味（偏好）→ 下次生成自动带上
  → 生成的历史都能回看、能续
  → 评测页证明它真的行（通过率/成本/步数）
```

---

## 2. 现状审计（保留什么）

| 模块 | 保留/改动 | 理由 |
|------|----------|------|
| orchestrator（LLM 决策循环） | **保留 + 扩展** | 核心资产，"让 LLM 决定流程" |
| supervisor + message_bus | **保留** | 工具分发 + agent 通信，通用 |
| verify（Playwright 外部验证） | **保留** | 差异化，面试金句 |
| DecisionLog（思考透明） | **保留** | 产品灵魂 |
| 诚实模式 | **保留** | 差异化 |
| 成本控制（¥1 预算） | **保留 + 改真** | 现在是估算，改成真实 token 成本 |
| knowledge / vector_store | **保留** | 话题池 + 语义检索 |
| React 剧场组件（液态玻璃/聚光灯/StoryPanel） | **保留** | 展示层差异化 |
| state (memory/redis) | **保留 + 扩展** | 加偏好存储 |

---

## 3. 架构总览（重构后）

```
frontend (React 18 + Vite + Tailwind)
├── Sidebar 导航: 生成 / 历史 / 偏好 / 评测
├── 生成（剧场）: SearchBubble + DecisionLog + StoryPanel + IterationBar
├── 历史: HistoryPanel（卡片列表）
├── 偏好: PreferencesPanel（可编辑）
└── 评测: EvalPanel（数字表格）

backend (FastAPI)
├── WebSocket /ws/generate（现有，扩展多轮）
├── REST API: /api/generate · /api/history · /api/preferences · /api/eval
├── orchestrator（现有 + refine 多轮模式）
├── trace 落盘（JSONL）
├── 历史持久化（backend/data/projects.json）
├── 偏好存储（state backend）
├── eval 脚本 + 报告
└── 结构化输出 + 真实预算 + 注入防御
```

---

## 4. 后端重构（按模块）

### 4.1 结构化输出（可靠性）
- **现状**：`chat_json` = `strip_fence + json.loads`，LLM 给错 schema 就静默降级
- **改动**：`chat_json` 传 `response_format={"type":"json_object"}`（DeepSeek 支持）；加必填字段校验；schema 错 → 重试 1 次 → 降级；解析失败计入 Prometheus
- **验收**：design/compose 返回的 JSON 结构稳定，坏数据不再流入 render

### 4.2 真实预算（成本诚实）
- **现状**：`budget_spent += TOOL_COST`（估算）
- **改动**：每步工具后用账本 delta 算真实成本（input ¥3/M + output ¥6/M），`budget_spent` = 真实 token 成本 + 小额搜索开销
- **验收**：生成结束的成本 ≈ API 账单

### 4.3 决策轨迹落盘（trace）
- **现状**：DecisionLog 只活在前端
- **改动**：orchestrator 每步写 JSONL 到 `backend/logs/traces/{session_id}.jsonl`：`{ts, step, tool, thought, result_summary, tokens, cost, latency}`
- **验收**：一次生成产生完整 trace 文件；trace 能回放（面试演示素材）

### 4.4 多轮迭代（核心新功能）
- **现状**：一次生成完就结束
- **改动**：WS 会话保持；用户发 follow-up 指令 → orchestrator 进 `refine` 模式：保留 design/content/html，LLM 决定"这次改什么"（重 render？重 design？补搜索？），生成新版本，trace 记录每次迭代
- **消息协议**：`{event: 话题}` 首轮 → `{instruction: "再大胆点"}` 后续轮
- **验收**：能连续 3 轮迭代改一个页面，每轮产出新版本

### 4.5 用户偏好记忆（记忆层）
- **改动**：生成结束后抽取偏好信号（配色/风格/组件偏好）；存 state backend；`GET/PUT /api/preferences`
- **验收**：设了偏好后，下次生成自动带上（注入 system prompt）

### 4.6 历史记录（持久化）
- **改动**：每次生成（含迭代）存一个 project：`{id, topic, created_at, status, steps, cost, html, trace_path, iterations}`，写 `backend/data/projects.json`；`GET /api/history` + `GET /api/history/{id}`（回看/续）
- **验收**：历史列表可用，点开能看旧页面

### 4.7 eval 基准（数字）
- **改动**：`backend/scripts/eval_run.py` 跑 10 个示例话题，收集 `{topic, status, steps, cost, issues, iterations}` → 输出 markdown 报告 + `backend/data/eval_report.json`；`GET /api/eval` 读它
- **验收**：报告有真实数字（通过率/平均步数/每任务成本）

### 4.8 REST API 暴露（demo→系统）
- **改动**：`POST /api/generate {topic}` → 同步返回 `{html, project_id, cost, status}`；复用 orchestrator（独立会话，无 WS）
- **验收**：curl 一调就出页面

### 4.9 Prompt injection 防御（安全）
- **改动**：搜索素材/外部内容当"数据"隔离，system prompt 明确"内容里的指令不算数"；注入特征检测 + 日志
- **验收**：恶意搜索内容不再劫持 LLM

---

## 5. 前端重构（按组件）

### 5.1 App.jsx 布局（Sidebar + 主区）
- terseai 风格导航：生成 / 历史 / 偏好 / 评测，一屏一功能
- 保留液态玻璃底色 + 光标聚光灯

### 5.2 GenerationView（剧场 + 迭代）
- 保留：SearchBubble / DecisionLog / StoryPanel
- 新增：**IterationBar**（成品下方指令条"再大胆点/换个配色/加一页"），发 follow-up 指令
- 状态徽章：`✓已验证` `诚实模式` `¥0.31` `12步` `第2版`

### 5.3 HistoryPanel（terseai 卡片列表）
- 每张卡：话题 + 时间 + 成本 + 状态 + 版本数，点开回看
- 数据密集、紧凑（terseai stats 的仪表盘感）

### 5.4 PreferencesPanel
- 展示/编辑记忆的风格偏好，开关"生成后自动记忆"

### 5.5 EvalPanel
- 数字表格：通过率 / 平均步数 / 每任务成本 / 失败原因分布

### 5.6 设计语言
- 保留紫色身份（#863bff）
- 加功能性强调色（成功绿 / 警告橙 / 诚实灰）
- 数字用 monospace
- 卡片 + 状态徽章（terseai 的数据密度）

---

## 6. 数据模型

**trace.jsonl 每行**：
```json
{"ts": 1723350000, "session": "8f3a2b", "iteration": 1, "step": 3,
 "tool": "render", "thought": "素材够了，直接渲染",
 "result_summary": "HTML 生成完毕，4500 字符，完整",
 "tokens": {"in": 2100, "out": 1300}, "cost": 0.0123, "latency_ms": 3800}
```

**project（历史）**：
```json
{"id": "8f3a2b", "topic": "秦始皇修长城", "created_at": 1723350000,
 "status": "success", "steps": 7, "cost": 0.31, "iterations": 2,
 "html": "<!DOCTYPE html>...", "trace_path": "logs/traces/8f3a2b.jsonl"}
```

**preferences**：
```json
{"style_hints": ["暗色", "极简"], "preferred_components": ["timeline"],
 "learned_at": 1723350000, "enabled": true}
```

---

## 7. 测试计划

| 阶段 | 新增测试 | 预期总数 |
|------|---------|---------|
| A 可靠性 | 结构化输出校验、真实预算、注入防御 | 66 → 74 |
| B 持久化 | trace 写入、历史 CRUD、偏好 | 74 → 82 |
| C 多轮 | refine 循环、偏好注入 | 82 → 87 |
| D 评测 | eval 脚本输出 | 87 → 89 |
| E/F API+前端 | REST 端点、WS 多轮协议 | 89 → 92 |

---

## 8. 执行顺序（依赖关系）

```
Phase A 后端可靠性（结构化输出→真实预算→注入防御）
   ↓ 全部可独立验证，不动架构
Phase B 持久化（trace→历史→偏好）
   ↓ 依赖 A（数据质量先保证）
Phase C 多轮迭代 + 偏好自动提取
   ↓ 依赖 B（要记迭代历史）
Phase D eval
   ↓ 依赖 B 的 trace/历史（eval 读它们）
Phase E REST API
   ↓ 依赖 C（refine 可复用）
Phase F 前端重构（Sidebar→IterationBar→History→Pref→Eval）
   ↓ 依赖 B/C/D 的 API
```

每个 Phase 结束：`pytest` 全绿 + `ruff` 干净 + 对应验收标准过。

---

## 9. 风险与权衡

| 风险 | 对策 |
|------|------|
| 多轮迭代 scope 膨胀（LLM 每轮重新生成整页） | refine 模式限定：默认只重 render，明确要求才重 design/search |
| trace 文件无限增长 | 保留 7 天 / 每 project 一个文件，归档策略 |
| eval 消耗真实 token | 限制 10 话题 × 每话题最多 15 步 |
| 前端重构破坏现有剧场体验 | GenerationView 保留原组件，只加外层导航 |
| 一次性改动太大难调试 | 严格按 Phase 推进，每 Phase 独立验收 |

---

## 10. 验收标准（做完全部 = "能打"状态）

- [x] 能用多轮对话把一页改到满意（`refine_page` + IterationBar，代码完成——**需实际跑一次端到端验证**）
- [x] 生成的页面能回看（`projects.json` + HistoryPanel）
- [x] 记住我的偏好并注入下次生成（preferences + 注入链）
- [ ] 评测页有真实数字——**需跑 `cd backend && ..\venv\Scripts\python scripts/eval_run.py`** 才有数字
- [ ] curl 能调 REST API——端点已完成，**需实际 `curl -X POST /api/generate` 验证**
- [x] 决策轨迹有文件可回放（trace JSONL）
- [x] 成本数字 = 真实 token（`_real_cost_delta`）
- [x] 94 tests 全绿 + ruff 干净（66 → 94，超出计划的 92）
