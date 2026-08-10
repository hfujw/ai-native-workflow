"""5 个工具 — 编排 LLM 按需调用。每个工具独立、可单独测试。"""

from app.tools.compose import tool_compose
from app.tools.design import tool_design
from app.tools.render import tool_render, tool_render_stream
from app.tools.search import _filter_noise, tool_search
from app.tools.verify import tool_verify

# ── 预算（估算）──
TOOL_COST = {"search": 0.03, "design": 0.13, "render": 0.15, "verify": 0.05}  # design = design+compose 合并

__all__ = [
    "TOOL_COST",
    "_filter_noise",
    "tool_compose",
    "tool_design",
    "tool_render",
    "tool_render_stream",
    "tool_search",
    "tool_verify",
]
