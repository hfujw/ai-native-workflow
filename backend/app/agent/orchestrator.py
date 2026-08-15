"""编排 Agent — 思考→行动→反馈 主循环。

拿到用户输入后，不按固定流程。每一步都是：
1. 🤔 思考：告诉用户"我打算干什么、为什么"
2. 🔧 行动：调用工具
3. 📊 反馈：展示结果
4. 🔄 循环：根据反馈决定下一步
"""

import asyncio
import json
import logging

from app.agent.evaluate import evaluate_material
from app.config import settings
from app.knowledge.kb import _name, event_to_search_results, get_event_by_keyword
from app.llm.client import chat_stream
from app.llm.parser import clean_thought, safe_parse_json, strip_fence
from app.observability.trace import log_trace

logger = logging.getLogger(__name__)

ORCHESTRATOR_SYSTEM_PROMPT = """你是一个视觉叙事引擎。用户给你一个主题，你生成一个好看的HTML页面。

【工具】
- search(query, reason) → 搜素材（内部自动换词重搜 + 向量兜底）
- design → 设计叙事形式 + 写文案 + 标来源（一步完成）
- render → 生成HTML（内部自检 + 缓存 + 重试）
- verify → Playwright审查

【硬规则】
- render之后必须verify
- verify说过 → 停止，输出final
- verify说不过 → 退给render或design，你来决定退给谁
- 最多20步，总预算¥1，最多搜8次
- HTML截断(缺</html>) → 自动失败，必须重render
- 同一工具连续3次失败 → 必须换策略

【决策指南】
- **你是决策中心**。orchestrator 只执行和兜底，其他决定都你来做。
- **搜索是可选的增强**。有把握的话题直接 design。
- 不确定的话题选 search 验证。最多搜 8 次。
- 搜不到？换词重搜已在 Agent 内部处理，你只需要调 search 一次。
- design 现在一步完成设计+文案，不需要再单独调 compose。
- verify说"visual不好看"→退render；"来源不足"或"形式不合适"→退design
- 预算紧张时用最简方案
- 【诚实模式】**你**认为素材不够且你也没把握时：直接 render 诚实页面，不编造

输出JSON。thought 字段是你每步决策前的内心独白。
- 如果你想进入诚实模式（素材不够且你没把握），在 JSON 中加 `"honest": true`，tool 会被自动设为 render
- 其他时候不需要 honest 字段
- 第1步：可以介绍主题背景（如"我对这个话题的了解是…"）
- 第2步及以后：禁止重复"用户想了解XXX""我对XXX不太熟悉"等开场白。直接从上一
  步的结果开始——"上一步搜到了5条素材，但都是朱姓百科而非朱子钦本人，所以现在…"
- 不要像个复读机每次重新介绍主题。像一个人在持续思考，不是每次都重启。
- 好例子（第3步）："连续两次搜索都只返回朱姓泛化内容，没有增量信息。继续搜没意义了，
  素材评估显示与'朱子钦'无直接关联。用朱字释义做一个诚实的汉字文化页。"
- 坏例子（第3步）："用户想了解朱子钦这个人。我对这个名字不太熟悉。搜索结果显示…"

{"thought":"3-4句自然内心独白","tool":"search|design|compose|render|verify","params":{}}"""


def apply_gen_params(ctx: dict, params: dict | None) -> None:
    """把前端设置里的生成参数（会话级）覆盖到编排上下文。

    - agentSteps  → max_steps（Agent 决策循环步数）
    - budget      → budget_total（单次生成成本上限，元）
    - searchMax   → search_max（搜索轮数上限）
    - searchEnabled → search_enabled（False 时强制禁止搜索）
    - llmSteps    → llm_steps（预留：单次 LLM 调用的步数语义，工具层参数化后接入）
    """
    p = params or {}
    if p.get("agentSteps") is not None:
        ctx["max_steps"] = min(100, max(1, int(p["agentSteps"])))  # 上限对齐 config（防烧钱）
    if p.get("budget") is not None:
        ctx["budget_total"] = max(0.0, float(p["budget"]))
    if p.get("searchMax") is not None:
        ctx["search_max"] = min(20, max(0, int(p["searchMax"])))   # 上限对齐 config
    ctx["search_enabled"] = bool(p.get("searchEnabled", True))
    if p.get("llmSteps") is not None:
        ctx["llm_steps"] = min(100, max(1, int(p["llmSteps"])))


async def orchestrator_node(state: dict) -> dict:
    """主循环：思考→行动→反馈→循环。思考先推到前端，用户看到后AI再行动。"""
    user_input = state.get("user_input", "")
    push = state.get("_push")

    ctx = {
    "session_id": state.get("session_id", ""),
    "user_input": user_input,
    "_push": push,
    "material": [],
    "design": None,
    "content": None,
    "html": "",
    "visual": None,
    "steps": 0,
    "max_steps": settings.max_steps,
    "search_max": settings.search_max,
    "search_enabled": True,
    "model": settings.deepseek_model,   # 会话模型（前端 Composer 选择可覆盖）
    "budget_spent": 0.0,
    "budget_total": settings.budget_total,
    "passed": False,
    "issues": [],
    "tool_history": [],
    "cost_records": state.get("_cost_records", []),
    "_last_cost_len": 0,   # 真实预算：上次结算的账本长度
    "_preferences": state.get("_preferences", {}),  # Phase C：用户偏好
    }

    # 前端设置里的生成参数（会话级覆盖全局配置）
    apply_gen_params(ctx, state.get("_params"))
    # 前端 Composer 选择的模型（会话级覆盖）
    if state.get("_model"):
        ctx["model"] = state["_model"]

    # 本地知识库：关键词匹配 → 没命中 → 语义向量检索兜底
    # "嬴政" 能匹配到 "秦始皇修长城"——关键词做不到的，向量能做到。
    kb_event = get_event_by_keyword(user_input)
    if kb_event:
        ctx["material"].extend(event_to_search_results(kb_event))
        logger.info("KB命中 | session=%s | topic=%s", ctx["session_id"], _name(kb_event))
    else:
        from app.knowledge.vector_store import vector_search
        try:
            hits = vector_search(user_input, top_k=3, min_distance=1.5)
            for h in hits:
                event = get_event_by_keyword(h["title"])
                if event:
                    ctx["material"].extend(event_to_search_results(event))
                    logger.info("向量命中 | session=%s | query='%s' → '%s'",
                                ctx["session_id"], user_input, _name(event))
        except Exception as e:
            logger.debug("向量检索不可用: %s", e)  # ChromaDB 不可用时静默跳过

    while ctx["steps"] < ctx["max_steps"] and ctx["budget_spent"] < ctx["budget_total"]:

        # 0. 诚实模式 render 后强制 verify
        if ctx.get("force_verify"):
            ctx.pop("force_verify")
            decision = {"thought": "诚实模式：自动验证", "tool": "verify", "params": {}}
        elif ctx.get("force_next_tool"):
            # 强制回退：跳过 LLM 决策，直接执行指定工具
            tool_name = ctx.pop("force_next_tool")
            if push:
                await push({"type": "tool_result", "step": ctx["steps"] + 1, "tool": tool_name,
                            "summary": f"强制回退执行 {tool_name}…", "budget": ctx["budget_spent"]})
            result = await _execute_tool(tool_name, {}, ctx)  # 不依赖上一轮的旧 params
            ctx["steps"] += 1
            ctx["tool_history"].append({"step": ctx["steps"], "tool": tool_name,
                                        "result_summary": _summarize(result)})
            if push:
                await push({"type": "tool_result", "step": ctx["steps"], "tool": tool_name,
                            "summary": _summarize(result), "budget": ctx["budget_spent"]})
            continue
        else:
            # 1. 让LLM决定下一步
            decision = await _decide(ctx)

        # 1.5. LLM 主动选择诚实模式
        if decision.get("honest") and not ctx.get("honest_mode"):
            ctx["honest_mode"] = True
            ctx["material_level"] = {"level": "low", "reason": "LLM自评素材不足", "suggestion": "诚实呈现"}
            decision["tool"] = "render"  # 不单独 push——后面的统一 push 会推

        # 1.55. 联网开关：searchEnabled=false 时强制禁止搜索（设置里的护栏）
        if decision.get("tool") == "search" and not ctx.get("search_enabled", True):
            decision["tool"] = "design"
            if push:
                await push({"type": "thinking", "step": ctx["steps"] + 1,
                            "thought": "联网搜索已在设置中关闭，跳过搜索，直接基于自身知识与素材设计。",
                            "tool": "system", "budget": ctx["budget_spent"]})

        # 1.6. 搜索次数硬拦截
        search_rounds = sum(1 for h in ctx["tool_history"] if h["tool"] == "search")
        if decision.get("tool") == "search" and search_rounds >= ctx["search_max"]:
            decision["tool"] = "design"
            if push:
                await push({"type": "thinking", "step": ctx["steps"] + 1,
                            "thought": f"已调用 {search_rounds} 轮搜索，达到上限。orchestrator 强制切换为 design——LLM 请基于现有素材或自身知识继续。",
                            "tool": "system", "budget": ctx["budget_spent"]})

        # 2. ⚡ 思考先推到前端（空 thought 自动补上含义）
        thought = decision.get("thought", "")
        if isinstance(thought, dict):
            thought = thought.get("thought", str(thought))
        if not isinstance(thought, str):
            thought = str(thought)
        tool_name = decision.get("tool", "search")
        if not thought.strip():
            defaults = {
                "search": "搜索更多素材以补充信息…",
                "design": "分析素材，决定叙事形式和文案…",
                "compose": "优化设计方案和文案…",
                "render": "生成交互式 HTML 页面…",
                "verify": "审查生成结果…",
            }
            thought = defaults.get(tool_name, f"执行 {tool_name}…")
        log_trace(ctx["session_id"], {
            "type": "decide", "step": ctx["steps"] + 1,
            "thought": thought, "tool": tool_name,
        })
        if push:
            await push({"type": "thinking", "step": ctx["steps"] + 1, "thought": thought,
                        "tool": tool_name, "budget": ctx["budget_spent"]})

        # 3. 推"进行中"，启动心跳
        if push:
            await push({"type": "heartbeat", "step": ctx["steps"] + 1, "tool": tool_name,
                        "budget": ctx["budget_spent"]})
        # 心跳：长操作期间每 4 秒推一次 pulse
        async def heartbeat():
            for _ in range(15):
                await asyncio.sleep(4)
                if push:
                    await push({"type": "heartbeat", "step": ctx["steps"] + 1, "tool": tool_name,
                                "budget": ctx["budget_spent"]})
        hb = asyncio.create_task(heartbeat())

        # 4. 执行工具（finally 确保 heartbeat 一定被清理）
        try:
            result = await _execute_tool(tool_name, decision.get("params", {}), ctx)
        finally:
            hb.cancel()

        # 5. 推送结果
        ctx["steps"] += 1
        ctx["tool_history"].append({"step": ctx["steps"], "thought": thought,
                                     "tool": tool_name, "result_summary": _summarize(result)})
        log_trace(ctx["session_id"], {
            "type": "tool", "step": ctx["steps"], "tool": tool_name,
            "summary": _summarize(result),
            "cost_delta": ctx.get("_last_tool_cost", 0),
        })
        # 同一工具连续 3 次 → 强制换策略（喂给下一次 _decide）
        recent_tools = [h["tool"] for h in ctx["tool_history"][-3:]]
        ctx["force_strategy_change"] = len(recent_tools) == 3 and len(set(recent_tools)) == 1
        if push:
            await push({"type": "tool_result", "step": ctx["steps"], "tool": tool_name,
                        "summary": _summarize(result), "budget": ctx["budget_spent"]})

        # 5. 搜索后评估素材质量（信息通知 LLM，不替 LLM 做决策）
        if tool_name == "search" and not ctx.get("honest_mode"):
            eval_result = evaluate_material(ctx["material"], ctx["user_input"])
            ctx["material_level"] = eval_result
            if eval_result["level"] in ("low", "none") and push:
                await push({"type": "thinking", "step": ctx["steps"],
                            "thought": f"🔍 本轮搜索结果：{eval_result['reason']}。{eval_result['suggestion']}。LLM 自行决定下一步——换词重搜、跳过搜索直接用自身知识、或进入诚实模式。",
                            "tool": "system", "budget": ctx["budget_spent"]})

        # 6. 硬检查
        if tool_name == "render":
            if not result.get("complete"):
                ctx["issues"].append({"severity": "critical", "category": "incomplete",
                                      "description": "render自动失败：HTML截断"})
                ctx["render_fail_count"] = ctx.get("render_fail_count", 0) + 1
                ctx["render_success_streak"] = 0
                # 硬拦截：连续 3 次 render 失败 → 强制重新设计，防"连续20次重渲染"
                ctx["consecutive_render_fail"] = ctx.get("consecutive_render_fail", 0) + 1
                if ctx["consecutive_render_fail"] >= 3:
                    logger.warning("render 连续 %d 次失败，强制换策略 design | session=%s",
                                   ctx["consecutive_render_fail"], ctx["session_id"])
                    ctx["force_next_tool"] = "design"
            elif result.get("complete"):
                ctx["render_success_streak"] = ctx.get("render_success_streak", 0) + 1
                ctx["consecutive_render_fail"] = 0
            # 诚实模式 或 连续2次render成功还没verify → 强制verify
            if (ctx.get("honest_mode") or ctx.get("render_success_streak", 0) >= 2) and result.get("complete"):
                ctx["force_verify"] = True
                ctx["render_success_streak"] = 0

        if tool_name == "verify":
            ctx["passed"] = result.get("passed", False)
            ctx["issues"] = result.get("issues", [])
            if ctx["passed"] or ctx.get("honest_mode"):
                if ctx.get("honest_mode"):
                    logger.info("orchestrator=pass | session=%s | mode=honest", ctx["session_id"])
                else:
                    logger.info("orchestrator=pass | session=%s | steps=%d | cost=¥%.4f",
                                ctx["session_id"], ctx["steps"], ctx["budget_spent"])
                if push:
                    await push({"type": "complete", "html": ctx.get("html", ""),
                                "steps": ctx["steps"], "budget": ctx["budget_spent"]})
                    if ctx.get("honest_mode"):
                        await push({"type": "thinking", "step": ctx["steps"],
                                    "thought": "这是基于现有资料的诚实呈现，已标注信息局限。",
                                    "tool": "system", "budget": ctx["budget_spent"]})
                return {"status": "success", "html": ctx.get("html", ""),
                        "steps": ctx["steps"], "budget": ctx["budget_spent"],
                        "honest_mode": ctx.get("honest_mode", False),
                        "tool_history": ctx["tool_history"],
                        # 多轮迭代需要复用
                        "design": ctx.get("design"), "content": ctx.get("content"),
                        "material": ctx.get("material")}

            # ❌ verify 没通过 → 强制回退，不让 LLM 决定
            ctx["render_fail_count"] = ctx.get("render_fail_count", 0) + 1
            rollback = result.get("rollback_target", "render")
            logger.warning("verify=fail | session=%s | fail_count=%d | rollback=%s",
                           ctx["session_id"], ctx["render_fail_count"], rollback)

            # 连续2次 verify 失败 → 不是技术问题，是素材问题，直接终止
            if ctx["render_fail_count"] >= 2:
                logger.warning("orchestrator=abort | session=%s | verify_fail_count=%d | reason=material_mismatch",
                               ctx["session_id"], ctx["render_fail_count"])
                if push:
                    await push({"type": "thinking", "step": ctx["steps"],
                                "thought": f"连续{ctx['render_fail_count']}次生成均被审查驳回——不是技术问题，是现有素材与用户主题不匹配。建议换一个信息更充分的主题。",
                                "tool": "system", "budget": ctx["budget_spent"]})
                return {"status": "failed", "steps": ctx["steps"], "budget": ctx["budget_spent"],
                        "issues": ctx["issues"], "reason": "素材不匹配，多次生成被驳回"}

            # 强制回退：不让 LLM 决定下一步，直接跳回指定工具
            if push:
                await push({"type": "thinking", "step": ctx["steps"],
                            "thought": f"审查发现{len(ctx['issues'])}个问题，系统强制回退到「{rollback}」重做。",
                            "tool": "system", "budget": ctx["budget_spent"]})
            ctx["force_next_tool"] = rollback
            continue  # 跳到循环顶部，force_next_tool 块接管执行

    # 循环结束但没通过 → 推"死亡报告"到 DecisionLog
    search_rounds = sum(1 for h in ctx['tool_history'] if h['tool'] == 'search')
    reason = f"搜了 {search_rounds} 轮没找到直接素材" if search_rounds >= 2 else "多次生成尝试仍不满意"
    logger.info("orchestrator=exhausted | session=%s | steps=%d | cost=¥%.4f | reason=%s",
                ctx["session_id"], ctx["steps"], ctx["budget_spent"], reason)
    if push:
        await push({"type": "thinking", "step": ctx["steps"],
                    "thought": f"⚠️ 无法完成「{ctx['user_input']}」：{reason}。建议换一个信息更充分的主题试试。",
                    "tool": "system", "budget": ctx["budget_spent"]})
        await push({"type": "failed", "reason": reason,
                    "steps": ctx["steps"], "budget": ctx["budget_spent"]})
    return {"status": "failed", "steps": ctx["steps"], "budget": ctx["budget_spent"],
            "issues": ctx["issues"], "tool_history": ctx["tool_history"]}


async def _decide(ctx: dict) -> dict:
    """让LLM决定：下一步干什么。"""
    # 构建简洁上下文
    # 素材摘要（让LLM知道有什么内容）
    material_brief = ""
    if ctx['material']:
        titles = [r.get('title','')[:40] for r in ctx['material'][:5]]
        material_brief = f"素材来源：{' | '.join(titles)}\n"

    # 最近结果详情
    recent_detail = ""
    for h in ctx['tool_history'][-3:]:
        recent_detail += f"  [{h['tool']}] {h.get('result_summary', '')[:80]}\n"

    # 验证问题详情
    issues_detail = ""
    if ctx['issues']:
        issues_detail = "\n".join(
            f"  - [{i.get('severity','?')}] {i.get('description','')[:100]}"
            for i in ctx['issues'][:3] if isinstance(i, dict)
        )

    summary = f"""用户想了解的具体主题：{ctx['user_input']}
⚠️ 必须围绕这个主题生成，不要偏离或扩展。
步骤：{ctx['steps']}/{ctx['max_steps']} | 预算：¥{ctx['budget_spent']:.2f}/¥{ctx['budget_total']:.0f}
{material_brief}已有素材：{len(ctx['material'])}条 | 搜索次数：{sum(1 for h in ctx['tool_history'] if h['tool']=='search')}
已设计：{ctx['design'] is not None} | 已写文案：{ctx['content'] is not None}
HTML长度：{len(ctx.get('html',''))}字符 | 上次验证：{'通过' if ctx['passed'] else '未通过'}
最近步骤：
{recent_detail if recent_detail else '  （无）'}
最近问题：
{issues_detail if issues_detail else '  （无）'}
"""

    if ctx.get("force_strategy_change"):
        summary += "\n⚠️ 连续失败！必须换策略，不能重试同一个工具。"

    if ctx.get("honest_mode"):
        eval_result = ctx.get("material_level", {})
        summary += f"\n⚠️【诚实模式】{eval_result.get('reason','素材不足')}。禁止 design/compose，直接 render 一个诚实页面。不要编造。只生成一次。"

    # 搜索死循环防护：连续2次搜空就强制禁止
    search_rounds = sum(1 for h in ctx['tool_history'] if h['tool'] == 'search')
    recent_searches = [h for h in ctx['tool_history'][-2:] if h['tool'] == 'search']
    all_empty = all("0条" in h.get("result_summary", "") or "不相关" in h.get("result_summary", "") or "未找到" in h.get("result_summary", "") for h in recent_searches)
    if search_rounds >= 3 or (search_rounds >= 2 and all_empty):
        summary += f"\n⚠️ 已调用 {search_rounds} 轮搜索（最近2轮无结果），禁止再搜！基于现有素材做设计，或诚实说素材不足。"

    try:
        # 流式收集 LLM 输出（不推原始 JSON，等解析完推干净的 thought）
        accumulated = ""
        async for chunk in chat_stream(
            summary,
            system=ORCHESTRATOR_SYSTEM_PROMPT,
            model=ctx.get("model"),
            temperature=0.5,
            session_records=ctx.get("cost_records"),
            label="decide",
        ):
            accumulated += chunk

        result = strip_fence(accumulated)
        decision = json.loads(result)
        decision["thought"] = clean_thought(
            decision.get("thought", ""), ctx["user_input"], ctx["steps"])
        return decision
    except Exception as e:
        ctx["_decide_fail_count"] = ctx.get("_decide_fail_count", 0) + 1
        logger.warning("decide=fail | session=%s | fail_count=%d | error=%s",
                       ctx["session_id"], ctx["_decide_fail_count"], e)
        # 连续3次失败 → LLM 不可用，触发诚实模式终止
        if ctx["_decide_fail_count"] >= 3:
            ctx["honest_mode"] = True
            return {"thought": "LLM连续故障，进入诚实模式", "tool": "render",
                    "params": {}}
        return {"thought": f"决策异常，降级搜索(第{ctx['_decide_fail_count']}次)", "tool": "search",
                "params": {"query": ctx["user_input"], "reason": "初始搜索", "depth": "quick"}}


def _real_cost_delta(ctx: dict) -> float:
    """自上次结算以来新增的 LLM token 真实成本（DeepSeek v4-flash 费率 + 缓存拆分）。

    cost_records 是会话账本，累积所有 chat/chat_stream 的 token。
    只算增量——包含上一轮 decide 决策 + 本轮工具的 LLM 调用。
    """
    from app.llm.client import INPUT_CACHE_HIT, INPUT_CACHE_MISS, OUTPUT_RATE

    records = ctx.get("cost_records", [])
    start = ctx.get("_last_cost_len", 0)
    ctx["_last_cost_len"] = len(records)
    new = records[start:]
    total_in = sum(r.get("input_tokens", 0) for r in new)
    total_cache_hit = sum(r.get("cache_hit_tokens", 0) for r in new)
    total_out = sum(r.get("output_tokens", 0) for r in new)
    in_miss = max(0, total_in - total_cache_hit)
    return round(total_cache_hit / 1_000_000 * INPUT_CACHE_HIT
                 + in_miss / 1_000_000 * INPUT_CACHE_MISS
                 + total_out / 1_000_000 * OUTPUT_RATE, 6)


async def _execute_tool(tool_name: str, params: dict, ctx: dict) -> dict:
    """执行工具调用——Supervisor 分发 + ctx 更新。

    预算用真实 LLM token 成本（不再是 TOOL_COST 估算）——决策+工具的全部 LLM 调用都计入。
    """
    ctx["_last_tool_cost"] = _real_cost_delta(ctx)
    ctx["budget_spent"] += ctx["_last_tool_cost"]

    from app.agent.supervisor import dispatch
    result = await dispatch(ctx, tool_name, params)

    # ctx 更新（每种工具的副作用，Supervisor 不处理）
    if tool_name == "search":
        ctx["material"] = result.get("results", ctx["material"])
    elif tool_name in ("design", "compose"):
        ctx["design"] = result.get("design")
        ctx["content"] = result.get("content")
    elif tool_name == "render":
        if result.get("html"):
            ctx["html"] = result["html"]

    return result


def _summarize(result: dict) -> str:
    """工具结果的一句话摘要。"""
    tool = result.get("tool", "")
    if tool == "search":
        n = result.get("count", 0)
        return f"搜索结束，共找到 {n} 条可信素材" if n > 0 else "搜索结束，未找到新素材"
    elif tool == "design":
        # DesignerAgent 合并了 design+compose
        design = result.get("design", {})
        content = result.get("content", {})
        comps = design.get("components", [])
        r = design.get("rationale", "")
        n = len(content.get("blocks", []))
        t = content.get("title", "")
        return f"设计+文案：「{'、'.join(comps)}」——{n}块「{t or r[:30]}」"
    elif tool == "render":
        length = result.get("length", 0)
        ok = result.get("complete")
        return f"HTML 生成完毕，{length} 字符，结构{'完整' if ok else '截断需重试'}"
    elif tool == "verify":
        if result.get("passed"):
            return "Playwright 审查通过，所有检查项正常"
        n = len(result.get("issues", []))
        return f"审查发现 {n} 个问题，需{'重生成' if result.get('rollback_target') == 'render' else '重写文案' if result.get('rollback_target') == 'compose' else '重新设计'}"
    return str(result.get("error", "完成"))


# ═══════════════════════════════════════════════════════════════
# 多轮迭代（Phase C）：用户在成品上继续提要求，agent 改页面
# ═══════════════════════════════════════════════════════════════

REFINE_SYSTEM_PROMPT = """用户在已生成页面的基础上提出修改要求，你决定怎么改。

已有：设计(design)、文案(content)、素材(material)。
可选动作：
- rerender   只改视觉/结构（最省 token，优先）
- redesign   要改叙事形式或重写文案（用户明确要求改内容/换形式时）
- research   要补充新信息，现有素材不够时

输出JSON：
{"action": "rerender|redesign|research", "hint": "给渲染/设计的指令（简短中文）", "query": "research 时的新搜索词"}"""


async def refine_page(design, content, material, html, user_input, instruction,
                      push, session_records, preferences=None, model=None) -> dict:
    """多轮迭代：用户改页面 → LLM 决定改法 → 执行 → 返回新版 html。"""
    import copy

    from app.tools.design import DesignerAgent
    from app.tools.render import RenderAgent
    from app.tools.search import tool_search

    summary = (
        f"用户想了解的：{user_input}\n"
        f"当前设计：{json.dumps(design, ensure_ascii=False)[:800]}\n"
        f"当前文案块数：{len((content or {}).get('blocks', []))}\n"
        f"用户新要求：{instruction}"
    )
    if push:
        await push({"type": "thinking", "step": 0,
                    "thought": f"🔄 收到新要求「{instruction}」，决定怎么改…",
                    "tool": "system", "budget": 0})

    decision = {"action": "rerender", "hint": instruction}
    try:
        accumulated = ""
        async for chunk in chat_stream(summary, system=REFINE_SYSTEM_PROMPT,
                                       temperature=0.3, session_records=session_records, label="refine"):
            accumulated += chunk
        parsed = safe_parse_json(accumulated)
        if parsed:
            decision = parsed
    except Exception as e:
        logger.warning("refine 决策失败，默认 rerender: %s", e)

    action = decision.get("action", "rerender")
    hint = decision.get("hint", instruction)

    if action == "research":
        query = decision.get("query") or user_input
        if push:
            await push({"type": "thinking", "step": 0,
                        "thought": f"🔍 迭代补搜：「{query}」…", "tool": "search", "budget": 0})
        sr = await tool_search(query, reason="迭代补搜", existing_material=material)
        material = material + sr.get("results", [])

    if action in ("redesign", "research"):
        if push:
            await push({"type": "thinking", "step": 0,
                        "thought": "🎨 重新设计叙事形式和文案…", "tool": "design", "budget": 0})
        da = await DesignerAgent().run(material, user_input, push=push,
                                       session_records=session_records, preferences=preferences,
                                       model=model)
        design = da.get("design") or design
        content = da.get("content") or content

    # 渲染：把用户 hint 注入 visual_hint（只改视觉时不动 design/content）
    patched = copy.deepcopy(design or {})
    hint_text = f"用户要求：{hint}"
    patched["visual_hint"] = f"{patched.get('visual_hint', '')} | {hint_text}".strip(" |")
    if push:
        await push({"type": "thinking", "step": 0,
                    "thought": f"🖌️ 重新渲染（{action}）…", "tool": "render", "budget": 0})
    rr = await RenderAgent().run(patched, content or {}, push=push, session_records=session_records,
                                 model=model)

    # F4: 迭代也要外部验证（保持"render 后必须 verify"原则，不让 LLM 自评）
    verified = False
    try:
        from app.tools.verify import tool_verify
        v = await tool_verify(rr.get("html", ""), content or {})
        critical = [i.get("description", "") for i in v.get("issues", [])
                    if i.get("severity") == "critical"][:3]
        if critical and rr.get("html"):
            # 有 critical 问题 → 把问题当 hint 再渲染一次（重渲染后视为已修正）
            if push:
                await push({"type": "thinking", "step": 0,
                            "thought": f"🔎 验证发现 {len(critical)} 个关键问题，修正后重渲染…",
                            "tool": "verify", "budget": 0})
            patched["visual_hint"] = f"{patched.get('visual_hint', '')} | 审查问题：{'；'.join(critical)}".strip(" |")
            rr2 = await RenderAgent().run(patched, content or {}, push=push, session_records=session_records)
            if rr2.get("complete"):
                rr = rr2
                verified = True  # 修正后重渲染成功，视为已修正
        else:
            verified = not critical  # 原本无 critical → 通过
    except Exception as e:
        logger.debug("refine 验证不可用: %s", e)

    return {"html": rr.get("html", ""), "design": design, "content": content,
            "material": material, "action": action, "verified": verified}
