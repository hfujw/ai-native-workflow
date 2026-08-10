"""Researcher Agent —— 搜索升级为自主决策。

不再"搜一次就返回"，而是内部循环：搜索 → 评估 → 不够就换词重搜 → 向量兜底。
不依赖 orchestrator 来做"搜不到 → 重搜"的判断。
"""

import logging

from app.agents.evaluate import evaluate_material
from app.knowledge.kb import get_event_by_keyword
from app.tools.search import tool_search

logger = logging.getLogger(__name__)

# 备选搜索角度（首次搜空后换角度重试）
_ALT_ANGLES = ["历史", "起源", "发展", "影响", "人物", "事件", "技术", "原理"]


class ResearcherAgent:
    """搜索 Agent —— 自主决定搜索策略。

    内部循环：
    1. 搜索（原始词）
    2. 评估 → 够不够？
    3. 不够 → 换角度重搜（最多 2 次）
    4. 还不够 → 语义向量兜底
    5. 仍然不够 → 诚实标记
    """

    async def run(
        self,
        topic: str,
        existing_material: list[dict] | None = None,
        session_records=None,
        push=None,  # 推给前端的回调（可选）
    ) -> dict:
        """对外接口——返回 {results, count, level}。"""
        material = list(existing_material) if existing_material else []
        search_count = 0

        # 先试原始词
        if push:
            await push({"type": "thinking", "step": 0,
                        "thought": f"🔍 ResearcherAgent：搜索「{topic}」…",
                        "tool": "search", "budget": 0})
        result = await tool_search(topic, reason="初始搜索", depth="quick",
                                   existing_material=material)
        material.extend(result.get("results", []))
        search_count += 1

        evaluation = evaluate_material(material, topic)
        if evaluation["level"] == "high":
            if push:
                await push({"type": "thinking", "step": 0,
                            "thought": f"✅ ResearcherAgent：搜索完成，{evaluation['reason']}",
                            "tool": "search", "budget": 0})
            return self._done(material, evaluation, search_count)

        # 换角度重搜（最多 2 次）
        for angle in _ALT_ANGLES[:2]:
            alt_query = f"{topic} {angle}"
            if push:
                await push({"type": "thinking", "step": 0,
                            "thought": f"🔍 ResearcherAgent：换个角度搜「{alt_query}」…",
                            "tool": "search", "budget": 0})
            result = await tool_search(alt_query, reason=f"换角度: {angle}", depth="quick",
                                       existing_material=material)
            new_count = len(result.get("results", []))
            material.extend(result.get("results", []))
            search_count += 1

            evaluation = evaluate_material(material, topic)
            if evaluation["level"] == "high":
                if push:
                    await push({"type": "thinking", "step": 0,
                                "thought": f"✅ ResearcherAgent：搜索完成，{evaluation['reason']}",
                                "tool": "search", "budget": 0})
                return self._done(material, evaluation, search_count)

            if new_count == 0 and search_count >= 2:
                break
        if push:
            await push({"type": "thinking", "step": 0,
                        "thought": f"⚠️ ResearcherAgent：搜了 {search_count} 轮，{evaluation['reason']}",
                        "tool": "search", "budget": 0})

        # 向量兜底
        kb_material = await self._vector_fallback(topic)
        if kb_material:
            material.extend(kb_material)
            evaluation = evaluate_material(material, topic)

        return self._done(material, evaluation, search_count)

    # ─── 内部方法 ───

    def _done(self, material, evaluation, count) -> dict:
        return {
            "tool": "search",
            "results": material,
            "count": len(material),
            "level": evaluation["level"],
            "reason": evaluation["reason"],
            "search_count": count,
        }

    async def _vector_fallback(self, topic: str) -> list[dict]:
        """语义向量检索兜底。"嬴政" → "秦始皇"。"""
        try:
            from app.knowledge.vector_store import vector_search
            hits = vector_search(topic, top_k=3, min_distance=1.5)
            results = []
            for h in hits:
                event = get_event_by_keyword(h["title"])
                if event:
                    from app.knowledge.kb import event_to_search_results
                    results.extend(event_to_search_results(event))
                    logger.info("ResearcherAgent=vector_hit | %s → %s", topic, h["title"])
            return results
        except Exception as e:
            logger.debug("向量检索不可用: %s", e)
            return []

    async def listen(self, bus):
        """Phase 4：通过消息总线监听搜索请求。收到消息 → 执行搜索 → 返回结果。"""
        bus.register("researcher")
        while True:
            msg = await bus.recv("researcher", timeout=60.0)
            if msg is None:
                continue
            if msg.get("type") == "search_request":
                result = await self.run(
                    topic=msg.get("topic", ""),
                    existing_material=msg.get("existing_material"),
                    session_records=msg.get("session_records"),
                    push=msg.get("push"),  # 推消息给前端
                )
                await bus.send(msg.get("reply_to", "designer"), {
                    "type": "search_result",
                    "results": result.get("results", []),
                    "count": result.get("count", 0),
                    "level": result.get("level", "unknown"),
                })
                return  # 一次性服务，搜完就停
