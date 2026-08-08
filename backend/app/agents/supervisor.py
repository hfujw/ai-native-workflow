"""Supervisor —— 工具注册表 + 总线分发，替代 if-elif 链。

原本 orchestrator._execute_tool 是 if tool=="search": ... elif tool=="design": ...
加新工具要改三个地方（import、if-elif、_summarize）。
现在：加一个 TOOL_HANDLERS 条目即可。
"""

import asyncio
import logging
from app.agents.message_bus import MessageBus
from app.agents.researcher_agent import ResearcherAgent
from app.agents.designer_agent import DesignerAgent
from app.agents.render_agent import RenderAgent
from app.tools.verify import tool_verify

logger = logging.getLogger(__name__)


# 工具 → Agent 映射（加新工具只需加一行）
TOOL_HANDLERS = {
    "search":  lambda ctx, bus: ResearcherAgent().run(
        topic=ctx.get("user_input", ""),
        existing_material=ctx.get("material", []),
        session_records=ctx.get("cost_records"),
    ),
    "design":  lambda ctx, bus: DesignerAgent().run(
        ctx.get("material", []), ctx.get("user_input", ""),
        push=ctx.get("_push"), session_records=ctx.get("cost_records"),
        bus=bus,  # ← 传总线，素材不够时Agent自己求助
    ),
    "compose": lambda ctx, bus: DesignerAgent().run(
        ctx.get("material", []), ctx.get("user_input", ""),
        push=ctx.get("_push"), session_records=ctx.get("cost_records"),
        bus=bus,
    ),
    "render":  lambda ctx, bus: RenderAgent().run(
        ctx.get("design") or {}, ctx.get("content") or {},
        push=ctx.get("_push"), session_records=ctx.get("cost_records"),
    ),
    "verify":  lambda ctx, bus: _sync_wrap(
        tool_verify(ctx.get("html", ""), ctx.get("content") or {})
    ),
}


async def dispatch(ctx: dict, tool_name: str) -> dict:
    """替代 orchestrator._execute_tool 的 if-elif 链。

    从 TOOL_HANDLERS 查 handler → 执行 → 返回结果。
    bus 通过 ctx["_bus"] 共享，让 Agent 之间能通信。
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
        result = await handler(ctx, bus)
    except Exception as e:
        logger.error("Supervisor=tool_failed | tool=%s | error=%s", tool_name, e)
        result = {"error": str(e)}

    return result


async def _sync_wrap(coro):
    """包装同步结果（verify 是 async 函数但不需要 bus）。"""
    return await coro
