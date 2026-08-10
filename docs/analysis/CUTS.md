# 减法记录

> 项目完工后回看——哪些提议被裁掉了、为什么、如果捡回来要怎么做。

---

## 第一轮裁项（v1→v2 时）

### 1. OpenTelemetry + Jaeger + Prometheus 全家桶

**裁掉原因**：面 AI 应用工程不是面 SRE。结构化日志 + `/metrics` 端点足够。
**替代方案**：log 行统一 `key=value` 格式 + 3 Counter + 1 Histogram。
**捡回来时机**：多实例部署、独立运维团队。

### 2. Pydantic-Settings 多环境分层

**裁掉原因**：只部署一次，不需要 dev/staging/prod 三套。
**替代方案**：v3 采纳了 pydantic-settings 单例模式，一个 dataclass 够用。
**捡回来时机**：v3 已解决。

### 3. pytest-docker 起依赖服务

**裁掉原因**：项目无外部依赖（无 Redis/Postgres）。mock LLM 够用。
**替代方案**：契约测试用预录 fixture + mock LLM。
**捡回来时机**：接有状态依赖后。

### 4. 一致性校验（问 LLM 两次对比答案）

**裁掉原因**：一次生成 ¥0.10，两次翻倍。外置规则引擎更可靠。
**替代方案**：`_evaluate_material()` 非 LLM 判定。
**捡回来时机**：预算充足 + 模型有 confidence API。

### 5. JWT 认证

**裁掉原因**：公开展示 demo，加登录 = 面试官打不开。
**替代方案**：IP 限流 + ¥5 日预算 + 1次/天 试用。
**捡回来时机**：要收费或有用户系统。

### 6. 前端 SSR/SSG

**裁掉原因**：6 个组件，Vite build < 200KB，首屏 < 1s。
**替代方案**：SPA + Vite。
**捡回来时机**：SEO 需求。

---

## 第二轮裁项（kimi 反馈后）

### 7. Redis 完整接入

**裁掉原因**：日均 < 50 用户，MemoryBackend 够。接口已留。
**替代方案**：`StateBackend` 抽象 + `MemoryBackend`（4 方法）。Redis 改一行配置。
**捡回来时机**：多 worker 部署、日活 > 500。

### 8. Prometheus + Grafana + PagerDuty

**裁掉原因**：一个 `/metrics` + 4 个指标够讲故事。
**替代方案**：`/metrics` 端点，面试时"扩展只需加 label"。
**捡回来时机**：如有独立运维。

### 9. CI 里 pyright 类型检查

**裁掉原因**：当前代码几乎无 type hint，一跑就炸。
**替代方案**：CI 只做 `ruff check` + `pytest --cov`。
**捡回来时机**：核心模块补完 type hint。

### 10. StateBackend 11 方法接口

**裁掉原因**：只用 `get/set/incr/expire`，Hash/Lock 暂时不需要。
**替代方案**：4 方法接口。需要时再加。
**捡回来时机**：会话管理、分布式锁。

---

## 第三轮（执行中发现并裁掉的）

### 11. `playwright install --with-deps` 多阶段 Docker

**裁掉原因**：系统依赖无法通过 `COPY` 传递，运行时报 `libxxx.so`。
**替代方案**：单阶段 `mcr.microsoft.com/playwright/python:v1.45.0-jammy` 官方镜像。
**捡回来时机**：已修。

### 12. 流式 `_decide()`（JSON 流式）

**裁掉原因**：JSON 流式解析复杂度极高，`_decide` 输出只有几百字符，收益极小。
**替代方案**：只做 `tool_render()` HTML 流式。面试时说"基于 ROI 评估"。
**捡回来时机**：模型支持 structured output streaming。

### 13. 启动时发真实 LLM 请求做健康检查

**裁掉原因**：冷启动慢 + API 抖动导致服务起不来 + 消耗 Token。
**替代方案**：启动只做本地校验（Config + Playwright 文件 + demo 目录）。
**捡回来时机**：不捡。

---

## 总结

| 裁掉 | 替代 | 什么时候捡 |
|------|------|-----------|
| OTEL + Prometheus 全家桶 | 结构化日志 + /metrics | 多实例部署 |
| pytest-docker | mock LLM 响应 | 接有状态依赖 |
| 一致性校验 | 外置规则引擎 | 预算充足 |
| JWT 认证 | IP 限流 + 预算帽 | 要收费 |
| SSR/SSG | SPA + Vite | SEO 需求 |
| Redis 接入 | MemoryBackend + 接口预留 | 日活 > 500 |
| Prometheus 全家桶 | 4 指标 /metrics | 独立运维 |
| pyright CI | ruff 够用 | 补完 type hint |
| 11 方法 StateBackend | 4 方法 | 需要复杂数据结构 |
| JSON 流式 _decide | HTML 流式 render | structured output API |
