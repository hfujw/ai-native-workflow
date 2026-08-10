# Phase 1：Render Agent · 独立试点

> 状态：方案阶段（已过代码审查，致命问题已修）  
> 目标：把 `tool_render` 从"函数"升级为"有内部决策循环的 Agent"，验证模式  
> 原则：外表不动——orchestrator 调用方式不变，内部升级  
> 核心收益：相同 design+content 不重复生成，HTML 截断在 Agent 内部修复，减少 verify→回退→重 render 的 token 浪费

---

## 致命问题已修（两轮审查后修正）

| # | 问题 | 严重度 | 修复 |
|---|------|--------|------|
| 1 | 每次 `RenderAgent()` new 实例 → 缓存永不命中 | 🔴 | 缓存改为**类变量** `_cache: ClassVar`，所有实例共享 |
| 2 | 重试时流式推两次 → 前端闪烁 | 🔴 | 生成时**不 push**，自检通过后**一次性 push**；最后一轮失败也 push |
| 3 | `_patch_hint` 原地修改 design → 污染 ctx | 🔴 | `copy.deepcopy(design)` 后再修改 |
| 4 | 自检太薄：只查 `</html>` `</script>` `{` | 🟡 | 增加**标签配对检查**：四对标签 |
| 5 | 缓存无限增长 → OOM | 🟡 | TTL 5分钟 + 上限 50 条 + 淘汰最老 |
| 6 | token 记账在重试时重复 | 🟡 | 明确：`session_records` 累加式，正确行为 |
| 7 | `complete: false` 时 HTML 不写 ctx | 🟡 | 修正：**始终写 HTML**（有内容就写），让 verify 能审实际内容 |
| 8 | 流式帧格式假设未文档化 | 🔴 | 已确认：`tool_render_stream` 推的是**全量累计** HTML，`_generate` 逻辑正确；加注释说明 |
| 9 | DOCTYPE 重复添加（换行/空格导致） | 🔴 | `html.lstrip().lower().startswith("<!doctype")` |
| 10 | `_generate` 无异常兜底 | 🔴 | try/except 包裹，返回已收集的部分内容 |
| 11 | 缓存 key 序列化可能 TypeError | 🟡 | `default=str` 兜底 |
| 12 | `complete: false` 时 ctx 残留旧值 | 🟡 | 已修正（见 #7）：始终写 HTML，不依赖旧值 |
| 13 | `_generate` 完全失败返回空串 → 自检通过 | 🔴 | 加最小长度检查：`< 200` 字节直接判定失败 |
| 14 | 自检只查"有开无闭"，纯文本/Markdown 会误判通过 | 🟡 | 加 `<html>` `<body>` 必须存在检查 |
| 15 | `push` 失败会中断整个请求 | 🟡 | 包 `_safe_push` try/except，不阻断返回 |

---

## 一、现状

```
orchestrator._execute_tool("render")
    │
    └── tools/render.py
        ├── tool_render(design, content)         # 一次性生成（不走流式）
        └── tool_render_stream(design, content)  # 流式生成（实际在用）
```

问题：
- render 是单次 LLM 调用，没有自检。HTML 截断只能等 verify 发现
- verify 发现截断 → 回退 render 重来 → 又花一次 16K token
- 相同 design+content 每次重新生成，不设缓存

---

## 二、目标

```
orchestrator._execute_tool("render")
    │
    └── agents/render_agent.py
        └── RenderAgent.run(design, content)
            │
            ├── 1. 查缓存：相同 design+content 命中 → 直接返回（不调 LLM）
            ├── 2. 生成 HTML（内部流式，但不 push 前端）
            ├── 3. 自检：标签配对 </html> <script> 占位符
            ├── 4. 通过 → 一次性 push 前端 + 缓存 + 返回
            ├── 5. 不通过 → 补全修复指引 → 重生成（最多 2 次）
            └── 6. 两次都没过 → push 最后一次结果 + 返回 complete:false
```

---

## 三、RenderAgent 完整代码

```python
# agents/render_agent.py

import copy
import hashlib
import json
import logging
import time
from typing import ClassVar
from app.tools.render import tool_render_stream  # 内部还是用现有的流式生成
from app.llm.parser import strip_fence

logger = logging.getLogger(__name__)

CACHE_MAX = 50          # 最多缓存 50 条
CACHE_TTL = 300         # 过期时间 5 分钟（秒）


class RenderAgent:
    """渲染 Agent —— 独立负责 HTML 生成、自检、缓存。

    内部有简单的决策循环：生成 → 自检 → 不通过就补全 → 再生成。
    不依赖 orchestrator 来做"render 失败 → 重 render"的判断。

    缓存是类级变量（_cache, _cache_time），所有实例共享。
    """

    _cache: ClassVar[dict[str, str]] = {}
    _cache_time: ClassVar[dict[str, float]] = {}

    async def run(
        self,
        design: dict,
        content: dict,
        push=None,                    # 推消息到前端的回调
        session_records=None,         # token 记账（累加式）
    ) -> dict:
        """对外接口——和 tool_render 签名一致，orchestrator 无感。"""

        # ── Step 1: 查缓存 ──
        cache_key = self._cache_key(design, content)
        cached = self._cache_get(cache_key)
        if cached is not None:
            logger.info("RenderAgent=cache_hit | key=%s", cache_key)
            # 缓存命中也要推给前端（否则用户看不到页面）
            await self._safe_push(push, cached)
            return {"tool": "render", "html": cached, "complete": True,
                    "length": len(cached), "cached": True}

        # ── Step 2: 生成 + 自检循环 ──
        html = ""
        issues = []

        for attempt in range(2):
            # 深拷贝 design，防止 _patch_hint 污染 ctx["design"]
            patched_design = copy.deepcopy(design)
            if issues:
                patched_design = self._patch_hint(patched_design, issues)

            # 生成 HTML（内部流式，不 push）
            html = await self._generate(patched_design, content, session_records)
            html = strip_fence(html)
            # 用 lstrip 防止换行/空格导致 startswith 失败，重复添加 DOCTYPE
            if not html.lstrip().lower().startswith("<!doctype"):
                html = f"<!DOCTYPE html>\n{html}"

            # 自检
            issues = self._self_check(html)

            if not issues:
                # 通过 → 缓存 + push + 返回
                logger.info("RenderAgent=pass | attempt=%d | len=%d", attempt + 1, len(html))
                self._cache_set(cache_key, html)
                await self._safe_push(push, html)
            return {"tool": "render", "html": html, "complete": True,
                        "length": len(html), "attempts": attempt + 1,
                        "self_checked": True}

            logger.info("RenderAgent=retry | attempt=%d | issues=%s", attempt + 1, issues)

        # ── Step 3: 两次都没过 → push 最后一次结果，让 verify 兜底 ──
        # 即使没通过自检，也推给前端——用户看到"AI 在努力"比看到白屏好
        await self._safe_push(push, html)
        return {"tool": "render", "html": html, "complete": False,
                "length": len(html), "attempts": 2,
                "self_check_issues": issues}

    # ─── 内部方法 ───

    async def _safe_push(self, push, html: str):
        """安全推送——WebSocket 断开时静默处理，不阻断返回。"""
        if not push:
            return
        try:
            await push({"type": "html_chunk", "html": html})
        except Exception as e:
            logger.warning("RenderAgent=push_failed | %s", e)

    async def _generate(self, design, content, session_records) -> str:
        """流式收集完整 HTML，不 push 前端（等自检通过再推）。

        依赖事实：tool_render_stream 的 frame["html"] 是**全量累计**内容，
        不是增量 delta——这点已在 tools/render.py:120 确认。
        """
        accumulated = ""
        try:
            async for frame in tool_render_stream(
                design, content,
                session_records=session_records,
            ):
                if frame.get("complete"):
                    return frame.get("html", accumulated)
                else:
                    accumulated = frame.get("html", accumulated)
        except Exception as e:
            logger.error("RenderAgent=_generate_failed | %s", e)
        return accumulated  # 返回已收集的碎片，让自检决定能不能用

    def _self_check(self, html: str) -> list[str]:
        """自检：纯规则，不调 LLM。"""
        issues = []

        # 最小内容检查：正常 HTML 至少 200 字节
        if len(html) < 200:
            issues.append("content_too_short")

        lower = html.lower()

        # 必须存在的标签（不是可选的）
        required = [("<html", "</html>"), ("<body", "</body>")]
        for open_tag, close_tag in required:
            if open_tag not in lower:
                issues.append(f"missing_{open_tag.strip('<>')}")
            elif close_tag not in lower:
                issues.append(f"missing_{close_tag.strip('<>')}")

        # 可选但需闭合的标签
        optional = [("<script", "</script>"), ("<style", "</style>")]
        for open_tag, close_tag in optional:
            if open_tag in lower and close_tag not in lower:
                issues.append(f"missing_{close_tag.strip('<>')}")

        # 占位符残留
        if "{{" in html:
            issues.append("placeholder_left")

        return issues

    def _patch_hint(self, design: dict, issues: list[str]) -> dict:
        """在原 design 上追加修复指引（调用方已确保 deepcopy，不会污染 ctx）。"""
        hints = {
            "content_too_short": "⚠️ 上轮生成内容过短或为空，请重新生成完整 HTML",
            "missing_<html": "⚠️ 缺少 <html> 开始标签",
            "missing_<body": "⚠️ 缺少 <body> 开始标签",
            "missing_</html>": "⚠️ 上轮 HTML 被截断，请精简 CSS，确保输出完整 </html>",
            "missing_</body>": "⚠️ 缺少 </body> 闭合标签",
            "missing_</script>": "⚠️ 必须包含至少一个 <script>...</script> 块",
            "missing_</style>": "⚠️ 缺少 </style> 闭合标签",
            "placeholder_left": "⚠️ 检查所有 {{xx}} 占位符已被替换为实际内容",
        }
        patch = " | ".join(hints[i] for i in issues if i in hints)
        if patch:
            if design.get("visual_hint"):
                design["visual_hint"] = f"{design['visual_hint']} | {patch}"
            else:
                design["visual_hint"] = patch
        return design

    # ─── 缓存 ───

    def _cache_key(self, design, content) -> str:
        """SHA256 前 16 位。design+content 相同 → key 相同。

        default=str 兜底：design/content 里可能混入 datetime 等不可序列化对象。
        """
        try:
            raw = json.dumps({"d": design, "c": content}, sort_keys=True, ensure_ascii=False)
        except (TypeError, ValueError):
            raw = repr((design, content))
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _cache_get(self, key: str) -> str | None:
        """查缓存，自动清理过期项。"""
        now = time.monotonic()
        if key in self._cache and now - self._cache_time.get(key, 0) < CACHE_TTL:
            return self._cache[key]
        # 过期 → 清理
        self._cache.pop(key, None)
        self._cache_time.pop(key, None)
        return None

    def _cache_set(self, key: str, html: str):
        """写缓存。超上限时淘汰最老的条目。"""
        now = time.monotonic()
        self._cache[key] = html
        self._cache_time[key] = now

        # 淘汰：超过 CACHE_MAX 条，删除最老的那条
        if len(self._cache) > CACHE_MAX:
            oldest_key = min(self._cache_time, key=lambda k: self._cache_time[k])
            self._cache.pop(oldest_key, None)
            self._cache_time.pop(oldest_key, None)
```

---

## 四、orchestrator 改动

```python
# agents/orchestrator.py _execute_tool()

# 之前（当前代码）
elif tool_name == "render":
    from app.tools import tool_render_stream
    result = None
    async for frame in tool_render_stream(
        ctx["design"] or {}, ctx["content"] or {},
        session_records=ctx.get("cost_records"),
    ):
        if frame.get("complete"):
            result = frame
        else:
            push = ctx.get("_push")
            if push:
                await push({"type": "html_chunk", "html": frame["html"]})
    if result and result.get("html"):
        ctx["html"] = result["html"]
    return result or {"tool": "render", "html": "", "complete": False, "length": 0}

# 之后
elif tool_name == "render":
    from app.agents.render_agent import RenderAgent
    result = await RenderAgent().run(
        ctx["design"] or {},
        ctx["content"] or {},
        push=ctx.get("_push"),
        session_records=ctx.get("cost_records"),
    )
    # 始终写 HTML（有内容就写）——verify 需要审实际内容而非空字符串
    if result.get("html"):
        ctx["html"] = result["html"]
    return result
```

---

## 五、测试清单

| # | 场景 | 预期 |
|---|------|------|
| 1 | 正常生成 + 自检通过 | 返回 `complete: true`，`self_checked: true`，`attempts: 1` |
| 2 | 第一次缺 `</html>`，第二次补全 | `attempts: 2`，HTML 包含 `</html>` |
| 3 | 两次都没通过 | `complete: false`，`self_check_issues` 非空，HTML 仍写入 ctx（verify 审残缺内容） |
| 4 | 相同 design+content 调两次 | 第二次 `cached: true`，不调 LLM |
| 5 | 缓存超 5 分钟 | 过期，重新生成 |
| 6 | 缓存超 50 条 | 最老条目被淘汰 |
| 7 | 自检：HTML 完全正常 | 返回空 `issues` |
| 8 | 自检：缺 `</body>` | `issues = ["missing_/body"]` |
| 9 | 自检：`<script>` 没闭合 | `issues = ["missing_</script>"]` |
| 10 | 自检：内容 < 200 字节 | `issues` 包含 `"content_too_short"` |
| 11 | 自检：纯文本（无 `<html>`） | `issues` 包含 `"missing_<html"` |
| 12 | `_safe_push` WS 断开 | 不抛异常，日志记录，正常返回结果 |
| 13 | `_patch_hint` 不修改原 design | 传入的 design 字典在调用前后一致 |

---

## 六、文件变更

| 操作 | 文件 | 说明 |
|------|------|------|
| 新建 | `agents/render_agent.py` | RenderAgent 类（约 130 行） |
| 修改 | `agents/orchestrator.py` | `_execute_tool` render 分支 10 行改为 8 行 |
| 不改 | `tools/render.py` | `tool_render_stream` 保留，Agent 内部调用 |

---

## 七、面试表述

> "Render 是 Token 消耗最大的一步——16K tokens，一次 ¥0.15。我把 render 拆成独立 Agent，内部有三层优化：
> 1. **自检循环**：生成完先检查标签闭合，不通过就补全重试——不用等 verify 发现截断再回退重 render。
> 2. **缓存**：相同 design+content 调用两次时直接返回缓存 HTML，一毛不花。类级变量保证所有请求共享同一份缓存。
> 3. **延迟推送**：生成过程中不在前端刷屏——自检通过后一次性推完整 HTML，用户看到干净的成品。
> 关键是外表没变——orchestrator 调用 RenderAgent 和调 tool_render 一模一样。这验证了'把工具升级为 Agent 不改上层'的模式。"
