# 全量对抗性检查记录 · 2026-08-11

> 范围：全项目（后端 + 前端）逐模块挑刺，按第一性原理修复。
> 结果：94 tests 全绿 + ruff 干净。

---

## 发现并修复的问题

### 🔴 真 Bug（会导致失败/浪费/安全）

| # | 问题 | 修复 |
|---|------|------|
| A1 | `get_cost_summary` 用 `r["input_tokens"]` 不安全访问——账本里某条记录缺字段就 KeyError，**导致 render LLM 调用记账阶段崩溃 → 整话题失败**（eval 那 2 个失败的根因） | 改 `.get()` + 缺字段打警告 |
| A2 | **多轮迭代成本不记入日预算**——refine 的 LLM 调用不计入 ¥5/天，可无限白嫖 | 每轮迭代后 `record_cost(delta)` |
| A3 | **迭代无上限**——refine_page 不受 ¥1 会话预算约束，可无限烧 token | 加 `MAX_ITERATIONS=6`（首轮 + 5 次修改） |
| A4 | **连续 20 次重渲染死循环**——系统提示写了"同一工具连续3次失败换策略"但只是提醒，LLM 不听话就死循环 | 硬拦截：连续 3 次 render 失败 → 强制 design |

### 🟡 设计缺陷

| # | 问题 | 修复 |
|---|------|------|
| B1 | 多轮迭代产出**不经过 verify**——违背"render 后必须 verify"原则，迭代版是"未验证"的 | refine 结尾加 tool_verify；有 critical 则带问题重渲染一次 |
| B2 | refine 的 redesign **不传用户偏好**——迭代时偏好失效 | refine_page 加 preferences 参数并透传 |

### 🟢 防御性加固

| # | 问题 | 修复 |
|---|------|------|
| C1 | designer 的 `listener.cancel()` 没 await——"Task was destroyed" 警告 | 加 `await listener`（抑制 CancelledError） |
| C2 | `kb.py` 的 `event["content"]` 若为非 dict（数据变化）→ AttributeError | 加 `isinstance(..., dict)` 守卫 |
| C3 | main.py push 回调直接 `msg["step"]`——消息缺字段就 KeyError | 全部改 `.get()` + 默认值 |
| C4 | 多轮循环里 `refine_page` 抛异常会炸掉整个会话 | 加 try/except，失败提示后继续 |

---

## 评估为"可接受/设计选择"的

- **verify.py**：Playwright 若 `set_content` 抛异常会跳过 `browser.close()`——`async with` 兜底，低风险
- **断路器**：`failure_count` 不按时间衰减（3 次即熔断）——设计选择，防级联优先
- **前端重连 mid-iteration** 会从头重启——minor UX，极少发生
- **DecisionLog 在页面生成后折叠**——迭代思考被折叠，minor UX

---

## 验证

- `pytest tests/ -q` → **94 passed**
- `ruff check app/ tests/ scripts/` → **All checks passed!**
- "Python 装饰器"（修复前失败）→ 修复后 `success | 4 步 | ¥0.0147`

## 遗留（需要用户/后续）

- **重跑 eval** 拿到修复后的真实通过率（README 已标注待更新）
