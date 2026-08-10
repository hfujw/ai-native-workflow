# 安全加固检查清单

> 最后更新：2026-08-08  
> 项目：时光像素（AI-Native Workflow）

---

## STRIDE 威胁建模结果

### 1. Spoofing（伪装）

| 风险 | 当前状态 | 修复 |
|------|---------|------|
| 无用户认证——任何人可访问 WebSocket | ⚠️ 接受风险。项目设计为公开 Demo，加登录会阻止面试官试用 | IP 限流已作为替代方案 |
| X-Forwarded-For 可伪造 | ✅ `TRUST_PROXY` 门控（默认关闭）+ 取 XFF **最后一个** IP（Caddy 追加的真实客户端 IP），客户端伪造值被忽略 | 仅 Caddy 反代后开 `TRUST_PROXY=true`（docker-compose 已配） |
| session_id 可预测（uuid4 前 8 位） | ⚠️ 碰撞概率 $2^{-32}$，单机场景可接受 | 未来多 worker → 完整 UUID |

### 2. Tampering（篡改）

| 风险 | 当前状态 | 修复 |
|------|---------|------|
| WebSocket 消息明文传输 | ⚠️ 开发环境 ws:// | 生产：wss://（TLS 加密），nginx/Caddy 反代 |
| 无消息签名 | ⚠️ 当前 WebSocket 消息无签名验证 | 公网 Demo 可接受；如需防注入，加 HMAC 签名 |
| 生成的 HTML 可能被中间人注入 | ⚠️ 同 TLS | wss:// 解决传输层 |

### 3. Repudiation（抵赖）

| 风险 | 当前状态 | 修复 |
|------|---------|------|
| 无操作审计日志 | ⚠️ 当前日志含 session_id + IP + topic | ✅ 基本可追溯 |
| 用户生成违规内容后无追责 | ⚠️ 日志记录 topic 和 HTML 内容 | 保留 30 天日志用于追溯 |
| 无删除用户数据的 API | ❌ 缺失 | 加 `/api/privacy/delete` 端点（手工处理） |

### 4. Information Disclosure（信息泄露）

| 风险 | 当前状态 | 修复 |
|------|---------|------|
| .env 文件暴露结构 | ✅ `.env` 在 `.gitignore` | `.env.example` 已清理关键字段 |
| 日志记录用户输入（topic）| ⚠️ `logger.info("新请求 | topic=%s")` | 接受——需要用于排查 |
| 错误信息泄露堆栈 | ✅ `_friendly_error` 映射到用户友好信息 | 不暴露技术细节 |
| API Key 直接可读 | ⚠️ 任何能 SSH 的人都能读 `.env` | 生产用 Docker secrets / 环境变量 |
| `/api/cost` 暴露 API 消耗 | ✅ 已删除（2026-08-11，无全局账本，成本统计走 Prometheus） | — |
| `/metrics` 暴露 Prometheus | ✅ Caddy 已限制内网 IP（见 Caddyfile `handle /metrics`） | — |

### 5. Denial of Service（拒绝服务）

| 风险 | 当前状态 | 修复 |
|------|---------|------|
| 无输入长度限制 | ✅ `max_length=500` | 已就位 |
| WebSocket 连接数限制 | ✅ 20 上限 + 踢旧连接 | 已就位 |
| 单 IP 多连接 | ✅ `max_connections_per_ip=3` | 已就位 |
| LLM 调用超时 | ✅ 120s 全局超时 | 已就位 |
| 断路器 | ✅ 3 次失败熔断 30s | 已就位 |
| 慢速 WebSocket 攻击（slow send）| ✅ WS 断开自动取消 LLM 任务 | receive 有 30s 超时 + orch_task.cancel() |
| ReDoS 正则攻击 | ✅ 无用户可控正则 | `_strip_fence` 的正则是常量，无风险 |
| 日预算帽 | ✅ ¥5/天 | 已就位 |

### 6. Elevation of Privilege（提权）

| 风险 | 当前状态 | 修复 |
|------|---------|------|
| 无 admin 接口 | ✅ 无认证体系 → 无提权风险 | — |
| `/metrics` 端点 | ✅ Caddy 已限内网 IP（仅 127.0.0.1/内网段可访问） | — |
| `/api/cost` 端点 | ✅ 已删除 | — |

---

## 安全修复清单（按优先级）

### P0 - 立即修复（上线前必备）

- [x] **输入长度限制**：`main.py` `user_input` 加 `max_length=500`
- [x] **日志脱敏**：API Key 在任何日志中不出现（已实现——Key 只在 config.py 内存中）
- [x] **WS 断开取消任务**：用户断开 WebSocket → `orch_task.cancel()` 停止 LLM 调用
- [ ] **生产环境 CORS 收紧**：上线时 `allow_origins` 改为具体域名
- [ ] **HTTPS 强制**：生产环境 Nginx/Caddy 301 重定向 HTTP → HTTPS

### P1 - 本周修复

- [x] **WebSocket 单 IP 连接数限制**：防止同一 IP 占满 20 个连接
- [x] **slow send 攻击防护**：WS 断开自动取消 LLM 任务
- [x] **日志保留策略**：30 天自动清理（TimedRotatingFileHandler）
- [x] **LICENSE 文件**：MIT 标准文本
- [x] **PRIVACY.md**：数据收集说明
- [x] **`/metrics` 端点加 IP 白名单**（Caddyfile 已实现——仅内网 IP 可访问）

### P2 - 排期

- [x] **`/api/cost` 已删除**（2026-08-11）
- [ ] **完整 UUID 替代 8 位前缀**
- [ ] **用户数据删除端点**

---

## 依赖安全

定期运行 `pip list --outdated` 检查过期依赖。

关键依赖安全策略：
- `openai`：通过环境变量管理 Key，不硬编码
- `playwright`：Docker 镜像已锁定版本 `v1.45.0-jammy`
- `fastapi`：保持最新补丁版本

---

## 报告漏洞

如发现安全漏洞，请邮件至：`<TODO: 替换为真实可回复邮箱>`（注意：`users.noreply.github.com` 是退信地址，不能用于安全联系）

响应时间：72 小时内确认，30 天内修复。
