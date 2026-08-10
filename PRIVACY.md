# 隐私声明

> 最后更新：2026-08-08
> 项目：时光像素（AI-Native Workflow）

## 数据收集范围

我们收集以下数据以提供服务：

| 数据类型 | 具体内容 | 用途 |
|---------|---------|------|
| 用户输入 | 搜索框中输入的主题（如"秦始皇修长城"）| 发送给 AI 模型生成 HTML 页面 |
| 自动日志 | IP 地址、请求时间、session ID、LLM token 消耗量 | 限流、成本控制、故障排查 |
| 生成内容 | AI 生成的 HTML 页面内容（仅内存展示，**不持久化**） | 请求结束后即丢弃，不用于其他目的 |

## 不收集的数据

- 不设置 Cookie
- 不使用第三方追踪脚本（Google Analytics 等）
- 不要求用户注册或提供个人信息
- 不存储浏览器指纹

## 第三方共享

| 第三方 | 共享数据 | 目的 | 隐私政策 |
|--------|---------|------|---------|
| DeepSeek | 用户输入的主题 | AI 文本/HTML 生成 | https://platform.deepseek.com/privacy |
| Tavily | 搜索关键词 | 网页搜索 | https://tavily.com/privacy |

**注意**：DeepSeek 和 Tavily 的隐私政策独立于本项目。请查阅其各自政策了解数据处理方式。

## 数据存储与保留

| 数据 | 存储位置 | 保留期限 |
|------|---------|---------|
| 日志文件（含 IP、主题、LLM token）| `backend/logs/detail.log` | 30 天（每天午夜轮转，`TimedRotatingFileHandler`，保留 30 个备份） |
| 生成的 HTML | 服务端内存（不持久化）| 请求结束后丢弃 |
| Demo 页面 HTML | `backend/demos/` | 手动管理 |
| 限流计数器 | 内存（MemoryBackend）或 Redis（`STATE_BACKEND=redis`） | 按日期键（`rate:{ip}:{日期}`）自然过期 |

## 用户权利

根据适用的数据保护法律，您有以下权利：

- **访问权**：请求查看与您的 IP 关联的日志记录
- **删除权**：请求删除与您的 IP 关联的日志记录
- **知情权**：了解您的数据如何被使用

如需行使上述权利，请联系：
- 邮箱：`<TODO: 替换为真实可回复邮箱>`（`users.noreply.github.com` 是退信地址，无法兑现访问权/删除权承诺）
- 响应时间：30 天内

## 安全措施

- 日志不包含 DeepSeek API Key
- API Key 通过环境变量注入，不写入代码
- 公网访问建议使用 HTTPS（wss://）加密传输

## 协议变更

本隐私声明可能随时更新。更新后将在项目 README 中注明最后更新日期。

## 联系

如有隐私相关问题，请联系：`<TODO: 替换为真实可回复邮箱>`

---

## GDPR 合规检查清单

> 本项目面向全球用户公开访问，需满足 GDPR 基本要求。

| # | 要求 | 当前状态 | 行动 |
|---|------|---------|------|
| 1 | 数据最小化 | ✅ 仅收集 IP、输入主题、LLM token | — |
| 2 | 目的限制 | ✅ 仅用于生成 HTML 和成本控制 | — |
| 3 | 存储限制 | ✅ 30 天自动清除（TimedRotatingFileHandler） | — |
| 4 | 用户知情权 | ✅ PRIVACY.md 说明数据收集范围 | — |
| 5 | 用户访问权 | ⚠️ 需手工查询日志 | P2：加 `/api/privacy/request` 端点 |
| 6 | 用户删除权 | ⚠️ 需手工清理日志 | P2：加 `/api/privacy/delete` 端点 |
| 7 | 数据可移植性 | ✅ 无用户账户系统，无持久化用户数据 | — |
| 8 | 数据保护官（DPO）| N/A ——个人项目，非企业 | — |
| 9 | 数据泄露通知 | ⚠️ 无自动化检测 | 依赖 GitHub Security Advisories |
| 10 | 第三方数据处理协议 | ⚠️ DeepSeek/Tavily 的 DPA 未签署 | 个人项目可接受 |
| 11 | Cookie 同意 | ✅ 不使用 Cookie | — |
| 12 | 儿童数据保护 | ⚠️ 无年龄验证 | 加使用条款声明 13 岁以下禁用 |

---

## 开源依赖协议兼容性

| 依赖 | 协议 | 是否兼容 MIT | 说明 |
|------|------|-------------|------|
| FastAPI | MIT | ✅ | 完全兼容 |
| uvicorn | BSD-3 | ✅ | 与 MIT 兼容 |
| openai | Apache-2.0 | ✅ | 与 MIT 兼容（专利授权条款独立） |
| python-dotenv | BSD-3 | ✅ | 完全兼容 |
| playwright | Apache-2.0 | ✅ | 与 MIT 兼容 |
| pydantic-settings | MIT | ✅ | 完全兼容 |
| prometheus-client | Apache-2.0 | ✅ | 与 MIT 兼容 |
| httpx | BSD-3 | ✅ | 完全兼容 |
| redis | MIT | ✅ | 完全兼容 |
| React | MIT | ✅ | 完全兼容 |
| Vite | MIT | ✅ | 完全兼容 |
| Tailwind CSS | MIT | ✅ | 完全兼容 |
| framer-motion | MIT | ✅ | 完全兼容 |
| lucide-react | ISC | ✅ | ISC 与 MIT 等效，完全兼容 |
| ChromaDB | Apache-2.0 | ✅ | 与 MIT 兼容 |

**结论**：所有依赖均与 MIT 协议兼容，无冲突。Apache-2.0 的专利授权条款是附加保护，不影响 MIT 项目。
