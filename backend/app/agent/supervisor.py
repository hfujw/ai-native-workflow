"""Supervisor —— 工具注册表 + 总线分发，替代 if-elif 链。

原本 orchestrator._execute_tool 是 if tool=="search": ... elif tool=="design": ...
加新工具要改三个地方（import、if-elif、_summarize）。
现在：加一个 TOOL_HANDLERS 条目即可。
"""

import logging

from app.agent.message_bus import MessageBus
from app.tools.design import DesignerAgent
from app.tools.render import RenderAgent
from app.tools.search import ResearcherAgent
from app.tools.verify import tool_verify

logger = logging.getLogger(__name__)

# ── 安全重试上限 ──
# llm_steps 默认 10，但一次 render 全量生成可达 16384 token、一次 design 是
# 3 创意脑+综合+批评+文案 ≈ 7 次 LLM 调用——直接拿 llm_steps 当工具内部重试上限会把预算烧穿。
# 用户想要的"多试试"由 orchestrator 层（verify 失败回退 / judge 回退）兜底，工具内部 2-3 次足够。
SAFE_REQUERY_CAP = 2      # search 换词：原始词 + 最多 2 次换词
SAFE_RENDER_ATTEMPTS = 3  # render 自检重试：3 次全量渲染封顶（连挂 3 次 orchestrator 强制换策略）
SAFE_DESIGN_ATTEMPTS = 2  # design/compose 重试：每次约 7 次调用，2 次封顶


def _skill_assets_for(skill_id: str | None) -> dict | None:
    """按 skill_id 加载模板资产（template.html/reference.css）。"""
    if not skill_id:
        return None
    try:
        from app.skills import load_skill
        skill = load_skill(skill_id)
        return (skill or {}).get("assets") or None
    except Exception as e:
        logger.debug("skill 资产加载失败(%s): %s", skill_id, e)
        return None


# 工具 → Agent 映射（加新工具只需加一行）。
# handler 签名：handler(ctx, bus, params)——params 是 LLM 决策携带的参数（如 search 的 query）。
TOOL_HANDLERS = {
    "search":  lambda ctx, bus, params: ResearcherAgent().run(
        topic=(params or {}).get("query") or ctx.get("user_input", ""),
        existing_material=ctx.get("material", []),
        session_records=ctx.get("cost_records"),
        push=ctx.get("_push"),  # ← 补 push：ResearcherAgent 内部换词思考也进 DecisionLog（思考透明）
        model=ctx.get("model"),
        max_requery=min(ctx.get("llm_steps") or 2, SAFE_REQUERY_CAP),  # 换词上限（防烧 token）
    ),
    "design":  lambda ctx, bus, params: DesignerAgent().run(
        ctx.get("material", []), ctx.get("user_input", ""),
        push=ctx.get("_push"), session_records=ctx.get("cost_records"),
        bus=bus,
        model=ctx.get("model"),  # ← 会话模型（前端选择）
        swarm_size=ctx.get("creative_swarm_size"),  # 创意脑数量（人海战术）
        max_attempts=min(ctx.get("llm_steps") or 2, SAFE_DESIGN_ATTEMPTS),  # 设计重试上限
    ),
    "compose": lambda ctx, bus, params: DesignerAgent().run(
        ctx.get("material", []), ctx.get("user_input", ""),
        push=ctx.get("_push"), session_records=ctx.get("cost_records"),
        bus=bus,
        model=ctx.get("model"),
        swarm_size=ctx.get("creative_swarm_size"),
        max_attempts=min(ctx.get("llm_steps") or 2, SAFE_DESIGN_ATTEMPTS),
    ),
    "render":  lambda ctx, bus, params: RenderAgent().run(
        ctx.get("design") or {}, ctx.get("content") or {},
        push=ctx.get("_push"), session_records=ctx.get("cost_records"),
        model=ctx.get("model"),
        skill_assets=_skill_assets_for(ctx.get("skill_id")),
        max_attempts=min(ctx.get("llm_steps") or 2, SAFE_RENDER_ATTEMPTS),  # 自检重试上限
    ),
    "verify":  lambda ctx, bus, params: _sync_wrap(
        tool_verify(ctx.get("html", ""), ctx.get("content") or {})
    ),
}


async def dispatch(ctx: dict, tool_name: str, params: dict | None = None) -> dict:
    """替代 orchestrator._execute_tool 的 if-elif 链。

    从 TOOL_HANDLERS 查 handler → 执行 → 返回结果。
    bus 通过 ctx["_bus"] 共享，让 Agent 之间能通信。
    params 透传给 handler——LLM 决策的参数（如 search 的 query）不再被丢弃。
    """
    handler = TOOL_HANDLERS.get(tool_name)
    if handler is None:
        return {"error": f"未知工具: {tool_name}"}

    # 确保总线条存在且共享
    bus = ctx.get("_bus")
    if bus is None:
        bus = MessageBus()
        ctx["_bus"] = bus

    try:
        result = await handler(ctx, bus, params)
    except Exception as e:
        # P3：原始异常记日志；回传友好文案——避免把内部细节（OpenAI 错误等）泄漏给前端/日志
        logger.error("Supervisor=tool_failed | tool=%s | error=%s", tool_name, e)
        result = {"error": "工具执行失败，请重试"}

    return result


async def _sync_wrap(coro):
    """包装同步结果（verify 是 async 函数但不需要 bus）。"""
    return await coro
