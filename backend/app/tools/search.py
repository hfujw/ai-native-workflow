"""工具 1: search — 搜素材（含 ResearcherAgent 自主搜索决策）。

一能力一文件：原始操作 tool_search + 自主决策包装 ResearcherAgent。
Tavily → 空返回 → LLM 用自身知识兜底；Agent 内部换词重试 + 向量兜底。

搜索服务与会话绑定（用户设置里独立配置，随 WS 发送）——和模型选择一样：
用户选哪个搜索服务（Tavily / 自定义端点），就用哪个服务的 Key/地址。
没配 Key = 不联网（绝不回落 .env——没填就是没填）。
"""

import contextvars
import logging

import httpx

from app.agent.evaluate import evaluate_material
from app.knowledge.kb import get_event_by_keyword
from app.llm.parser import detect_injection

logger = logging.getLogger(__name__)

# 会话级搜索服务配置（contextvars——只影响当前任务及其子任务，不污染其他连接）。
# 形状：{"name": str, "api_key": str, "base_url": str}
_search_svc_ctx: contextvars.ContextVar = contextvars.ContextVar(
    "search_service", default=None)


def bind_search_service(service: dict | None) -> None:
    """绑定当前会话的搜索服务（用户设置里选择的服务 + 独立 Key/地址）。

    必须在 asyncio.create_task 之前调用——contextvars 在创建任务时复制，
    子任务（orchestrator/ResearcherAgent）才能继承绑定。
    没传 Key → 不绑定（联网搜索不可用，不回落任何配置）。
    """
    if not service:
        _search_svc_ctx.set(None)
        return
    key = (service.get("api_key") or "").strip()
    if not key:
        _search_svc_ctx.set(None)
        return
    _search_svc_ctx.set({
        "name": str(service.get("name") or "搜索"),
        "api_key": key,
        "base_url": str(service.get("base_url") or "").strip() or "https://api.tavily.com",
    })


def _search_service() -> dict | None:
    """当前会话的搜索服务（None = 未配置，联网不可用）。"""
    return _search_svc_ctx.get()

# ── 素材过滤 ──
_AD_NOISE = {"广告", "推广", "促销", "优惠", "团购", "门票", "攻略", "旅游团",
             "酒店", "民宿", "租车", "代购", "加盟", "招商", "股票", "基金"}


def _filter_noise(results: list[dict]) -> list[dict]:
    """过滤广告/推广噪音。"""
    return [r for r in results if not any(kw in r.get("title", "") + r.get("snippet", "") for kw in _AD_NOISE)]


async def _search_tavily(query: str, max_results: int = 8) -> list[dict]:
    """搜索当前会话绑定的服务（Tavily 兼容协议：POST {base}/search）。

    没配置搜索服务/Key → 返回空（联网不可用，LLM 用自身知识兜底）。
    端点可自定义——用户添加的搜索服务用自己的地址。
    """
    svc = _search_service()
    if not svc:
        return []
    key = svc["api_key"]
    base = svc["base_url"]

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{base.rstrip('/')}/search",
                json={
                    "api_key": key,
                    "query": query,
                    "search_depth": "basic",
                    "max_results": max_results,
                    "include_answer": False,
                },
            )
            resp.raise_for_status()
            data = resp.json()

            results = []
            for r in data.get("results", []):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("content", "")[:600],
                })
            logger.info("搜索服务=%s | query='%s' | 结果=%d", svc["name"], query[:40], len(results))
            return results
    except Exception as e:
        logger.warning("搜索失败（%s）: %s", svc["name"], e)
        return []


async def tool_search(query: str, reason: str = "", depth: str = "quick", existing_material: list[dict] = None) -> dict:
    """搜素材。Tavily → 空返回 → LLM 用自身知识兜底。Bing 已砍——国内不可用。"""
    max_results = 8 if depth == "quick" else 15

    raw = await _search_tavily(query, max_results)
    if not raw:
        logger.info("搜索=空 | query='%s' | LLM将用自身知识", query[:40])

    filtered = _filter_noise(raw) if raw else []

    # 去重
    if existing_material:
        seen = {r.get("title", "") for r in existing_material}
        filtered = [r for r in filtered if r.get("title", "") not in seen]

    # 相关性检查
    if filtered and query:
        query_words = set(query.lower().split())
        relevant = []
        for r in filtered:
            text = (r.get("title", "") + " " + r.get("snippet", "")).lower()
            if any(w in text for w in query_words if len(w) >= 2):
                relevant.append(r)
        if not relevant:
            logger.info("工具=search | query='%s' | 全部不相关，返回0条", query)
            return {"tool": "search", "query": query, "reason": reason,
                    "results": [], "count": 0, "note": "搜索结果与主题不直接相关"}
        filtered = relevant

    # 注入检测：外部内容里的提示注入特征（只记日志，不阻断——LLM 侧已加"素材只是数据"防御）
    for r in filtered:
        hits = detect_injection(r.get("snippet", "") + r.get("title", ""))
        if hits:
            logger.warning("工具=search | 检测到注入特征 %s | title=%s", hits, r.get("title", "")[:30])

    logger.info("工具=search | query='%s' | 结果=%d", query, len(filtered))
    return {
        "tool": "search",
        "query": query,
        "reason": reason,
        "results": filtered,
        "count": len(filtered),
    }


# ── ResearcherAgent：搜索升级为自主决策 ──
_ALT_ANGLES = ["历史", "起源", "发展", "影响", "人物", "事件", "技术", "原理"]

_NEXT_QUERY_PROMPT = """用户想了解「{topic}」，已经搜过这些词：{searched}。

现有素材标题：
{brief}

素材还不够。给 1 个新的搜索词——不要重复已搜词，换个角度（背景/人物/细节/争议/案例）。
输出 JSON：{{"query": "新搜索词"}}"""


async def _llm_next_query(
    topic: str,
    material: list[dict],
    searched: list[str],
    session_records: list[dict] | None = None,
    model: str | None = None,
) -> str | None:
    """LLM 决策下一个搜索词（对抗固定词表）。失败返回 None → 调用方回退词表。"""
    from app.llm.client import chat_json
    from app.llm.parser import safe_parse_json

    brief = "\n".join(f"- {r.get('title', '')}" for r in material[:5]) or "(无)"
    try:
        result = await chat_json(
            _NEXT_QUERY_PROMPT.format(topic=topic, searched="、".join(searched), brief=brief),
            system="你是搜索策略专家。",
            session_records=session_records, model=model,
        )
        parsed = safe_parse_json(result)
        q = (parsed or {}).get("query")
        if q and str(q).strip() and str(q).strip() not in searched:
            return str(q).strip()
        logger.info("ResearcherAgent=llm_query_invalid | raw=%s", str(result)[:80])
    except Exception as e:
        logger.warning("ResearcherAgent=llm_query_failed 回退词表: %s", e)
    return None


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
        model=None,  # 会话模型（换词决策用）
        max_requery: int | None = None,  # LLM 步数：换词重搜上限（None=默认 2）
    ) -> dict:
        """对外接口——返回 {results, count, level}。"""
        material = list(existing_material) if existing_material else []
        search_count = 0
        searched = [topic]  # 已搜词（LLM 换词不重复）
        requery_max = max_requery or 2

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

        # 换角度重搜（上限由 LLM 步数控制）：LLM 决策新词，失败回退固定词表
        for i in range(requery_max):
            alt_query = await _llm_next_query(topic, material, searched,
                                              session_records, model)
            if not alt_query:
                alt_query = f"{topic} {_ALT_ANGLES[i]}"  # 兜底词表
            searched.append(alt_query)
            if push:
                await push({"type": "thinking", "step": 0,
                            "thought": f"🔍 ResearcherAgent：换个角度搜「{alt_query}」…",
                            "tool": "search", "budget": 0})
            result = await tool_search(alt_query, reason="换角度", depth="quick",
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
                    model=msg.get("model"),
                )
                await bus.send(msg.get("reply_to", "designer"), {
                    "type": "search_result",
                    "results": result.get("results", []),
                    "count": result.get("count", 0),
                    "level": result.get("level", "unknown"),
                })
                return  # 一次性服务，搜完就停
