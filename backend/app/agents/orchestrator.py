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
from app.core.config import settings
from app.llm.client import chat_stream
from app.llm.parser import strip_fence, clean_thought
from app.tools import tool_verify, TOOL_COST
from app.knowledge.kb import get_event_by_keyword, event_to_search_results, _name
from app.agents.evaluate import evaluate_material

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
    "budget_spent": 0.0,
    "budget_total": settings.budget_total,
    "passed": False,
    "issues": [],
    "tool_history": [],
    "cost_records": state.get("_cost_records", []),
    }

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

        # 1.6. 搜索次数硬拦截
        search_rounds = sum(1 for h in ctx["tool_history"] if h["tool"] == "search")
        if decision.get("tool") == "search" and search_rounds >= ctx["search_max"]:
            decision["tool"] = "design"
            if push:
                await push({"type": "thinking", "step": ctx["steps"] + 1,
                            "thought": f"已调用 {search_rounds} 轮搜索，达到上限。orchestrator 强制切换为 design——LLM 请基于现有素材或自身知识继续。",
                            "tool": "system", "budget": ctx["budget_spent"]})

        # 2. ⚡ 思考先推到前端（只 push 一次，且确保是纯文本）
        thought = decision.get("thought", "")
        if isinstance(thought, dict):
            thought = thought.get("thought", str(thought))
        if not isinstance(thought, str):
            thought = str(thought)
        tool_name = decision.get("tool", "search")
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
                ctx["issues"].append("render自动失败：HTML截断")
                ctx["render_fail_count"] = ctx.get("render_fail_count", 0) + 1
            # 诚实模式：render 后强制 verify，不让 LLM 再决定
            if ctx.get("honest_mode") and result.get("complete"):
                ctx["force_verify"] = True

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
                        "tool_history": ctx["tool_history"]}

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
            for i in ctx['issues'][:3]
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
        # 流式思考——前端 DecisionLog 逐字显示
        push = ctx.get("_push")
        accumulated = ""
        async for chunk in chat_stream(
            summary,
            system=ORCHESTRATOR_SYSTEM_PROMPT,
            temperature=0.5,
            session_records=ctx.get("cost_records"),
            label="decide",
        ):
            accumulated += chunk
            if push:
                await push({"type": "thinking_stream", "step": ctx["steps"] + 1,
                            "chunk": chunk, "tool": "decide", "budget": ctx["budget_spent"]})

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


async def _execute_tool(tool_name: str, params: dict, ctx: dict) -> dict:
    """执行工具调用，更新ctx。"""
    cost = TOOL_COST.get(tool_name, 0.05)
    ctx["budget_spent"] += cost

    if tool_name == "search":
        from app.agents.researcher_agent import ResearcherAgent
        result = await ResearcherAgent().run(
            topic=params.get("query", ctx["user_input"]),
            existing_material=ctx["material"],
            session_records=ctx.get("cost_records"),
        )
        ctx["material"] = result.get("results", ctx["material"])
        return result

    elif tool_name == "design" or tool_name == "compose":
        # DesignerAgent 合并 design+compose——素材不够时向 ResearcherAgent 求助
        from app.agents.designer_agent import DesignerAgent
        from app.agents.message_bus import MessageBus
        bus = ctx.get("_bus")
        if bus is None:
            bus = MessageBus()
            ctx["_bus"] = bus
        result = await DesignerAgent().run(
            ctx["material"], ctx["user_input"],
            push=ctx.get("_push"),
            session_records=ctx.get("cost_records"),
            bus=bus,
        )
        ctx["design"] = result.get("design")
        ctx["content"] = result.get("content")
        return result

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

    elif tool_name == "verify":
        result = await tool_verify(ctx.get("html", ""), ctx.get("content") or {})
        return result

    return {"error": f"未知工具: {tool_name}"}


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
