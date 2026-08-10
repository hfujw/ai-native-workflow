"""工具 4: render — 生成 HTML（支持流式）。"""

import json
import logging
import time as _time

from app.llm.client import chat, chat_stream
from app.llm.parser import strip_fence

logger = logging.getLogger(__name__)

# 注意：使用 {{design}} 双花括号占位，避免与 JSON 中的单花括号冲突
RENDER_SYSTEM_PROMPT = """生成一个好看的交互式HTML页面。

【结构】
{{design}}

【内容】
{{content}}

【视觉方向】
{{visual}}

【规则】
- 450行以内，CSS精简，动画最多1个
- 不用外部库
- 必须有</html>
- 直接输出完成HTML，不要```包裹

【绝对禁止】
- 如果素材为空且你对话题无把握：只输出纯文本说明"关于「xxx」的公开资料有限，当前无法生成完整叙事。"
- 禁止在无素材时编造任何事实、数字、年份、人名、地名。
- 不确定的内容可以标注"据传""说法不一"，但不允许凭空构造。"""


async def tool_render(
    design: dict,
    content: dict,
    visual: dict = None,
    session_records: list[dict] | None = None,
) -> dict:
    """生成HTML。返回html字符串+完整性标记。"""
    visual = visual or {}
    visual_block = ""
    if visual.get("reference_css"):
        visual_block = f"参考CSS：\n{visual['reference_css'][:800]}"
    if visual.get("palette"):
        visual_block += f"\n色板：{', '.join(visual['palette'])}"

    # 用 replace 而不是 format，避免 JSON 字符串中的 {} 被误解析
    prompt = (
        RENDER_SYSTEM_PROMPT
        .replace("{{design}}", json.dumps(design, ensure_ascii=False, indent=2))
        .replace("{{content}}", json.dumps(content, ensure_ascii=False, indent=2))
        .replace("{{visual}}", visual_block or "由你自由发挥")
    )

    try:
        code = await chat(
            prompt,
            system="你是前端工程师。直接输出完整HTML。",
            temperature=0.3,
            session_records=session_records,
        )
        code = strip_fence(code)
        if not code.lower().startswith("<!doctype"):
            code = f"<!DOCTYPE html>\n{code}"

        is_complete = "</html>" in code
        logger.info("工具=render | %d chars | 完整=%s", len(code), is_complete)
        return {"tool": "render", "html": code, "complete": is_complete, "length": len(code)}
    except Exception as e:
        logger.error("render失败: %s", e)
        return {"tool": "render", "html": "<!DOCTYPE html><html><body><h1>生成失败</h1><p>AI 暂时无法完成这个页面，请稍后重试。</p></body></html>",
                "complete": True, "length": 0, "error": str(e)}


async def tool_render_stream(
    design: dict,
    content: dict,
    visual: dict = None,
    session_records: list[dict] | None = None,
):
    """流式生成HTML——逐段 yield，前端 iframe 实时看到页面"长出来"。

    用法：
        async for frame in tool_render_stream(design, content):
            if frame["complete"]:
                result = frame   # 最终结果，同 tool_render 返回格式
            else:
                push({"type": "html_chunk", "html": frame["html"]})
    """
    visual = visual or {}
    visual_block = ""
    if visual.get("reference_css"):
        visual_block = f"参考CSS：\n{visual['reference_css'][:800]}"
    if visual.get("palette"):
        visual_block += f"\n色板：{', '.join(visual['palette'])}"

    prompt = (
        RENDER_SYSTEM_PROMPT
        .replace("{{design}}", json.dumps(design, ensure_ascii=False, indent=2))
        .replace("{{content}}", json.dumps(content, ensure_ascii=False, indent=2))
        .replace("{{visual}}", visual_block or "由你自由发挥")
    )

    try:
        accumulated = ""
        last_push = _time.monotonic()
        async for chunk in chat_stream(
            prompt,
            system="你是前端工程师。直接输出完整HTML。",
            temperature=0.3,
            session_records=session_records,
            label="render",
        ):
            accumulated += chunk
            now = _time.monotonic()
            # 标签完整性优先，但超过 2 秒没推就强制推（防止 CSS 大段文本卡住）
            if (len(accumulated) > 300 and ">" in accumulated) or (now - last_push > 2.0):
                yield {"tool": "render", "html": accumulated, "complete": False}
                last_push = now

        code = strip_fence(accumulated)
        # 用 lstrip 防止换行/空格导致 startswith 失败，重复添加 DOCTYPE
        if not code.lstrip().lower().startswith("<!doctype"):
            code = f"<!DOCTYPE html>\n{code}"

        is_complete = "</html>" in code
        logger.info("工具=render_stream | %d chars | 完整=%s", len(code), is_complete)
        yield {"tool": "render", "html": code, "complete": is_complete, "length": len(code)}

    except Exception as e:
        logger.error("render流式失败: %s", e)
        yield {"tool": "render", "html": "<!DOCTYPE html><html><body><h1>生成失败</h1><p>请稍后重试</p></body></html>",
               "complete": True, "length": 0, "error": str(e)}
