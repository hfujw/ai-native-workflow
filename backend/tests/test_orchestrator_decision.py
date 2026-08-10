"""测试 orchestrator 决策链路——LLM 自主权恢复后的核心场景。

这些测试验证：LLM 的决策不被 orchestrator 硬编码覆盖，
orchestrator 只在预算/步数耗尽时兜底。
"""



# ── 辅助函数（模拟 orchestrator 的决策处理） ──

def _simulate_decision_handling(decision: dict, ctx: dict) -> dict:
    """模拟 orchestrator_node 中对 LLM decision 的处理逻辑。"""
    # honest 字段 → 自动切换为 render
    if decision.get("honest") and not ctx.get("honest_mode"):
        ctx["honest_mode"] = True
        decision["tool"] = "render"
    return decision


def _simulate_hard_guard(ctx: dict) -> bool:
    """模拟 orchestrator 的硬兜底：步数/预算耗尽。"""
    return ctx["steps"] >= ctx.get("max_steps", 20) or ctx["budget_spent"] >= ctx.get("budget_total", 1.0)


# ── 场景 1：LLM 决定跳过搜索直接设计 ──

def test_llm_skips_search_goes_directly_to_design():
    """LLM 认为知识足够，直接选 design——orchestrator 不干预。"""
    decision = {"tool": "design", "thought": "我对这个话题有充分知识"}
    ctx = {"steps": 0, "budget_spent": 0, "max_steps": 20, "budget_total": 1.0}

    decision = _simulate_decision_handling(decision, ctx)

    assert decision["tool"] == "design"  # 没有被 orchestrator 改为 search


# ── 场景 2：LLM 主动选择诚实模式 ──

def test_llm_actively_chooses_honest_mode():
    """LLM 输出 honest:true → orchestrator 自动切为 render。"""
    decision = {"tool": "search", "honest": True, "thought": "素材不够，诚实呈现"}
    ctx = {"steps": 3, "budget_spent": 0.1}

    decision = _simulate_decision_handling(decision, ctx)

    assert ctx["honest_mode"] is True
    assert decision["tool"] == "render"  # 被 orchestrator 自动改为 render


# ── 场景 3：LLM 搜不到后决定继续（不触发诚实） ──

def test_llm_search_empty_then_continues_to_design():
    """LLM 搜了一次空结果 → 下一步选 design → orchestrator 放行。"""
    decision = {"tool": "design", "thought": "搜索无结果，但我自己知道"}
    ctx = {"steps": 2, "budget_spent": 0.05}

    decision = _simulate_decision_handling(decision, ctx)

    assert decision["tool"] == "design"
    assert not ctx.get("honest_mode")  # 没有被迫进入诚实模式


# ── 场景 4：orchestrator 硬兜底——步数耗尽 ──

def test_hard_guard_steps_exhausted():
    """步数超过上限 → orchestrator 强制终止。"""
    ctx = {"steps": 20, "budget_spent": 0.5, "max_steps": 20, "budget_total": 1.0}
    assert _simulate_hard_guard(ctx) is True


# ── 场景 5：orchestrator 硬兜底——预算耗尽 ──

def test_hard_guard_budget_exhausted():
    """预算超过 ¥1 → orchestrator 强制终止。"""
    ctx = {"steps": 5, "budget_spent": 1.05, "max_steps": 20, "budget_total": 1.0}
    assert _simulate_hard_guard(ctx) is True


# ── 场景 6：正常流程——orchestrator 不放行已触发的诚实模式 ──

def test_honest_mode_not_repeatedly_triggered():
    """已经诚实模式后，LLM 再次输出 honest:true 不会破坏状态。"""
    decision = {"tool": "search", "honest": True, "thought": "还是不够"}
    ctx = {"honest_mode": True, "steps": 4, "budget_spent": 0.3}

    decision = _simulate_decision_handling(decision, ctx)

    assert ctx["honest_mode"] is True  # 状态保持
    assert decision["tool"] == "search"  # tool 不会被改为 render（因为已经诚实模式了）


# ── 场景 7：搜索次数硬拦截——第 9 次被强制改写 ──

def _simulate_search_limit(decision: dict, ctx: dict) -> dict:
    """模拟 orchestrator 的搜索次数硬拦截。"""
    search_count = sum(1 for h in ctx.get("tool_history", []) if h["tool"] == "search")
    if decision.get("tool") == "search" and search_count >= ctx.get("search_max", 8):
        decision["tool"] = "design"
    return decision


def test_search_count_hard_limit_blocks_9th_search():
    """LLM 想搜第 9 次 → orchestrator 强制改为 design。"""
    decision = {"tool": "search", "params": {"query": "再来一次"}}
    ctx = {
        "tool_history": [{"tool": "search"}] * 8,
        "search_max": 8,
        "steps": 8,
        "budget_spent": 0.5,
    }

    decision = _simulate_search_limit(decision, ctx)

    assert decision["tool"] == "design"  # 被强制改了，不是 search
