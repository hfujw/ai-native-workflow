"""Designer Agent —— 合并 design + compose，内部自循环。

素材不够时不再默默降级——通过 MessageBus 向 ResearcherAgent 求助。
没有 bus 时回退到旧降级行为（向后兼容）。
"""

import logging
from app.tools.design import tool_design
from app.tools.compose import tool_compose

logger = logging.getLogger(__name__)

COMPONENT_MIN_MATERIAL: dict[str, int] = {
    "timeline": 3, "comparison": 3, "cards": 1,
    "flowchart": 2, "portrait": 1, "datapanel": 2, "encyclopedia": 0,
}


class DesignerAgent:
    """设计 + 文案 Agent —— 支持向 ResearcherAgent 求助。"""

    async def run(
        self,
        material: list[dict],
        user_input: str,
        push=None,
        session_records=None,
        bus=None,                     # Phase 4：消息总线（可选）
    ) -> dict:
        mat_count = len(material)

        for attempt in range(2):
            design = await tool_design(material, user_input, session_records=session_records)

            # 素材不够？
            if not self._check_design_fit(design, mat_count):
                # 有消息总线 → 通过 bus 请 ResearcherAgent 帮忙
                if bus:
                    logger.info("DesignerAgent=ask_help | need=%s | have=%d条",
                                design.get("components", []), mat_count)
                    if push:
                        await push({"type": "thinking", "step": 0,
                                    "thought": f"🤝 DesignerAgent：素材仅 {mat_count} 条，向 ResearcherAgent 求助搜索「{user_input}」…",
                                    "tool": "design", "budget": 0})
                    bus.register("designer")
                    bus.register("researcher")
                    from app.agents.researcher_agent import ResearcherAgent
                    import asyncio
                    listener = asyncio.create_task(ResearcherAgent().listen(bus))
                    await bus.send("researcher", {
                        "type": "search_request",
                        "topic": user_input,
                        "existing_material": material,
                        "session_records": session_records,
                        "reply_to": "designer",
                        "push": push,  # 传 push 回调，让 ResearcherAgent 能推消息
                    })
                    reply = await bus.recv("designer", timeout=45.0)
                    listener.cancel()
                    if reply and reply.get("type") == "search_result":
                        new_results = reply.get("results", [])
                        material.extend(new_results)
                        mat_count = len(material)
                        logger.info("DesignerAgent=got_help | +%d条 → 共%d条",
                                    reply.get("count", 0), mat_count)
                        if push:
                            await push({"type": "thinking", "step": 0,
                                        "thought": f"✅ DesignerAgent：收到 {reply.get('count', 0)} 条新素材（共 {mat_count} 条），重新设计…",
                                        "tool": "design", "budget": 0})
                        continue  # 重新设计

                # 没有 bus → 旧降级行为
                design = self._downgrade_design(design, mat_count)
                patched = [{"title": "⚠️ 素材不足，请使用简单形式（如 encyclopedia/cards）",
                            "snippet": f"仅有 {mat_count} 条素材", "content": ""}]
                design = await tool_design(patched, user_input, session_records=session_records)

            content = await tool_compose(material, design, user_input, session_records=session_records)

            coverage = self._source_coverage(content)
            if coverage >= 0.3:
                logger.info("DesignerAgent=pass | attempt=%d | components=%s | coverage=%.0f%%",
                            attempt + 1, design.get("components", []), coverage * 100)
                return {"tool": "design", "design": design, "content": content, "attempts": attempt + 1}

            logger.info("DesignerAgent=retry | attempt=%d | coverage=%.0f%%", attempt + 1, coverage * 100)

        logger.info("DesignerAgent=fallback |百科降级")
        return self._fallback(material, user_input, session_records)

    # ─── 内部方法 ───

    def _check_design_fit(self, design: dict, material_count: int) -> bool:
        components = design.get("components", [])
        for comp in components:
            if material_count < COMPONENT_MIN_MATERIAL.get(comp, 1):
                return False
        return True

    def _downgrade_design(self, design: dict, material_count: int) -> dict:
        components = design.get("components", [])
        downgraded = []
        for comp in components:
            if material_count < COMPONENT_MIN_MATERIAL.get(comp, 1):
                if "encyclopedia" not in downgraded:
                    downgraded.append("encyclopedia")
            else:
                downgraded.append(comp)
        if not downgraded:
            downgraded = ["encyclopedia"]
        design["components"] = downgraded
        design["rationale"] = f"素材仅 {material_count} 条，降级为 {'+'.join(downgraded)}"
        return design

    def _source_coverage(self, content: dict) -> float:
        total = sourced = 0
        for block in content.get("blocks", []):
            for claim in block.get("claims", []):
                total += 1
                if claim.get("source") and claim.get("confidence", "") != "unknown":
                    sourced += 1
        return sourced / total if total > 0 else 0.0

    async def _fallback(self, material, user_input, session_records) -> dict:
        design = {"tool": "design", "components": ["encyclopedia"],
                  "rationale": "素材不足，降级为百科条目",
                  "structure": "单列百科", "visual_hint": "简洁中性"}
        content = {"tool": "compose", "title": user_input,
                   "subtitle": "基于有限资料的诚实呈现",
                   "blocks": [], "fact_notes": "当前素材不足以生成完整叙事"}
        if material:
            brief = "\n".join(
                f"- {r.get('title', '')}: {r.get('snippet', r.get('content', ''))[:200]}"
                for r in material[:5]
            )
            design["rationale"] += f"\n可用素材：\n{brief}"
        return {"tool": "design", "design": design, "content": content}
