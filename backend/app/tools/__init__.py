"""工具层 — 一能力一文件：search / design(+compose) / render / verify。

每个文件包含「原始操作 + Agent 决策包装」：
- search：tool_search + ResearcherAgent（换词重试 + 向量兜底）
- design：tool_design + tool_compose + DesignerAgent（设计+文案 + 自循环）
- render：tool_render(_stream) + RenderAgent（自检 + 缓存 + 重试）
- verify：tool_verify（Playwright 真执行，无 Agent 包装）
"""

from app.tools.design import tool_compose, tool_design
from app.tools.render import tool_render, tool_render_stream
from app.tools.search import _filter_noise, tool_search
from app.tools.verify import tool_verify

__all__ = [
    "_filter_noise",
    "tool_compose",
    "tool_design",
    "tool_render",
    "tool_render_stream",
    "tool_search",
    "tool_verify",
]
