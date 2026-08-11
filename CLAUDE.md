# AI-Native Workflow · 时光像素

> 最后更新：2026-08-11
> 当前阶段：Phase 1-5 + 产品化重构完成（多轮迭代/记忆/评测/REST API），94 tests，前端已重构（Sidebar+迭代条+三面板）

## 项目是什么

一个 AI 原生系统。输入任意主题 → LLM 自己决定流程（搜几次、用什么形式、失败了退回哪步）→ 生成交互式 HTML 页面。**流程是 LLM 自己决定的，不被人写死。**

## 我是谁

朱子钦，衡水学院 2026 届应届生，秋招主攻 AI 应用工程岗。

## 技术栈

| 层 | 选型 | 原因 |
|----|------|------|
| LLM | DeepSeek API (deepseek-chat) | 便宜、中文好、OpenAI SDK 兼容 |
| 编排 | 自研 async while 循环（不是 LangGraph） | LLM 自主决策、全异步 |
| Web | FastAPI + WebSocket | 实时推送思考过程 |
| 前端 | React 18 + Vite 5 + Tailwind 3 | 液态玻璃 + 光标聚光灯 |
| 搜索 | Tavily（零配置） | 国内可直连，不配 Key 也能跑 |
| 验证 | Playwright 无头浏览器 | 真执行，不靠猜 |
| 向量 | ChromaDB + text2vec-base-chinese | "嬴政"→"秦始皇"语义匹配 |
| 指标 | Prometheus（9 个指标） | /metrics 端点 |
| 部署 | Docker Compose + Caddy | 自动 HTTPS |
| Python | venv Python 3.13 | 系统 3.8 不兼容 |

## 架构

```
用户输入 → RateLimiter → Orchestrator async while 循环
              │
              ├── _decide() → LLM 自主决策每一步
              │
              ├── search   Tavily + KB 关键词 + ChromaDB 向量检索
              ├── design   选叙事形式（7 种组件可选）
              ├── compose  写文案 + 来源标注 + 可信度
              ├── render   RenderAgent（自检 + 缓存 + 重试）
              └── verify   Playwright 真执行 + 硬规则 + 事实核查
              ↓
         交互式 HTML 页面
```

**硬边界**：20 步、¥1 预算、搜 ≤8 次、render 后必须 verify、verify 失败强制回退、素材不足诚实模式、搜索死循环防护。

## 目录结构

```
backend/app/
├── main.py                     🚪 FastAPI + WebSocket 入口
├── demo.py                     📦 Demo 页面管理
├── core/                       🧱 config / metrics / trace / projects / preferences / eval_report
├── llm/                        🤖 client / parser / circuit_breaker
├── network/                    🌐 ws_manager / rate_limiter
├── tools/                      🔧 search / design / compose / render / verify
├── agents/                     🧠 orchestrator（含 refine 多轮） / supervisor / message_bus / researcher / designer / render / evaluate
├── knowledge/                  📚 kb / vector_store
└── state/                      💾 base / memory / redis（STATE_BACKEND 一行切换）

backend/scripts/                📊 eval_run.py（端到端评测脚本）

frontend/src/
├── App.jsx                     主布局（液态玻璃 + 光标聚光灯）
├── components/
│   ├── DecisionLog.tsx         AI 思考流程（5 步进度线）
│   ├── StoryPanel.tsx          生成页面（流式渲染 + 显影动画）
│   ├── RevealLayer.tsx         光标聚光灯 Canvas mask
│   ├── SearchBubble.tsx        搜索输入框
│   ├── EventTags.tsx           169 个示例话题标签云
│   ├── FailureNotice.tsx       失败提示 + demo 引导
│   └── ErrorBoundary.tsx       React 错误边界
└── hooks/useWebSocket.js       WebSocket + 断线重连 + 流式接收
```

## 关键设计决策

1. 不用 LangGraph——async while 循环 + LLM 决策，当前规模不需要状态图
2. 3 Agent 架构——Researcher（搜索）Designer（设计+文案）Render（自检+缓存），每个有内部决策循环
3. 审查外置——Playwright 真执行 + 硬规则 + 事实核查，不是 LLM 猜对错
4. 诚实模式——素材不足自动降级，标注"资料有限"，不编造
5. 搜索死循环防护——ResearcherAgent 内部处理（换词重试 + 向量兜底 + 自动停止）
6. 断路器——连续 3 次 LLM 失败熔断 30s，防级联故障
7. 预算双控——虚拟 ¥1/次 + 真实 ¥5/天，公网不破产
8. DecisionLog 是核心产品——AI 思考过程全透明
9. 流式渲染——contentDocument.write 不频闪
10. 消息总线——asyncio.Queue 基础设施；状态后端 memory/redis 可切换（RedisBackend 已实现）

## 当前状态

- ✅ 架构分层完毕（7 目录，单向依赖，无循环）
- ✅ Phase 1-5 完成：ResearcherAgent + DesignerAgent + RenderAgent + MessageBus + RedisBackend
- ✅ 产品化重构（2026-08-11）：结构化输出 / 真实预算 / 注入防御 / trace 落盘 / 历史持久化 / 偏好记忆 / 多轮迭代 refine / eval 评测 / REST API / 前端 Sidebar+迭代条+三面板
- ✅ 安全加固（输入长度限制 + IP 连接限制 + 日志 30 天 + WS断开取消任务 + XFF 防伪造 + 注入检测）
- ✅ 合规补全（LICENSE MIT + PRIVACY GDPR + SECURITY STRIDE）
- ✅ 94 tests 全绿（66 → 94，新增 Phase A-E 回归）
- 📋 说明：`docs/plans/refactor-master-plan.md` 是重构主计划，Phase A-F 已全部完成

## 运行

```bash
# 后端
cd backend && ..\venv\Scripts\python -m uvicorn app.main:app --port 8001

# 前端
cd frontend && npm run dev
```

## GitHub

https://github.com/hfujw/ai-native-workflow



## 规则

**回答我的时候：**

先叫我威风的龙，再回答问题

**改代码前：**

- 先 Read 目标文件确认当前内容——别靠对话记忆，文件可能已经变了
- 没读过的文件，必须先读再改

**改代码后：**
- 每次改动完立刻跑 `pytest tests/ -v`，62 tests 必须全绿
- tests 挂了就停手，修好再继续

**Push 前：**
- 必须检查 `.gitignore`
- 检查 `git status`——有没有不该进仓库的文件
- 永远不要提交：`BRIEFING.md` `STRUCTURE.md`（本地复习用）

**文件管理：**
- 新文档放 `docs/`，别在根目录建 `.md`
- 需要总结/复习时产生的临时文件，事后清理或放进 `.gitignore`
- 根目录只留 GitHub 标准文件 + Claude Code 要求的
- 发现死代码 → 直接删

**项目习惯：**
- 觉得我忽略了某个文件或规则，直接指出来
- 不会的问问，不要猜
- 目录要分组，别平铺十几个文件
