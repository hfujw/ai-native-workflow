# Claude Code 技能清单（85 个）

> 2026-08-11 整理 · 按功能域分组 · `(推测)` = 根据名字推断，非官方描述
> 用途：面试讲工具链、清理冗余、看清工作流

---

## 一、开发方法论（superpowers-deepseek-v4 插件 · 19 个）

| 技能 | 功能 / 何时用 |
|------|-------------|
| `using-superpowers` | 技能系统总入口。任何会话开始时先用，建立技能使用方式 |
| `brainstorming` | 需求头脑风暴：把模糊想法拆成可落地需求。**接到不明确的任务时用** |
| `resume-brainstorming` | 续上次没做完的头脑风暴 |
| `writing-plans` | 把需求写成带验收标准的分步实施计划。**动手写代码前用** |
| `resume-planning` | 续上次没写完的计划 |
| `executing-plans` | 按计划逐步执行，每步验证。**开始实现时用** |
| `test-driven-development` | TDD：先写测试再写实现。**有明确行为的改动用** |
| `subagent-driven-development` | 派子 agent 分担实现任务，自己主导 |
| `dispatching-parallel-agents` | 并行派发多个子 agent 干独立任务。**几个互不依赖的活一起干时用** |
| `systematic-debugging` | 系统化排错：先假设再验证，不瞎试。**遇到难缠 bug 用** |
| `multi-reviewer` | 多视角评审（代码/设计/性能等）。**重要改动交付前用** |
| `requesting-code-review` | 主动请求代码评审 |
| `receiving-code-review` | 接收评审意见并消化 |
| `verification-before-completion` | 声称"完成"前先验证真的能用。**收尾时用** |
| `writing-skills` | 写新的 Claude Code 技能 |
| `using-git-worktrees` | 用 git worktree 隔离开发 |
| `confirming-worktree-before-edit` | 编辑前确认是否开 worktree（会话级门禁） |
| `finishing-a-development-branch` | 收尾开发分支（合并/清理） |
| `managing-samples` | 管理示例/样本 |

## 二、规划与规格（9 个）

| 技能 | 功能 / 何时用 |
|------|-------------|
| `spec` | 写规格文档 |
| `planning-with-files` | 把计划写到文件里管理 |
| `autoplan` | 自动生成实施计划。**任务复杂不确定怎么拆时用** |
| `plan-tune` | 微调计划（推测：调整计划细节） |
| `plan-ceo-review` | 从"老板/业务"视角评审计划 |
| `plan-design-review` | 从"设计"视角评审计划 |
| `plan-devex-review` | 从"开发者体验"视角评审计划 |
| `plan-eng-review` | 从"工程"视角评审计划 |
| `office-hours` | 办公时间（推测：定时/例行检查） |

## 三、设计与 UI（10 个）

| 技能 | 功能 / 何时用 |
|------|-------------|
| `design` | 设计系统/方案入口 |
| `design-consultation` | 设计咨询（推测：问答式设计建议） |
| `design-review` | 设计评审。**视觉产出交付前用** |
| `design-system` | 设计系统（推测：维护设计规范） |
| `design-shotgun` | 快速出多版设计方向（推测） |
| `design-html` | 生成生产级 HTML/CSS 落地页（gstack） |
| `ui-styling` | UI 样式调整 |
| `ui-ux-pro-max` | 深度 UI/UX 优化 |
| `brand` | 品牌设计 |
| `banner-design` | 横幅/banner 设计 |

## 四、落地页 & 产品发布（gstack 生态 · 12 个）

| 技能 | 功能 / 何时用 |
|------|-------------|
| `gstack` | gstack 主命令入口 |
| `gstack-upgrade` | 升级 gstack 插件 |
| `_gstack-command` | gstack 内部命令（推测：底层） |
| `land-and-deploy` | 生成落地页 + 部署 |
| `landing-report` | 落地页报告（推测：效果/状态报告） |
| `setup-deploy` | 配置部署环境 |
| `ship` | 发布产品 |
| `open-gstack-browser` | 打开浏览器预览 |
| `context-save` | 保存当前工作上下文 |
| `context-restore` | 恢复之前保存的上下文 |
| `setup-gbrain` | 配置 gbrain（推测：gstack 的知识库/大脑） |
| `sync-gbrain` | 同步 gbrain |

## 五、iOS 开发（5 个）

| 技能 | 功能 / 何时用 |
|------|-------------|
| `ios-fix` | 修 iOS 代码问题 |
| `ios-clean` | 清理 iOS 项目 |
| `ios-qa` | iOS 质量检查 |
| `ios-design-review` | iOS 设计评审 |
| `ios-sync` | iOS 同步（推测） |

## 六、研究 / 内容 / 文档（10 个）

| 技能 | 功能 / 何时用 |
|------|-------------|
| `deep-research` | 深度研究：多路搜索 + 对抗性验证 + 引用报告。**需要严谨调研时用** |
| `investigate` | 调查/排查（推测） |
| `scrape` | 网页抓取 |
| `learn` | 学习模式（推测） |
| `document-generate` | 生成文档 |
| `document-release` | 发布文档 |
| `make-pdf` | 把内容转 PDF |
| `slides` | 做幻灯片 |
| `pptx` | 做 PPTX |
| `karpathy-guidelines` | 代码规范（Karpathy 风格，推测：LLM 代码简化准则） |

## 七、代码质量 / 审查 / 运维（12 个）

| 技能 | 功能 / 何时用 |
|------|-------------|
| `code-review` | 审查当前 diff 的正确性/复用/简化。**改完代码提交前用** |
| `simplify` | 简化改动代码（只做质量不做 bug 猎杀） |
| `security-review` | 安全审查。**涉及权限/输入/公网的改动用** |
| `review` | 通用评审（推测） |
| `qa` | 质量检查（推测：跑检查项） |
| `qa-only` | 只跑 QA 不修（推测：与 qa 近似） |
| `guard` | 防护/门禁（推测） |
| `canary` | 金丝雀发布（推测：小流量试点） |
| `careful` | 谨慎模式（推测：慢但稳） |
| `benchmark` | 基准测试 |
| `benchmark-models` | 模型基准对比（推测） |
| `devex-review` | 开发者体验评审 |
| `health` | 健康检查（推测） |
| `retro` | 复盘（推测：回顾总结） |

## 八、运行 / 验证 / 执行（7 个）

| 技能 | 功能 / 何时用 |
|------|-------------|
| `run` | 启动并运行项目验证。**要看效果/跑起来时用** |
| `verify` | 验证改动真的有效。**改完想确认能跑时用** |
| `loop` | 定时重复执行某个命令。**周期性任务/轮询用** |
| `pair-agent` | 结对 agent（推测：双 agent 协作） |
| `freeze` | 冻结（推测：锁定状态/分支） |
| `unfreeze` | 解冻（与 freeze 配对） |

## 九、浏览器 / MCP / 网络（4 个）

| 技能 | 功能 / 何时用 |
|------|-------------|
| `browse` | 浏览器操作/访问网页 |
| `setup-browser-cookies` | 配置浏览器 cookie（登录态） |
| `mcp-builder` | 构建 MCP 服务器。**想给 Claude 加新工具时用** |
| `codex` | Codex 集成（推测：OpenAI Codex 相关） |

## 十、配置 / 环境 / Claude 管理（8 个）

| 技能 | 功能 / 何时用 |
|------|-------------|
| `update-config` | 改 Claude Code 配置/settings.json。**要加权限/钩子/环境变量时用** |
| `keybindings-help` | 自定义快捷键帮助 |
| `fewer-permission-prompts` | 扫描历史，把常用只读命令加白名单减少弹窗 |
| `claude-md-management:revise-claude-md` | 修订 CLAUDE.md |
| `claude-md-management:claude-md-improver` | 改进 CLAUDE.md（与上一个近似） |
| `skillify` | 把流程变成 skill（推测） |
| `init` | 项目初始化 |
| `claude-api` | 构建 Claude API 应用（缓存/工具/模型迁移） |

## 十一、Agent 开发（agent-sdk-dev 插件 · 2026-08-11 新增）

> Anthropic 官方 "Claude Agent SDK Development Plugin"。用 Claude Agent SDK 开发时用。

| 能力 | 功能 / 何时用 |
|------|-------------|
| `/new-sdk-app [项目名]` | 脚手架：新建一个 Claude Agent SDK 应用（Py/TS），自动读官方文档。**面试前想快速搭个 Agent demo 时用** |
| `agent-sdk-verifier-py` | 子 agent：验证 Python Agent SDK 应用配置是否正确、符合最佳实践、可部署 |
| `agent-sdk-verifier-ts` | 同上，TypeScript 版 |

**注意**：这个插件面向 **Claude Agent SDK**（需要 anthropic SDK + Claude API key），和你项目用的 DeepSeek 不是一回事。但对 **Agent 开发岗面试**很有价值——能快速搭一个"用 Anthropic Agent SDK 写 tool-use + MCP"的 demo。

---

## 重复项分析（建议清理）

| 重复组 | 建议 |
|--------|------|
| `plan-ceo-review` `plan-design-review` `plan-devex-review` `plan-eng-review` | **4 个同一功能不同视角**——留 `plan-eng-review` 或合并成 1 个，其余删 |
| `qa` vs `qa-only` | 几乎重复——留 1 个 |
| `code-review` vs `review` vs `security-review` vs superpowers `multi-reviewer` | 4 个都管"审查"但分工不同：code-review=diff、security-review=安全、multi-reviewer=多视角。`review` 最泛，可删 |
| `claude-md-management:revise-claude-md` vs `claude-md-improver` | 两个都管 CLAUDE.md——留 1 个 |
| `freeze` / `unfreeze` | 配对，但若不用就一起删 |
| `benchmark` vs `benchmark-models` | 近似，按需留 1 |

**2026-08-11 已删 8 个**：`plan-ceo-review` `plan-design-review` `plan-devex-review` `qa-only` `review` `freeze` `unfreeze` `benchmark-models`（`revise-claude-md` 是插件命名空间技能，暂留）。剩余 58 个独立技能。

---

## 是否形成一套体系？

**结论：有强核心，但整体是"插件堆叠"而非"一个体系"。**

**成体系的部分（值得在面试里讲）**：
```
superpowers 方法论闭环：
  brainstorming（想清楚）→ writing-plans（写计划）→ executing-plans（执行）
  → test-driven-development（边写边测）→ code-review/security-review（交付前审）
  → verification-before-completion（验证才算完）
```
这是**一个完整、自洽、可讲的工程流程**——从需求到交付每一步都有对应技能。

**不成体系的部分**：
- 设计域 10 个、iOS 5 个、gstack 12 个——是**垂直场景工具**，和你的 AI/Agent 主线无关，面试讲不上
- 冗余集中在"审查"和"规划"两处（各 4+ 个）
- 缺少：**Agent 开发专属技能**（你面试的岗位）——没有 agent 调试、tool-use 测试、评测、记忆设计的专项技能

**一句话**：方法论层已经成体系（superpowers 闭环），工具层是散装的多插件堆叠。建议——清掉 9 个冗余，保留核心闭环，面试只讲"方法论闭环 + 你项目里的 Agent 实践"，别讲那些垂直插件。
