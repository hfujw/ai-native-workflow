"""发散-收敛设计（Kimi Agent Swarm 模式最小版）。

创造时多脑发散：spawn 2-3 个创意子脑（叙事/视觉/信息）并行产出方案；
收敛时单脑综合：synthesize 把多视角合并成 1 个 design。

设计要点：
- 子脑并行（asyncio.gather），任一失败不阻塞其余（其余照常综合）
- 子脑低温度 + 小 max_tokens（成本可控，预算护栏兜底）
- 综合器保留偏好注入与诚实降级
"""

import asyncio
import json
import logging

from app.llm.client import chat_json
from app.llm.parser import safe_parse_json

logger = logging.getLogger(__name__)

# 创意子脑清单：每个视角一个 prompt 骨架
CREATIVE_ANGLES: list[dict] = [
    {
        "id": "narrative",
        "name": "叙事型",
        "system": """你是叙事设计师。从一个主题里挖出「故事线」——人物、转折、情感节奏。
你的任务是给出这个主题的叙事角度建议：用什么故事结构讲？哪些元素能制造共鸣？

可选组件：timeline（时间轴）/ portrait（人物画像）/ cards（卡片集）
输出JSON：
{"angle": "你的叙事角度（一句话）", "components": ["timeline"], "structure": "页面结构安排", "visual_hint": "情绪基调与配色方向", "rationale": "为什么这样讲"}""",
    },
    {
        "id": "visual",
        "name": "视觉型",
        "system": """你是视觉设计师。你关心的是「第一眼冲击力」——风格、色彩、排版美学。
你的任务是给出这个主题的视觉方向建议：什么风格最能表达它？色彩/字体/布局怎么选？

可选组件：cards（卡片集）/ datapanel（数据面板）/ encyclopedia（百科条目）
输出JSON：
{"angle": "你的视觉角度（一句话）", "components": ["cards"], "structure": "版式安排", "visual_hint": "具体配色方向与风格基调", "rationale": "为什么这样设计"}""",
    },
    {
        "id": "informative",
        "name": "信息型",
        "system": """你是信息架构师。你关心的是「知识的完整与可读」——覆盖哪些关键信息、怎么组织最易懂。
你的任务是给出这个主题的信息架构建议：必须讲清哪些点？用什么结构呈现最清晰？

可选组件：comparison（对比表）/ flowchart（流程图）/ datapanel（数据面板）/ encyclopedia（百科条目）
输出JSON：
{"angle": "你的信息角度（一句话）", "components": ["comparison"], "structure": "信息组织方式", "visual_hint": "克制清晰的视觉基调", "rationale": "为什么这样组织"}""",
    },
]

_FALLBACK_DESIGN = {"components": ["encyclopedia"], "rationale": "发散失败，降级为百科条目",
                    "structure": "单列百科条目", "visual_hint": "简洁中性"}


def _material_brief(material: list[dict], limit: int = 8) -> str:
    if not material:
        return "(无素材)"
    return "\n".join(
        f"[{i+1}] {r.get('title', '')}: {r.get('snippet', r.get('content', ''))[:250]}"
        for i, r in enumerate(material[:limit])
    )


async def _one_creative(
    angle: dict,
    user_input: str,
    material: list[dict],
    session_records: list[dict] | None,
    model: str | None,
) -> dict:
    """单个创意子脑——独立调用，失败返回 None 标记。"""
    try:
        prompt = f"""用户想了解：{user_input}

素材：
{_material_brief(material)}

请从「{angle['name']}」视角给出设计方案。"""
        result = await chat_json(
            prompt,
            system=angle["system"],
            session_records=session_records,
            model=model,
        )
        parsed = safe_parse_json(result)
        if parsed is None or not isinstance(parsed.get("components"), list) or not parsed["components"]:
            logger.warning("creative=%s invalid | raw=%s", angle["id"], str(result)[:80])
            return None
        parsed["_angle"] = angle["id"]
        parsed["_angle_name"] = angle["name"]
        logger.info("creative=%s done | components=%s", angle["id"], parsed.get("components", []))
        return parsed
    except Exception as e:
        logger.warning("creative=%s failed | %s", angle["id"], e)
        return None


async def spawn_creative_agents(
    user_input: str,
    material: list[dict],
    session_records: list[dict] | None = None,
    model: str | None = None,
) -> list[dict]:
    """并行 spawn 全部创意子脑。返回成功子脑的方案列表（可能为空）。"""
    results = await asyncio.gather(*[
        _one_creative(angle, user_input, material, session_records, model)
        for angle in CREATIVE_ANGLES
    ])
    return [r for r in results if r is not None]


SYNTHESIZE_SYSTEM_PROMPT = """你是主设计师。多个创意分身从不同视角给出了方案，你负责综合成最终方案。

规则：
- 合并视角：组件取并集但控制数量（2-3 个为宜），叙事/视觉/信息角度要互相补强
- 视觉方向择优：选最具体的 visual_hint（有具体配色/风格词，而不是空话）
- 结构要可执行：structure 描述页面从上到下的实际布局
- 输出必须包含 components（非空列表）

输出JSON：
{"components": ["timeline", "cards"], "structure": "顶部时间轴，下方两列卡片", "visual_hint": "黑金配色、厚重历史感", "rationale": "综合叙事+视觉+信息角度的理由"}"""


async def synthesize_design(
    plans: list[dict],
    user_input: str,
    material: list[dict],
    session_records: list[dict] | None = None,
    model: str | None = None,
    preferences: dict | None = None,
) -> dict:
    """大脑综合：把多视角方案合成 1 个 design。失败降级：取第一个有效方案。"""
    if not plans:
        return dict(_FALLBACK_DESIGN)

    if len(plans) == 1:
        # 只有一个视角成功 → 直接采用，不浪费一次综合调用
        d = dict(plans[0])
        d["rationale"] = f"{d.get('rationale', '')}（仅{d.get('_angle_name', '单视角')}视角成功）"
        d["tool"] = "design"
        return d

    pref_hint = ""
    if preferences:
        style = preferences.get("style_hints") or []
        comps = preferences.get("preferred_components") or []
        if style or comps:
            pref_hint = (f"\n⚠️ 用户偏好：风格「{'、'.join(style)}」、组件「{'、'.join(comps)}」。"
                         f"尽量遵循，与主题冲突时以主题为准。")

    try:
        plans_text = "\n\n".join(
            f"[{p.get('_angle_name', '视角')}]\n{json.dumps({k: v for k, v in p.items() if not k.startswith('_')}, ensure_ascii=False, indent=1)}"
            for p in plans
        )
        prompt = f"""用户想了解：{user_input}

素材：
{_material_brief(material)}

创意分身方案：
{plans_text}
{pref_hint}
请综合成最终方案。"""
        result = await chat_json(
            prompt,
            system=SYNTHESIZE_SYSTEM_PROMPT,
            session_records=session_records,
            model=model,
        )
        parsed = safe_parse_json(result)
        if parsed is None or not isinstance(parsed.get("components"), list) or not parsed["components"]:
            logger.warning("synthesize invalid | raw=%s", str(result)[:80])
            raise ValueError("synthesize invalid")
        parsed["tool"] = "design"
        parsed["_synthesized"] = True
        logger.info("synthesize=done | components=%s", parsed.get("components", []))
        return parsed
    except Exception as e:
        logger.warning("synthesize failed, 用第一视角方案: %s", e)
        d = dict(plans[0])
        d["tool"] = "design"
        return d


async def brainstorm_design(
    user_input: str,
    material: list[dict],
    session_records: list[dict] | None = None,
    model: str | None = None,
    preferences: dict | None = None,
) -> dict:
    """对外主入口：发散（并行子脑）→ 收敛（综合）→ 批评（批评家挑刺）→ 修正。

    批评家只在综合出真实方案时介入（1 轮），失败静默跳过（不阻塞设计）。
    """
    plans = await spawn_creative_agents(user_input, material, session_records, model)
    design = await synthesize_design(plans, user_input, material, session_records, model, preferences)
    if not design.get("_synthesized"):
        return design  # 降级方案不批评（成本优先）

    # 批评家挑刺（设计阶段，render 前）——问题零成本修正
    from app.llm.judge import critique_design
    issues = await critique_design(design, user_input, material, session_records, model)
    if issues:
        fixed = await _fix_design(design, issues, user_input, session_records, model)
        if fixed:
            design = fixed
        logger.info("brainstorm=critic_fixed | issues=%d", len(issues))
    return design


async def _fix_design(
    design: dict,
    issues: list[dict],
    user_input: str,
    session_records: list[dict] | None = None,
    model: str | None = None,
) -> dict | None:
    """按批评意见修正设计（1 次 LLM 调用），失败返回 None（沿用原设计）。"""
    try:
        issues_text = "\n".join(
            f"- [{i.get('dimension', '?')}] {i.get('problem', '')} → 改法：{i.get('fix', '')}"
            for i in issues
        )
        prompt = f"""用户想了解：{user_input}

当前设计方案：
{json.dumps({k: v for k, v in design.items() if not k.startswith('_')}, ensure_ascii=False, indent=1)}

批评意见：
{issues_text}

请修正设计，保持好的部分，只改被批评的点。"""
        result = await chat_json(
            prompt,
            system=SYNTHESIZE_SYSTEM_PROMPT,  # 复用综合器人格（主设计师）
            session_records=session_records,
            model=model,
        )
        parsed = safe_parse_json(result)
        if parsed is None or not isinstance(parsed.get("components"), list) or not parsed["components"]:
            return None
        parsed["tool"] = "design"
        parsed["_critic_fixed"] = True
        return parsed
    except Exception as e:
        logger.warning("critic_fix=failed | %s", e)
        return None
