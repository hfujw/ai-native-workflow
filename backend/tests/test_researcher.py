"""批次 C：ResearcherAgent 自主换词——LLM 决策搜索词，失败回退固定词表。

覆盖：
- C-1 素材充足 → 不换词，1 次搜索
- C-2 LLM 换词成功 → 新词用于第二次搜索
- C-3 LLM 换词失败/返回无效 → 回退 _ALT_ANGLES 词表
- C-4 换词不重复已搜词
- C-5 model 透传给换词决策
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.tools.search import _llm_next_query, ResearcherAgent


def _mk_result(title: str) -> dict:
    return {"title": title, "url": "https://example.com/x", "snippet": f"{title} 的内容"}


async def _fake_search(query: str, **kwargs) -> dict:
    """初始搜索返回空，换词搜索返回 1 条，保证走到换词分支。"""
    if query == "恐龙":
        return {"results": []}
    return {"results": [_mk_result(query)]}


# ═══════════════════════════════════════════════════════════════
# C-1：素材充足不换词
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_enough_material_no_requery():
    """初始搜索即充足 → 不再换词。"""
    agent = ResearcherAgent()
    with patch("app.tools.search.tool_search", new=AsyncMock(
            return_value={"results": [_mk_result("恐龙"), _mk_result("恐龙化石"),
                                     _mk_result("恐龙灭绝"), _mk_result("恐龙种类")]})) as m:
        out = await agent.run("恐龙", session_records=[], model="deepseek-chat")
    assert out["level"] == "high"
    assert m.await_count == 1
    assert out["search_count"] == 1


# ═══════════════════════════════════════════════════════════════
# C-2：LLM 换词成功
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_llm_chooses_next_query():
    """LLM 决定新词「化石种类」→ 第二次搜索用新词。"""
    agent = ResearcherAgent()
    with patch("app.tools.search.tool_search", new=_fake_search), \
         patch("app.tools.search._llm_next_query", new=AsyncMock(return_value="化石种类")) as m:
        out = await agent.run("恐龙", session_records=[], model="deepseek-chat")
    assert m.await_count == 2  # 素材仍不足 → 两轮换词都问 LLM
    assert m.call_args.args[0] == "恐龙"  # topic
    assert m.call_args.args[4] == "deepseek-chat"  # model 位置参数
    assert any("化石种类" in r["title"] for r in out["results"])
    assert out["search_count"] == 3


# ═══════════════════════════════════════════════════════════════
# C-3：LLM 失败 → 回退词表
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_fallback_to_alt_angles_when_llm_fails():
    """LLM 返回 None → 回退「恐龙 历史」（词表第一项）。"""
    agent = ResearcherAgent()
    with patch("app.tools.search.tool_search", new=_fake_search), \
         patch("app.tools.search._llm_next_query", new=AsyncMock(return_value=None)):
        out = await agent.run("恐龙", session_records=[], model="deepseek-chat")
    assert any("恐龙 历史" in r["title"] for r in out["results"])
    assert out["search_count"] == 3  # 初始 + 2 轮词表回退


@pytest.mark.asyncio
async def test_llm_next_query_network_failure_falls_back():
    """底层 chat_json 抛异常 → _llm_next_query 返回 None（调用方回退词表）。"""
    from app.llm import client as client_mod

    with patch.object(client_mod, "chat_json", new=AsyncMock(side_effect=RuntimeError("网络挂了"))):
        q = await _llm_next_query("恐龙", [], ["恐龙"], [], "deepseek-chat")
    assert q is None


# ═══════════════════════════════════════════════════════════════
# C-4：换词不重复已搜词
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_llm_next_query_rejects_repeat_word():
    """LLM 返回已搜过的词 → 判定无效，回退 None。"""
    from app.llm import client as client_mod

    with patch.object(client_mod, "chat_json", new=AsyncMock(return_value='{"query": "恐龙"}')):
        q = await _llm_next_query("恐龙", [], ["恐龙"], [], "deepseek-chat")
    assert q is None


# ═══════════════════════════════════════════════════════════════
# C-5：model 透传（经 supervisor dispatch）
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_dispatch_passes_model_to_researcher():
    """supervisor dispatch(search) 必须把 ctx['model'] 传给 run。"""
    from app.agent.supervisor import dispatch

    with patch("app.agent.supervisor.ResearcherAgent") as MockRA:
        instance = MockRA.return_value
        instance.run = AsyncMock(return_value={"tool": "search", "results": [], "count": 0, "level": "none"})
        ctx = {"user_input": "恐龙", "material": [], "cost_records": [], "model": "deepseek-chat"}
        await dispatch(ctx, "search", None)
        assert instance.run.call_args.kwargs.get("model") == "deepseek-chat"
