"""测试 orchestrator 决策链路——LLM 自主权恢复后的核心场景。

这些测试验证：LLM 的决策不被 orchestrator 硬编码覆盖，
orchestrator 只在预算/步数耗尽时兜底。
"""



# ── 辅助函数（模拟 orchestrator 的决策处理） ──

def _simulate_decision_handling(decision: dict, ctx: dict) -> dict:
    """模拟 orchestrator_node 中对 LLM decision 的处理逻辑。"""
    # 零素材防呆：还没搜过、也没素材 → 不允许直接 design/compose（否则设计师空素材降级百科）
    searched = sum(1 for h in ctx.get("tool_history", []) if h.get("tool") == "search")
    if (not ctx.get("material") and searched == 0 and not ctx.get("honest_mode")
            and decision.get("tool") in ("design", "compose")):
        decision = {"tool": "search", "thought": "还没有素材——先搜索关键事实", "params": {}}
    # LLM 自主选 skill：decision.skill → 更新 ctx.skill_id（和选 tool 一样）
    skill_choice = str(decision.get("skill") or "").strip()
    if skill_choice in ("magazine", "infographic", "pixel"):
        ctx["skill_id"] = skill_choice
    # honest 字段 → 自动切换为 render
    elif decision.get("honest") and not ctx.get("honest_mode"):
        ctx["honest_mode"] = True
        decision["tool"] = "render"
    return decision


def _simulate_hard_guard(ctx: dict) -> bool:
    """模拟 orchestrator 的硬兜底：步数/预算耗尽。"""
    return ctx["steps"] >= ctx.get("max_steps", 20) or ctx["budget_spent"] >= ctx.get("budget_total", 1.0)


# ── 场景 1：零素材时 LLM 想直接设计 → 被强制改为 search ──

def test_zero_material_design_forced_to_search():
    """素材 0 条、没搜过 → LLM 想 design 被 orchestrator 强制改为 search（零素材降级百科的防呆）。"""
    decision = {"tool": "design", "thought": "我对这个话题有充分知识"}
    ctx = {"steps": 0, "budget_spent": 0, "max_steps": 20, "budget_total": 1.0,
           "material": [], "tool_history": []}

    decision = _simulate_decision_handling(decision, ctx)

    assert decision["tool"] == "search"  # 被强制改为 search


def test_zero_material_compose_forced_to_search():
    """素材 0 条、没搜过 → LLM 想 compose 同样被拦截。"""
    decision = {"tool": "compose", "thought": "直接写文案"}
    ctx = {"steps": 1, "material": [], "tool_history": []}

    decision = _simulate_decision_handling(decision, ctx)

    assert decision["tool"] == "search"


def test_zero_material_design_allowed_after_search():
    """搜过一次（即使无结果）→ LLM 选 design 放行（搜索死循环防护优先）。"""
    decision = {"tool": "design", "thought": "搜索无结果，但我自己知道"}
    ctx = {"steps": 2, "material": [], "tool_history": [{"tool": "search", "result_summary": "0条"}]}

    decision = _simulate_decision_handling(decision, ctx)

    assert decision["tool"] == "design"


def test_has_material_design_allowed():
    """有素材（KB 命中或搜索成功）→ LLM 选 design 放行。"""
    decision = {"tool": "design", "thought": "素材够了"}
    ctx = {"steps": 1, "material": [{"title": "恐龙灭绝"}], "tool_history": []}

    decision = _simulate_decision_handling(decision, ctx)

    assert decision["tool"] == "design"


# ── 场景 2：LLM 主动选择诚实模式 ──

def test_llm_actively_chooses_honest_mode():
    """LLM 输出 honest:true → orchestrator 自动切为 render。"""
    decision = {"tool": "search", "honest": True, "thought": "素材不够，诚实呈现"}
    ctx = {"steps": 3, "budget_spent": 0.1}

    decision = _simulate_decision_handling(decision, ctx)

    assert ctx["honest_mode"] is True
    assert decision["tool"] == "render"  # 被 orchestrator 自动改为 render


# ── 场景 3：LLM 搜不到后决定继续（不触发诚实） ──
# 已被 test_zero_material_design_allowed_after_search 覆盖（搜过空结果 → design 放行）


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


# ── 场景 8：LLM 自主选 skill（和选 tool 一样）──

def test_llm_selects_skill_updates_ctx():
    """LLM 决策带 skill 字段 → ctx.skill_id 更新为所选 skill。"""
    decision = {"tool": "design", "skill": "infographic", "thought": "数据主题用信息图"}
    ctx = {"material": [{"title": "数据"}], "tool_history": [], "skill_id": "magazine"}

    decision = _simulate_decision_handling(decision, ctx)

    assert ctx["skill_id"] == "infographic"  # LLM 覆盖了预设


def test_llm_skill_choice_optional():
    """LLM 不输出 skill 字段 → ctx.skill_id 不变（沿用预设）。"""
    decision = {"tool": "design", "thought": "直接设计"}
    ctx = {"material": [{"title": "x"}], "tool_history": [], "skill_id": "magazine"}

    _simulate_decision_handling(decision, ctx)

    assert ctx["skill_id"] == "magazine"


def test_llm_skill_choice_invalid_ignored():
    """LLM 输出非法 skill id → 忽略（防注入，只认内置）。"""
    decision = {"tool": "design", "skill": "hacker-style", "thought": "想用奇怪风格"}
    ctx = {"material": [{"title": "x"}], "tool_history": [], "skill_id": "magazine"}

    _simulate_decision_handling(decision, ctx)

    assert ctx["skill_id"] == "magazine"  # 非法 skill 被忽略
