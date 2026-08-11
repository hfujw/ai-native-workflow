"""工具 1: search — 搜素材。Tavily → 空返回 → LLM 用自身知识兜底。"""

import logging

import httpx

from app.llm.parser import detect_injection

logger = logging.getLogger(__name__)

# ── 素材过滤 ──
_AD_NOISE = {"广告", "推广", "促销", "优惠", "团购", "门票", "攻略", "旅游团",
             "酒店", "民宿", "租车", "代购", "加盟", "招商", "股票", "基金"}


def _filter_noise(results: list[dict]) -> list[dict]:
    """过滤广告/推广噪音。"""
    return [r for r in results if not any(kw in r.get("title", "") + r.get("snippet", "") for kw in _AD_NOISE)]


async def _search_tavily(query: str, max_results: int = 8) -> list[dict]:
    """Tavily Search API——国内可直连，返回 JSON 已清洗文本。没配 Key 直接返回空。"""
    from app.core.config import settings

    key = settings.tavily_api_key.strip()
    if not key:
        return []

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
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
            logger.info("Tavily搜索 | query='%s' | 结果=%d", query[:40], len(results))
            return results
    except Exception as e:
        logger.warning("Tavily搜索失败: %s", e)
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
