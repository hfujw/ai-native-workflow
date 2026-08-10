"""工具 3: compose — 写叙事文案 + 来源标注。"""

import json
import logging

from app.llm.client import chat_json
from app.llm.parser import strip_fence

logger = logging.getLogger(__name__)

COMPOSE_SYSTEM_PROMPT = """你是叙事文案写手。每个事实性陈述必须标注来源和可信度。不确定的标注'据传'或'说法不一'。不编造数字/年份/人名。

输出JSON：
{
  "title": "页面标题",
  "subtitle": "副标题",
  "blocks": [
    {
      "component": "timeline",
      "position": 1,
      "html_hint": "时间轴节点，50字以内",
      "claims": [
        {"text": "秦始皇统一六国于前221年", "source": "search_1", "confidence": "high"},
        {"text": "征发民夫约百万", "source": "search_5", "confidence": "medium", "note": "单一来源，史记可能夸大"}
      ]
    }
  ],
  "fact_notes": "哪些信息确定、哪些有争议"
}"""


async def tool_compose(
    material: list[dict],
    design: dict,
    user_input: str = "",
    session_records: list[dict] | None = None,
) -> dict:
    """写叙事文案+来源标注。"""
    brief = "\n\n".join(
        f"[来源{i+1}] {r.get('title','')}: {r.get('snippet', r.get('content',''))[:400]}"
        for i, r in enumerate(material[:8])
    )

    topic_hint = f"\n⚠️ 用户想了解的具体主题是「{user_input}」。只围绕这个主题写内容，不要偏离。" if user_input else ""

    prompt = f"""素材：{brief}

设计：{json.dumps(design, ensure_ascii=False)}
{topic_hint}
为每个组件写内容。每个数字/年份/人名必须标注来源。"""

    try:
        result = await chat_json(prompt, system=COMPOSE_SYSTEM_PROMPT, session_records=session_records)
        result = strip_fence(result)
        content = json.loads(result)
        logger.info("工具=compose | blocks=%d", len(content.get("blocks", [])))
        content["tool"] = "compose"
        return content
    except Exception as e:
        logger.warning("compose失败: %s", e)
        return {"tool": "compose", "title": "生成失败", "subtitle": str(e), "blocks": [], "fact_notes": ""}
