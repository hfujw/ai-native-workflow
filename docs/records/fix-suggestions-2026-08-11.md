# 修复建议 · 2026-08-11

> 产物：对抗性审查（Bug 清单）+ 第一性原理整理清理计划。
> 状态：✅ P0/P1 已修复 + L1 死代码已删 + L2 复习文件已归档，62 tests 全绿（含 5 条新增回归测试）。
> 未执行：P2 各项（P2-5/6/7/8/9）、L4-1 demo 双源、L4-2 包 __init__ 一致性。

---

## 一、对抗性审查发现的 Bug

### 🔴 P0-1 · render 截断 → 整个生成必崩（最狠） — ✅ 已修复
**文件**：`backend/app/agents/orchestrator.py:204`（塞字符串）→ `orchestrator.py:292-295`（对字符串调 `.get`）

**链路**：render 自检两次不过 / 空内容 → `complete=False` → orchestrator 往 `ctx["issues"]` 追加**字符串** `"render自动失败：HTML截断"` → 下一轮 `_decide()` 构建上下文时 `i.get('severity','?')` 对字符串调用 → **AttributeError**。异常发生在 `_decide` 的 `try` 块之外（try 在 323 行），无人接住 → 打出整个生成 → main.py 兜底发通用错误。

**讽刺点**：这正是系统设计成要优雅恢复的路径（"HTML截断 → 必须重render"），现在恢复路径 100% 死在下一个 decide 上。已最小脚本实锤 `'str' object has no attribute 'get'`。

**根因**：`ctx["issues"]` 混合类型——orchestrator 塞 str，verify 工具塞 dict。`main.py:360` 的 `i.get('description')` 是同一根因的第二受害点。

**修复**：
```python
# orchestrator.py:204 — 一行根治
ctx["issues"].append({"severity": "critical", "category": "incomplete",
                      "description": "render自动失败：HTML截断"})
```
顺带在 `_decide` / `main.py` 加 `isinstance(i, dict)` 防御。

**补测试**：render 返回 `complete=False` 后，`_decide` 不崩（当前无覆盖）。

---

### 🔴 P0-2 · `/api/cost` 端点必 500 — ✅ 已删除端点
**文件**：`backend/app/main.py:141`

`get_cost_summary()` 无参调用，但签名已改成必传 `records`（本次重构删除全局 `_cost_records` 时没同步改调用方）。实锤 `TypeError: missing 1 required positional argument: 'records'`。

**修复**（三选一）：
1. 删掉 `/api/cost` 端点（前端没调它）；
2. 在 `client.py` 恢复模块级累计账本（但这违背你删它的本意）；
3. 改为返回最近一次生成的花费。

**补测试**：`tests/` 目前**完全没有** cost 相关测试，这是它活下来的原因。

---

### 🟠 P1-3 · `_cost_records` 潜伏 NameError — ✅ 已修复
**文件**：`backend/app/llm/client.py:91`、`:192`

删了 `_cost_records` 定义但留了 `else: _cost_records.append(entry)` 分支。当前生产路径 `session_records` 恒非 None（main.py 每连接建账本 → orchestrator ctx 种入 → supervisor 逐层下传），**现在不炸**，但任何调用方忘传 → NameError → `chat()` 内部重试 3 次（白烧 token）→ 调用失败。

**修复**：删掉两个 `else` 分支（`session_records` 已是必传语义）；或在函数入口 `session_records = session_records or []`。

---

### 🟠 P1-4 · `X-Forwarded-For` 伪造 → 限流绕过（公网核心防线） — ✅ 已修复
**文件**：`backend/app/main.py:178-184`

无条件信任客户端可控制的 XFF 头第一段。客户端发 `X-Forwarded-For: 任意IP` 就能换 IP，绕过 **1 次/IP/日** 试用限制和日预算帽。**公网上线前必须堵**。

**修复**：
- 只在可信反向代理（Caddy）后信任 XFF；无代理直连场景直接忽略；
- 取最后一个可信跳的 IP 而非第一个；
- Caddy 侧配置 `trusted_proxies` / 正确的 XFF 改写。

---

### 🟡 P2-5 · LLM 决策的 `params` 被整套工具链丢弃
**文件**：`orchestrator.py:353-371` → `supervisor.py:46-68`

`_execute_tool` 收了 `params` 但不传 `dispatch`；`dispatch` 也没有 params 参数。系统提示里跟 LLM 吹的 `search(query, reason)` 契约是假的——实际搜索永远用 `ctx["user_input"]`，换词重搜只能用 ResearcherAgent 硬编码的 `_ALT_ANGLES`。

**修复**：`dispatch` 增加 `params` 透传，至少让 search 用 LLM 给的 query。

---

### 🟡 P2-6 · `record_cost` 无锁 get-then-set 竞态
**文件**：`backend/app/network/rate_limiter.py:68-73`

并发完成两个生成（上限 20 连接）→ 各读各写 → 丢一次花费记录 → 日预算帽低估。切 Redis 后同样存在。

**修复**：StateBackend 加 float 原子自增（Redis `INCRBYFLOAT`）；或记录时加锁。预算若要在途精确，应在**准入时预留**而不是事后记录（TOCTOU 根治）。

---

### 🟡 P2-7 · `rate_limiter.stats` 是硬编码假数据
**文件**：`backend/app/network/rate_limiter.py:34-37`

永远返回 `daily_spent: 0.0`（注释自认"测试用"）。`/api/rate-limit` 对外返回永远错误的数据。前端目前没消费它，但留着是坑。

**修复**：从 StateBackend 读真实值；或删掉该端点。

---

### 🟡 P2-8 · Redis 宕机 → fail-open，限流静默失效
**文件**：`backend/app/state/redis.py:20-50`

所有方法吞异常返回 `None`/`0` → 日预算帽、IP 试用帽全开。安全上应 fail-closed。

**修复**：可用性降级时至少打告警 + 暴露 `redis_available` 指标；或返回 503。

---

### 🟡 P2-9 · `force_strategy_change` 是死 flag
**文件**：`context.py:33`（定义）、`orchestrator.py:309`（读取）——**全库无人写它**。

**修复**：在"同一工具连续 3 次失败"处写 `ctx["force_strategy_change"] = True`；或删掉这个 flag 和提示。

---

### 🟢 P3 · 低优先级
| 项 | 位置 | 说明 |
|----|------|------|
| `issues[:3]→[:99]` | main.py:360 | 修复 P0-1 后建议恢复小上限（5~8 条），否则失败消息超长 |
| `LLM_TOKENS` 死指标 | metrics.py:24 | 定义了但从未 `.inc()`，面板永远 0 |
| heartbeat task 不 await | orchestrator.py:176-182 | 可能出 "Task was destroyed" 警告；60s 后停跳，长 render 前端无心跳 |
| `TOOL_COST` 缺 compose 键 | tools/__init__.py:19 | compose 走默认 0.05，预算口径不一致 |

---

## 二、整理清理计划（第一性原理）

**原则**：根目录只留标准文件（README/LICENSE/.gitignore/CLAUDE.md/Caddyfile）；生成物不进库；个人复习文件不进库；死代码直接删；单一事实来源。

### L1 · 死代码（已确认 0 引用，可直接删） — ✅ 已全部删除
| 文件 | 引用验证 |
|------|---------|
| `backend/app/core/exceptions.py` | 0 引用（docstring 描述的实现不存在——main.py 用的是字符串匹配的 `_friendly_error`） |
| `backend/app/core/idempotency.py` | 0 引用 |
| `backend/app/agents/context.py` | 0 引用（"未来切 LangGraph"——决策已是不用 LangGraph，是死愿景） |
| `backend/app/schemas/websocket.py` | 0 外部引用（仅自引用 docstring）；删后 `schemas/` 包也空了，一起删 |
| `TOOL_MAP`（tools/__init__.py:13-24） | 0 引用；与 supervisor 的 `TOOL_HANDLERS` 重复且签名过时 |
| `MessageBus.broadcast`（message_bus.py:56-60） | 0 引用 |

### L2 · 根目录复习文件（你的学习材料） — ✅ 已移到 `docs/archive/`（gitignored）
现状：已全部被 `.gitignore` 覆盖，**不进 git**，但物理上堆在根目录，违反"根目录只留标准文件"。
- `BRIEFING.md/.pdf`、`STRUCTURE.md/.pdf`、`CODE_MAP.md/.pdf`、`RELATIONS.md/.pdf`、`FULL_TRACE.md/.pdf`
- 截图：`agent-activity.png` `clean-output.png` `final-test.png` `final-test2.png` `success.png`
- `.coverage`（测试产物，可删）

**建议**：移到 gitignored 的 `docs/archive/` 子目录（或仓库外），根目录回归干净。

### L3 · 可再生产物（可选清理，不阻塞）
| 目录 | 大小 | 说明 |
|------|------|------|
| `venv/` | 1.4G | 运行依赖，CLAUDE.md 的启动命令引用它，**保留** |
| `frontend/dist` | 225M | 构建产物，`npm run build` 可再生成 |
| `frontend/node_modules` | 101M | 依赖，`npm install` 可再生成 |
| `backend/chroma_data/` | 少量 | 向量库，启动时从 JSON 重建 |
| `backend/logs/detail.log.2026-08-08` | 少量 | 轮转旧日志，可删（保留 30 天策略会自动处理） |

### L4 · 结构性改进（提案，不急）
1. **Demo 话题双源**：`demo.py` 的 `DEMO_TOPICS` 与前端 `App.jsx` 注释写着"保持同步"。单一事实来源 → 前端从 `/api/demos` 或 `/api/events` 拉取。
2. **包初始化不一致**：`agents/` `schemas/` `state/` `tools/` 有 `__init__.py`，但 `core/` `knowledge/` `llm/` `network/` 没有（靠 namespace package 跑通）。统一补上。
3. **`.gitignore` 残留条目**：`lithos-replica/` `frontend-demo/` `frontend-demo-v2/` `project-source-full.txt` `gen_kb.py` `skills-lock.json` `*.fname*` 指向的文件**都不存在**，可清理。— ✅ 已清理

---

## 三、执行顺序与验证

1. **P0-1 + P0-2 + P1-3**（3 个文件的小改动）→ `pytest tests/ -v` 57 全绿 → 补 2 个回归测试（issues 类型、cost 调用）
2. **L1 死代码删除** → 再跑 `pytest tests/ -v`（确认没删错）
3. **P1-4 XFF**（上公网前必须）
4. **P2 各项**（按时间排）
5. **L2 复习文件**（等你决定后执行）
6. **L4**（有空再说）

> 规则提醒：根目录不建新 `.md`；新文档进 `docs/`。本文件就在 `docs/`，符合。
