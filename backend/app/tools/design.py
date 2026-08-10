"""工具 2: design — 分析素材，决定用什么叙事形式。"""

import json
import logging

from app.llm.client import chat_json
from app.llm.parser import strip_fence

logger = logging.getLogger(__name__)

DESIGN_SYSTEM_PROMPT = """你是信息设计师。分析素材，决定用什么视觉形式呈现。

可选组件：
- timeline（时间轴）— 有明确时间顺序
- comparison（对比表）— 两个及以上对象对比
- cards（卡片集）— 人物、概念、独立条目
- flowchart（流程图）— 因果关系、步骤过程
- portrait（人物画像）— 以人物为核心
- datapanel（数据面板）— 有具体数据
- encyclopedia（百科条目）— 概念解释

你可以单选或多选组合。一个主题通常需要2-3个组件搭配。

⚠️ 如果你基于自身知识设计（而非搜索素材），在 rationale 中标注"知识来源：LLM 内部知识"。
不标注则视为基于搜索素材。

输出JSON：
{
  "components": ["timeline", "cards"],
  "rationale": "为什么选这些（注明知识来源）",
  "structure": "组件排列方式（如：顶部时间轴，下方2列卡片）",
  "visual_hint": "配色方向和情绪基调（如：秦汉黑红金、严肃厚重）"
}"""


async def tool_design(
    material: list[dict],
    user_input: str = "",
    session_records: list[dict] | None = None,
) -> dict:
    """分析素材，决定用什么叙事形式。"""
    if not material:
        return {"tool": "design", "components": ["encyclopedia"], "rationale": "无素材，仅做百科式展示",
                "structure": "单列百科条目", "visual_hint": "简洁中性"}

    brief = "\n\n".join(
        f"[{i+1}] {r.get('title','')}: {r.get('snippet', r.get('content',''))[:300]}"
        for i, r in enumerate(material[:8])
    )

    topic_hint = f"\n⚠️ 用户想了解的具体主题是「{user_input}」。只围绕这个主题设计，不要扩展成更大的话题。" if user_input else ""

    try:
        result = await chat_json(
            f"素材：\n{brief}{topic_hint}",
            system=DESIGN_SYSTEM_PROMPT,
            session_records=session_records,
        )
        result = strip_fence(result)
        design = json.loads(result)
        logger.info("工具=design | 组件=%s", design.get("components", []))
        design["tool"] = "design"
        return design
    except Exception as e:
        logger.warning("design失败: %s", e)
        return {"tool": "design", "components": ["encyclopedia"], "rationale": f"LLM异常({e})，降级为百科条目",
                "structure": "单列", "visual_hint": "默认"}
