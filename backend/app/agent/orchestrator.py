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
import re

from app.agent.evaluate import evaluate_material
from app.config import settings
from app.knowledge.kb import _name, event_to_search_results, get_event_by_keyword
from app.llm.client import chat_stream
from app.llm.parser import clean_thought, safe_parse_json, strip_fence
from app.observability.trace import log_trace
from app.skills import skill_prompt

logger = logging.getLogger(__name__)

ORCHESTRATOR_SYSTEM_PROMPT = """你是一个视觉叙事引擎。用户给你一个主题，你生成一个好看的HTML页面。

【工具】
- search(query, reason) → 搜素材（内部自动换词重搜 + 向量兜底）
- design → 设计叙事形式 + 写文案 + 标来源（一步完成）
- render → 生成HTML（内部自检 + 缓存 + 重试）
- verify → Playwright审查

【可选 skill】（和 tool 一样自由选，随 JSON 输出 skill 字段）
- 当前可用 skill 列表见下面的"可用 skill"（每步都会动态列出）
- 选一个最匹配主题的 skill；不输出 skill 字段 = 沿用当前 skill（或系统默认）

【硬规则】
- render之后必须verify
- verify通过 → 系统会自动交付并结束，你不需要输出 final（没有 final 这个工具，别再试）
- verify不通过 → 退给render或design，你来决定退给谁
- 最多20步，总预算¥1，最多搜8次
- HTML截断(缺</html>) → 自动失败，必须重render
- 同一工具连续3次失败 → 必须换策略

【决策指南】
- **你是决策中心**。orchestrator 只执行和兜底，其他决定都你来做。
- **素材（已有素材：0条）时禁止直接 design**——没有素材就没有来源可引用，"事实锚定"必挂。必须先 search。
- **有素材后**搜索才是可选的：素材够、你有把握，可直接 design。
- 不确定的话题选 search 验证。最多搜 8 次。
- 搜不到？换词重搜已在 Agent 内部处理，你只需要调 search 一次。
- design 现在一步完成设计+文案，不需要再单独调 compose。
- **已设计过（已有设计：True）就不要再 design**——直接 render 或按需 compose 优化。
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

{"thought":"3-4句自然内心独白","tool":"search|design|compose|render|verify","skill":"magazine|infographic|pixel（可选）","params":{}}"""


def apply_gen_params(ctx: dict, params: dict | None) -> None:
    """把前端设置里的生成参数（会话级）覆盖到编排上下文。

    - agentSteps  → max_steps（Agent 决策循环步数）
    - searchMax   → search_max（搜索轮数上限）
    - searchEnabled → search_enabled（False 时强制禁止搜索）
    - llmSteps    → llm_steps（每类 LLM 内部决策循环/重试的上限：
                     render 自检 / design 重试 / search 换词 / 审查回退）
    """
    p = params or {}
    if p.get("agentSteps") is not None:
        ctx["max_steps"] = min(100, max(1, int(p["agentSteps"])))  # 上限对齐 config
    if p.get("searchMax") is not None:
        ctx["search_max"] = min(20, max(0, int(p["searchMax"])))   # 上限对齐 config
    ctx["search_enabled"] = bool(p.get("searchEnabled", True))
    if p.get("llmSteps") is not None:
        ctx["llm_steps"] = min(100, max(1, int(p["llmSteps"])))
    if p.get("creativeSwarmSize") is not None:
        ctx["creative_swarm_size"] = min(6, max(1, int(p["creativeSwarmSize"])))  # 创意脑数量
    if p.get("skillId"):
        ctx["skill_id"] = str(p["skillId"])  # 风格 skill（模板资产注入渲染）


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
    "llm_steps": settings.llm_steps,   # 每类 LLM 内部循环/重试的上限
    "search_enabled": True,
    "model": None,   # 会话模型（前端 Composer 选择；无默认——模型必须前端填）
    "skill_id": None,  # 风格 skill：用户预设为初始值，LLM 决策可覆盖（v0.2 自主选 skill）
    "passed": False,
    "issues": [],
    "tool_history": [],
    "cost_records": state.get("_cost_records", []),  # 仅 token 计数（计费已砍，留作诊断）
    }

    # 前端设置里的生成参数（会话级覆盖全局配置）
    apply_gen_params(ctx, state.get("_params"))
    # 前端 Composer 选择的模型（会话级覆盖）
    if state.get("_model"):
        ctx["model"] = state["_model"]

    # 本地知识库：关键词/别名匹配（语义向量检索已砍——169 条固定话题用关键词就够，
    # 省掉 ChromaDB 依赖和首次要下载的 400MB 中文 embedding 模型）
    kb_event = get_event_by_keyword(user_input)
    if kb_event:
        ctx["material"].extend(event_to_search_results(kb_event))
        logger.info("KB命中 | session=%s | topic=%s", ctx["session_id"], _name(kb_event))

    while ctx["steps"] < ctx["max_steps"]:

        # 0. 断路器熔断检查：服务故障中 → 立即终止（不再每轮重试刷屏）
        from app.llm.circuit_breaker import State as _CBState
        from app.llm.circuit_breaker import llm_breaker
        if llm_breaker.state == _CBState.OPEN:
            ctx["_circuit_open"] = True
            break

        # 0. 诚实模式 render 后强制 verify
        if ctx.get("force_verify"):
            ctx.pop("force_verify")
            decision = {"thought": "诚实模式：自动验证", "tool": "verify", "params": {}}
        elif ctx.get("force_next_tool"):
            # 强制回退：跳过 LLM 决策，直接执行指定工具
            tool_name = ctx.pop("force_next_tool")
            if push:
                await push({"type": "tool_result", "step": ctx["steps"] + 1, "tool": tool_name,
                            "summary": f"强制回退执行 {tool_name}…"})
            result = await _execute_tool(tool_name, {}, ctx)  # 不依赖上一轮的旧 params
            ctx["steps"] += 1
            ctx["tool_history"].append({"step": ctx["steps"], "tool": tool_name,
                                        "result_summary": _summarize(result)})
            if push:
                await push({"type": "tool_result", "step": ctx["steps"], "tool": tool_name,
                            "summary": _summarize(result), "detail": _tool_detail(result)})
            continue
        else:
            # 1. 让LLM决定下一步
            decision = await _decide(ctx, push)

        # 1.4. 零素材防呆：还没搜过、也没素材 → 不允许直接 design（否则设计师拿到空素材降级百科，
        #      "事实锚定"必挂）。LLM 觉得"有把握"也要先 search 一次拿素材，除非它主动诚实。
        #      KB 命中的素材也算（ctx['material'] 非空即视为有素材）。
        searched = sum(1 for h in ctx["tool_history"] if h["tool"] == "search")
        if (not ctx["material"] and searched == 0 and not ctx.get("honest_mode")
                and decision.get("tool") in ("design", "compose")):
            decision = {"thought": "当前没有任何素材——先搜索确认关键事实，不能凭印象直接设计（避免零素材降级百科）。",
                        "tool": "search", "params": {"query": ctx.get("user_input", "")}}
            if push:
                await push({"type": "thinking", "step": ctx["steps"] + 1,
                            "thought": "还没有素材——先搜索关键事实，再进入设计。", "tool": "system"})

        # 1.45. LLM 自主选 skill（和选 tool 一样）：decision.skill → 更新 ctx.skill_id
        # 用户预设是初始值，LLM 可覆盖；只认真实存在的风格 skill id（动态白名单，防注入）
        skill_choice = str(decision.get("skill") or "").strip()
        if skill_choice:
            from app.skills import list_skills
            valid_skill_ids = {s.get("id") for s in list_skills("风格")}
            if skill_choice in valid_skill_ids and ctx.get("skill_id") != skill_choice:
                ctx["skill_id"] = skill_choice
                if push:
                    await push({"type": "thinking", "step": ctx["steps"] + 1,
                                "thought": f"🎨 自主选定风格：{skill_choice}——按此风格编排后续生成。",
                                "tool": "system"})

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
                            "tool": "system"})

        # 1.6. 搜索次数硬拦截
        search_rounds = sum(1 for h in ctx["tool_history"] if h["tool"] == "search")
        if decision.get("tool") == "search" and search_rounds >= ctx["search_max"]:
            decision["tool"] = "design"
            if push:
                await push({"type": "thinking", "step": ctx["steps"] + 1,
                            "thought": f"已调用 {search_rounds} 轮搜索，达到上限。orchestrator 强制切换为 design——LLM 请基于现有素材或自身知识继续。",
                            "tool": "system"})

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
                        "tool": tool_name})

        # 3. 推"进行中"，启动心跳
        if push:
            await push({"type": "heartbeat", "step": ctx["steps"] + 1, "tool": tool_name})
        # 心跳：长操作期间每 4 秒推一次 pulse
        async def heartbeat():
            for _ in range(15):
                await asyncio.sleep(4)
                if push:
                    await push({"type": "heartbeat", "step": ctx["steps"] + 1, "tool": tool_name})
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
        })
        # 同一工具连续 3 次 → 强制换策略（喂给下一次 _decide）
        recent_tools = [h["tool"] for h in ctx["tool_history"][-3:]]
        ctx["force_strategy_change"] = len(recent_tools) == 3 and len(set(recent_tools)) == 1
        # 通用工具失败检测：连续 3 次失败 → 也强制换策略（防工具坏了仍空转烧 decide token。
        # supervisor 把工具异常吞成 {"error": ...}，这里补上计数——否则 Agent 会一直重试同一个坏工具）
        if result.get("error"):
            ctx["consecutive_tool_fail"] = ctx.get("consecutive_tool_fail", 0) + 1
            if ctx["consecutive_tool_fail"] >= 3:
                ctx["force_strategy_change"] = True
        else:
            ctx["consecutive_tool_fail"] = 0
        if push:
            await push({"type": "tool_result", "step": ctx["steps"], "tool": tool_name,
                        "summary": _summarize(result), "detail": _tool_detail(result)})

        # 5. 搜索后评估素材质量（信息通知 LLM，不替 LLM 做决策）
        if tool_name == "search" and not ctx.get("honest_mode"):
            eval_result = evaluate_material(ctx["material"], ctx["user_input"])
            ctx["material_level"] = eval_result
            if eval_result["level"] in ("low", "none") and push:
                await push({"type": "thinking", "step": ctx["steps"],
                            "thought": f"🔍 本轮搜索结果：{eval_result['reason']}。{eval_result['suggestion']}。LLM 自行决定下一步——换词重搜、跳过搜索直接用自身知识、或进入诚实模式。",
                            "tool": "system"})

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
            # 诚实模式 或 render 成功 → 强制 verify（"render 后必须 verify"是硬规则，
            # 不让 LLM 自己决定——否则 LLM 会在 render 成功后又拉回去重设计，页面生成了却不终止）
            if (ctx.get("honest_mode") or ctx.get("render_success_streak", 0) >= 1) and result.get("complete"):
                ctx["force_verify"] = True
                ctx["render_success_streak"] = 0

        if tool_name == "verify":
            ctx["passed"] = result.get("passed", False)
            ctx["issues"] = result.get("issues", [])
            if ctx["passed"] or ctx.get("honest_mode"):
                # ── 诚实模式：直接交付（素材不足已降级，不做美学批评）──
                if ctx.get("honest_mode"):
                    logger.info("orchestrator=pass | session=%s | mode=honest", ctx["session_id"])
                    if push:
                        await push({"type": "complete", "html": ctx.get("html", ""),
                                    "steps": ctx["steps"]})
                        await push({"type": "thinking", "step": ctx["steps"],
                                    "thought": "这是基于现有资料的诚实呈现，已标注信息局限。",
                                    "tool": "system"})
                    return {"status": "success", "html": ctx.get("html", ""),
                            "steps": ctx["steps"],
                            "honest_mode": True,
                            "tool_history": ctx["tool_history"],
                            "design": ctx.get("design"), "content": ctx.get("content"),
                            "material": ctx.get("material")}

                # ── 正常模式：verify 通过 → 四维质量审查（事实/覆盖/可读/美学）──
                if settings.judge_enabled:
                    from app.llm.judge import judge_page, pick_rollback
                    if push:
                        await push({"type": "thinking", "step": ctx["steps"] + 1,
                                    "thought": "页面结构与事实通过验证，进入质量审查…",
                                    "tool": "judge"})
                    verdict = await judge_page(
                        ctx["user_input"], ctx.get("design"), ctx.get("content"),
                        ctx.get("material", []), ctx.get("html", ""),
                        session_records=ctx.get("cost_records"), model=ctx.get("model"),
                    )
                    # 回退上限：用户拍板 ≤2 轮（judge_max_retries），同时不超 llm_steps
                    judge_limit = min(ctx.get("llm_steps", settings.llm_steps), settings.judge_max_retries)
                    # 审查卡片必须有收尾——judge 内联执行不经过 _execute_tool，
                    # 不推 tool_result 前端会永久"进行中"+ 光标一直闪
                    if push:
                        issues_text = "\n".join(
                            f"· [{i.get('dimension')}] {i.get('desc', '')}" for i in verdict.get("issues", [])[:10]
                        )
                        await push({"type": "tool_result", "step": ctx["steps"] + 1, "tool": "judge",
                                    "summary": "质量审查通过" if verdict["passed"]
                                               else f"质量审查发现 {len(verdict['issues'])} 个问题",
                                    "detail": issues_text or ("全部维度通过" if verdict["passed"] else "")})
                    # 只有 issues 里含事实/覆盖严重问题才强制回退——纯可读/美学/教育问题不阻塞交付
                    # （judge 是"挑刺模式"，可读/美学问题永远挑得出；若都回退会死循环烧步数）
                    serious_issues = [
                        i for i in verdict.get("issues", [])
                        if isinstance(i, dict) and i.get("dimension") in ("fact", "coverage")
                    ]
                    if not verdict["passed"] and serious_issues and ctx.get("judge_fail_count", 0) < judge_limit:
                        ctx["judge_fail_count"] = ctx.get("judge_fail_count", 0) + 1
                        target = pick_rollback(verdict["issues"])
                        logger.info("orchestrator=judge_retry | session=%s | round=%d | target=%s",
                                    ctx["session_id"], ctx["judge_fail_count"], target)
                        if push:
                            await push({"type": "thinking", "step": ctx["steps"] + 1,
                                        "thought": f"质量审查发现 {len(verdict['issues'])} 个严重问题（事实/覆盖），退回「{target}」重做。",
                                        "tool": "judge"})
                        ctx["force_next_tool"] = target
                        continue
                    if not verdict["passed"]:
                        if push:
                            await push({"type": "thinking", "step": ctx["steps"] + 1,
                                        "thought": "质量审查多轮未通过，诚实交付当前版本。",
                                        "tool": "system"})

                logger.info("orchestrator=pass | session=%s | steps=%d",
                            ctx["session_id"], ctx["steps"])

                # 产物质量自动打分（五维底线：信息架构/视觉层次/段落/事实锚定/互动）——
                # 客观判定，不靠肉眼；<3/5 记日志，便于复盘调 prompt
                from app.observability.artifact_quality import assess_artifact
                quality = assess_artifact(ctx.get("html", ""))

                if push:
                    await push({"type": "complete", "html": ctx.get("html", ""),
                                "steps": ctx["steps"], "quality": quality.get("score", 0)})
                return {"status": "success", "html": ctx.get("html", ""),
                        "steps": ctx["steps"],
                        "quality": quality.get("score", 0),
                        "quality_results": quality.get("results", {}),
                        "honest_mode": False,
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
                                "tool": "system"})
                return {"status": "failed", "steps": ctx["steps"],
                        "issues": ctx["issues"], "reason": "素材不匹配，多次生成被驳回"}

            # 强制回退：不让 LLM 决定下一步，直接跳回指定工具
            if push:
                await push({"type": "thinking", "step": ctx["steps"],
                            "thought": f"审查发现{len(ctx['issues'])}个问题，系统强制回退到「{rollback}」重做。",
                            "tool": "system"})
            ctx["force_next_tool"] = rollback
            continue  # 跳到循环顶部，force_next_tool 块接管执行

    # 循环结束但没通过 → 推"死亡报告"到 DecisionLog
    if ctx.get("_circuit_open"):
        # 断路器熔断：AI 服务故障中，快速失败（不是素材问题，重试只会刷屏）
        reason = "AI 服务暂时不可用（连续失败已熔断），请稍后重试"
        logger.warning("orchestrator=circuit_open | session=%s | steps=%d",
                       ctx["session_id"], ctx["steps"])
    else:
        search_rounds = sum(1 for h in ctx['tool_history'] if h['tool'] == 'search')
        reason = f"搜了 {search_rounds} 轮没找到直接素材" if search_rounds >= 2 else "多次生成尝试仍不满意"
        logger.info("orchestrator=exhausted | session=%s | steps=%d | reason=%s",
                    ctx["session_id"], ctx["steps"], reason)
    if push:
        await push({"type": "thinking", "step": ctx["steps"],
                    "thought": f"⚠️ 无法完成「{ctx['user_input']}」：{reason}。建议换一个信息更充分的主题试试。",
                    "tool": "system"})
        await push({"type": "failed", "reason": reason,
                    "steps": ctx["steps"]})
    return {"status": "failed", "steps": ctx["steps"],
            "issues": ctx["issues"], "tool_history": ctx["tool_history"],
            "reason": reason}


def _extract_thought(text: str) -> str | None:
    """从累积的 decide JSON 文本里尽量提取 thought 字段值（可能不完整）。

    - 还没看到 `"thought": "` → 返回 None（还没开始生成 thought）
    - 已看到、值未闭合 → 返回已见部分（供前端"长出来"）
    - 已闭合 → 返回完整 thought
    转义（\\、\" 等）保留原样——最终 thinking 推送会用解析后的干净 thought 覆盖。
    """
    m = re.search(r'"thought"\s*:\s*"', text)
    if not m:
        return None
    i = m.end()
    out: list[str] = []
    while i < len(text):
        ch = text[i]
        if ch == "\\":  # 转义序列（\\ 或 \"）——整体跳过，不误判为闭合引号
            if i + 1 < len(text):
                out.append(text[i] + text[i + 1])
                i += 2
                continue
            break
        if ch == '"':  # 未转义的引号 → thought 值闭合
            break
        out.append(ch)
        i += 1
    return "".join(out)


async def _decide(ctx: dict, push=None) -> dict:
    """让LLM决定：下一步干什么。

    严谨性设计（批次 C）：
    - 前缀稳定：主题/步数/预算/状态段固定顺序不变（KV 缓存友好）
    - 增量反馈：最近 2 步工具结果结构化回填（模型真正"看到"上一步）
    - 容错：safe_parse_json（半截 JSON 重试一次，不再裸 json.loads 立即降级）
    - 实时流：LLM 边生成，边把 thought 增量推给前端（JSON 里 thought 在前，渐进提取）——
      decide 期间屏幕不再干等，卡片逐字"长出来"
    """
    # ── 稳定前缀（不变，利于 KV 缓存复用）──
    material_brief = ""
    if ctx['material']:
        titles = [r.get('title', '')[:40] for r in ctx['material'][:5]]
        material_brief = f"素材来源：{' | '.join(titles)}\n"

    summary = f"""用户想了解的具体主题：{ctx['user_input']}
⚠️ 必须围绕这个主题生成，不要偏离或扩展。
步骤：{ctx['steps']}/{ctx['max_steps']}
{material_brief}已有素材：{len(ctx['material'])}条 | 搜索次数：{sum(1 for h in ctx['tool_history'] if h['tool']=='search')}
已设计：{ctx['design'] is not None} | 已写文案：{ctx['content'] is not None}
HTML长度：{len(ctx.get('html', ''))}字符 | 上次验证：{'通过' if ctx['passed'] else '未通过'}
"""

    # ── 可用 skill（动态：新装的 skill 自动进 LLM 视野，不硬编码）──
    from app.skills import list_skills
    style_skills = list_skills("风格")
    if style_skills:
        lines = ["可用 skill（选一个最匹配主题的，或沿用当前）："]
        for s in style_skills:
            lines.append(f"- {s.get('id')}（{s.get('name','')}）→ {s.get('desc','')[:60]}")
        summary += "\n".join(lines) + "\n"

    # ── 增量尾部：最近 2 步的结构化反馈（模型"看到"上一步再决策）──
    feedback = _step_feedback(ctx)
    if feedback:
        summary += f"最近执行反馈：\n{feedback}\n"

    # 验证问题详情（尾部追加）
    issues_detail = ""
    if ctx['issues']:
        issues_detail = "\n".join(
            f"  - [{i.get('severity', '?')}] {i.get('description', '')[:100]}"
            for i in ctx['issues'][:3] if isinstance(i, dict)
        )
    if issues_detail:
        summary += f"最近问题：\n{issues_detail}\n"

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
        prev_visible = ""
        async for chunk in chat_stream(
            summary,
            system=skill_prompt("core", ORCHESTRATOR_SYSTEM_PROMPT),
            model=ctx.get("model"),
            temperature=0.5,
            session_records=ctx.get("cost_records"),
            label="decide",
        ):
            accumulated += chunk
            # 决策实时流：边收边把 thought 新增片段推给前端（JSON 里 thought 在前，渐进提取）
            if push:
                visible = _extract_thought(accumulated)
                if visible and len(visible) > len(prev_visible):
                    delta = visible[len(prev_visible):]
                    prev_visible = visible
                    if delta:
                        await push({"type": "thinking_stream", "step": ctx["steps"] + 1,
                                    "chunk": delta, "tool": "think"})

        result = strip_fence(accumulated)
        decision = safe_parse_json(result)
        # 半截 JSON 容错：解析失败重试一次（带"必须输出完整 JSON"提示）
        if decision is None:
            logger.warning("decide=parse_failed 重试一次 | session=%s", ctx["session_id"])
            retry = ""
            async for chunk in chat_stream(
                summary + "\n⚠️ 上次输出不是合法 JSON。这次只输出一个完整 JSON 对象，不要任何额外文字。",
                system=skill_prompt("core", ORCHESTRATOR_SYSTEM_PROMPT),
                model=ctx.get("model"),
                temperature=0.3,
                session_records=ctx.get("cost_records"),
                label="decide_retry",
            ):
                retry += chunk
            decision = safe_parse_json(strip_fence(retry))
        if decision is None or not isinstance(decision, dict) or not decision.get("tool"):
            raise ValueError("decide 解析失败")
        decision["thought"] = clean_thought(
            decision.get("thought", ""), ctx["user_input"], ctx["steps"])
        return decision
    except Exception as e:
        # 配置错误（未填 API Key）→ 直接上抛，让 generate.py 快速失败并提示用户
        # （不是临时故障，降级/重试只会卡到超时）
        from app.llm.client import LLMNotConfiguredError
        if isinstance(e, LLMNotConfiguredError):
            raise
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


def _step_feedback(ctx: dict) -> str:
    """最近 2 步工具结果的增量反馈（结构化，让模型看到上一步再决策）。

    每行固定格式：`[工具] 关键产出`——只取最近 2 步，控制 token 增量。
    """
    lines = []
    for h in ctx['tool_history'][-2:]:
        tool = h.get('tool', '?')
        summary_text = h.get('result_summary', '')[:120]
        lines.append(f"  [{tool}] {summary_text}")
    return "\n".join(lines)


async def _execute_tool(tool_name: str, params: dict, ctx: dict) -> dict:
    """执行工具调用——Supervisor 分发 + ctx 更新。"""
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


def _tool_detail(result: dict) -> str:
    """工具的实际产出（给用户看"干了什么"）——搜索素材列表、设计方案、验证问题。

    和 _summarize（一句话摘要）配合：摘要给卡片行内，detail 给展开卡正文。
    """
    tool = result.get("tool", "")
    if tool == "search":
        results = result.get("results", []) or []
        if not results:
            return "（未找到可用素材）"
        lines = []
        for i, r in enumerate(results[:10], 1):
            t = (r.get("title") or "").strip()
            url = (r.get("url") or "").strip()
            snip = (r.get("snippet") or r.get("content") or "").strip()[:100]
            lines.append(f"{i}. {t}")
            if url:
                lines.append(f"   {url}")
            if snip:
                lines.append(f"   {snip}")
        if len(results) > 10:
            lines.append(f"… 共 {len(results)} 条素材")
        return "\n".join(lines)
    if tool in ("design", "compose"):
        design = result.get("design") or {}
        if not design:
            return ""
        return (f"组件：{'、'.join(design.get('components', []) or [])}\n"
                f"结构：{design.get('structure', '')}\n"
                f"视觉：{design.get('visual_hint', '')}")
    if tool == "verify":
        issues = result.get("issues", []) or []
        if not issues:
            return "全部检查项通过"
        return "\n".join(f"· [{i.get('severity')}] {i.get('description', '')}" for i in issues[:10])
    return ""


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
                      push, session_records, model=None) -> dict:
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
                    "tool": "system"})

    decision = {"action": "rerender", "hint": instruction}
    try:
        accumulated = ""
        async for chunk in chat_stream(summary, system=skill_prompt("refine", REFINE_SYSTEM_PROMPT),
                                       temperature=0.3, session_records=session_records,
                                       model=model, label="refine"):
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
                        "thought": f"🔍 迭代补搜：「{query}」…", "tool": "search"})
        sr = await tool_search(query, reason="迭代补搜", existing_material=material)
        material = material + sr.get("results", [])

    if action in ("redesign", "research"):
        if push:
            await push({"type": "thinking", "step": 0,
                        "thought": "🎨 重新设计叙事形式和文案…", "tool": "design"})
        da = await DesignerAgent().run(material, user_input, push=push,
                                       session_records=session_records, model=model)
        design = da.get("design") or design
        content = da.get("content") or content

    # 渲染：把用户 hint 注入 visual_hint（只改视觉时不动 design/content）
    patched = copy.deepcopy(design or {})
    hint_text = f"用户要求：{hint}"
    patched["visual_hint"] = f"{patched.get('visual_hint', '')} | {hint_text}".strip(" |")
    if push:
        await push({"type": "thinking", "step": 0,
                    "thought": f"🖌️ 重新渲染（{action}）…", "tool": "render"})
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
                            "tool": "verify"})
            patched["visual_hint"] = f"{patched.get('visual_hint', '')} | 审查问题：{'；'.join(critical)}".strip(" |")
            rr2 = await RenderAgent().run(patched, content or {}, push=push, session_records=session_records,
                                          model=model)
            if rr2.get("complete"):
                rr = rr2
                verified = True  # 修正后重渲染成功，视为已修正
        else:
            verified = not critical  # 原本无 critical → 通过
    except Exception as e:
        logger.debug("refine 验证不可用: %s", e)

    return {"html": rr.get("html", ""), "design": design, "content": content,
            "material": material, "action": action, "verified": verified}
