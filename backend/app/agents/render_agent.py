"""Render Agent — 独立负责 HTML 生成、自检、缓存。

内部有决策循环：生成 → 自检 → 不通过就补全 → 再生成。
不依赖 orchestrator 来做"render 失败 → 重 render"的判断。
缓存是类级变量（_cache, _cache_time），所有实例共享。
"""

import copy
import hashlib
import json
import logging
import time
from typing import ClassVar

from app.llm.parser import strip_fence
from app.tools.render import tool_render_stream

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
            from app.core.metrics import RENDER_CACHE_HITS
            RENDER_CACHE_HITS.inc()
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

            # 生成 HTML（内部流式收集，不 push 前端）
            html = await self._generate(patched_design, content, session_records)
            html = strip_fence(html)
            # 用 lstrip 防止换行/空格导致 startswith 失败，重复添加 DOCTYPE
            if not html.lstrip().lower().startswith("<!doctype"):
                html = f"<!DOCTYPE html>\n{html}"

            # 空内容短路：_generate 完全失败时直接返回失败
            if not html or len(html) < 200:
                return {"tool": "render", "html": "", "complete": False,
                        "length": len(html), "attempts": attempt + 1,
                        "self_check_issues": ["generate_empty"]}

            # 自检
            issues = self._self_check(html)

            if not issues:
                # 通过 → 缓存 + push + 返回
                logger.info("RenderAgent=pass | attempt=%d | len=%d", attempt + 1, len(html))
                from app.core.metrics import RENDER_CACHE_MISSES
                RENDER_CACHE_MISSES.inc()
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

        排除动态字段（时间戳、随机ID 等），否则每次 key 不同，缓存永不命中。
        """
        # 只取业务字段，排除元数据
        design_static = {
            "components": design.get("components", []),
            "rationale": design.get("rationale", ""),
            "structure": design.get("structure", ""),
            "visual_hint": design.get("visual_hint", ""),
        }
        content_static = {
            "title": content.get("title", ""),
            "subtitle": content.get("subtitle", ""),
            "blocks": content.get("blocks", []),
        }
        try:
            raw = json.dumps(
                {"d": design_static, "c": content_static},
                sort_keys=True, ensure_ascii=False,
            )
        except (TypeError, ValueError):
            raw = repr((design_static, content_static))
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _cache_get(self, key: str) -> str | None:
        """查缓存，自动清理过期项。"""
        now = time.monotonic()
        if key in self._cache and now - self._cache_time.get(key, 0) < CACHE_TTL:
            return self._cache[key]
        # 过期 → 清理
        self._cache.pop(key, None)
        self._cache_time.pop(key, None)
        from app.core.metrics import RENDER_CACHE_EVICTED
        RENDER_CACHE_EVICTED.labels(reason="ttl_expired").inc()
        return None

    def _cache_set(self, key: str, html: str):
        """写缓存。超上限时淘汰最老的条目。"""
        now = time.monotonic()
        self._cache[key] = html
        self._cache_time[key] = now

        # 淘汰：达到 CACHE_MAX 条时，删除最老的那条
        if len(self._cache) >= CACHE_MAX:
            from app.core.metrics import RENDER_CACHE_EVICTED
            oldest_key = min(self._cache_time, key=lambda k: self._cache_time[k])
            self._cache.pop(oldest_key, None)
            self._cache_time.pop(oldest_key, None)
            RENDER_CACHE_EVICTED.labels(reason="capacity_limit").inc()
