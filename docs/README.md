# docs/ 文档索引

> 组织原则：按**生命周期**分目录，不按主题平铺。
>
> | 目录 | 含义 |
> |------|------|
> | `plans/` | **未来向**——项目下一步要做什么 |
> | `analysis/` | **当前事实**——现状诊断、设计决策、性能剖析 |
> | `records/` | **历史**——已完成工作的记录、审计、修复 |
> | `deployment/` | **部署运维** |
> | `archive/` | 本地复习文件（gitignored，不进 git） |

## plans/ —— 规划

| 文档 | 说明 | 状态 |
|------|------|------|
| [multi-agent-full-roadmap.md](plans/multi-agent-full-roadmap.md) | Agent 架构演化全景（Phase 1-5） | ✅ Phase 1-5 已完成，Redis 已实现 |
| [phase6-interview-plan.md](plans/phase6-interview-plan.md) | 面试竞争力升级计划（4 缺口 + 执行顺序） | 📋 当前主线，待拍板执行 |

## analysis/ —— 分析

| 文档 | 说明 | 状态 |
|------|------|------|
| [CUTS.md](analysis/CUTS.md) | 减法记录——裁掉的功能 + 理由 + 捡回时机 | ✅ 有效 |
| [data-layer-diagnosis.md](analysis/data-layer-diagnosis.md) | 数据层诊断 | ⚠️ 写于 08-08，"StateBackend 闲置"已过时（限流器已接入 StateBackend，且新增 RedisBackend） |
| [observability.md](analysis/observability.md) | 可观测性现状 + 目标 | ⚠️ `llm_tokens_total` 指标已删（从未埋点）；引用的 `grafana-dashboard.json` 不存在；OTel 目标与 CUTS.md 的"裁掉 OTel"决策冲突 |
| [performance-analysis.md](analysis/performance-analysis.md) | 性能剖析 | ⚠️ `_successful_trials` 字典已重构为 StateBackend（rate_limiter 用 `state.incr`） |

## records/ —— 历史记录

| 文档 | 说明 |
|------|------|
| [UPGRADE_PLAN.md](records/UPGRADE_PLAN.md) | v4.0 工程化升级完工记录（21 tests 时代） |
| [multi-agent-phase1-render.md](records/multi-agent-phase1-render.md) | Phase 1 Render Agent 设计稿（已落地） |
| [fix-suggestions-2026-08-11.md](records/fix-suggestions-2026-08-11.md) | 对抗性审查 + 修复记录（P0/P1 已修复，62 tests） |

## deployment/ —— 部署

| 文档 | 说明 |
|------|------|
| [deployment-plan.md](deployment/deployment-plan.md) | 生产部署方案（Caddy + Docker Compose + GH Actions） |

## 规则

- 新文档按生命周期放对应目录，**别在 docs/ 根目录平铺** `.md`
- 系统当前状态的**唯一事实来源**是根目录 `CLAUDE.md`；本目录文档是设计 / 分析 / 记录，可能有历史偏差（见上表 ⚠️）
- 发现文档与代码不符 → 在索引的"状态"列标注，别偷偷改历史文档
