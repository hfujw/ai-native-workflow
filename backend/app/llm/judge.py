"""质量审查器——四维对抗审查（C 方案：独立调用 + 挑刺模式）。

维度：
- fact:      事实核查——页面断言 vs 素材，找无依据/矛盾的表述（补上 verify 缺失的真核查）
- coverage:  覆盖度——主题关键信息是否讲全
- readability: 可读性——通俗易懂、像讲给人听，而非信息转储
- aesthetic: 美学——视觉方案是否具体、协调、有艺术感

设计要点：
- 挑刺模式：不评分，只找具体缺陷（每条可指导修改），找不出 = 通过
- 独立调用：复用会话模型，但用独立的"质检员"人格（低温度），与生成调用对抗
- 审查失败（解析异常等）→ 默认通过，不阻塞交付
- 诚实模式页面不审查（素材不足已降级，无需美学批评）
"""

import json
import logging

from app.llm.client import chat_json
from app.llm.circuit_breaker import CircuitOpenError
from app.llm.parser import safe_parse_json
from app.skills import skill_prompt

logger = logging.getLogger(__name__)

JUDGE_SYSTEM_PROMPT = """你是严格的质检员，审查一个 AI 生成的知识页面。你的任务不是打分，而是**挑刺**——找出具体缺陷，每条必须能直接指导修改（指出位置和改法）。

四维审查：
1. 事实核查：页面中的每个数字/年份/断言，与提供的素材对照。找出：无素材依据的断言、与素材矛盾的表述。没有素材支撑的断言必须标出。（如果素材为空：检查页面是否诚实标注"资料有限"，而不是编造）
2. 覆盖度：用户想了解的主题，关键信息是否讲全？有没有明显的空洞？
3. 可读性：是否通俗易懂？有没有生硬术语堆砌、大段枯燥陈列？是否像"讲给人听"而不是"信息转储"？
4. 美学：视觉方案是否具体、协调、有艺术感？版式、色彩、留白、层级是否有明确设计？（根据视觉方案描述与页面结构特征判断）

规则：
- 至少找出 3 条具体缺陷；如果实在挑不出，则 passed=true
- 每条 issue 必须给出：维度、建议回退到哪个环节、具体描述（位置+问题+改法）
- 回退目标：事实/覆盖问题 → search 或 compose；可读性问题 → compose；美学问题 → design 或 render
- passed=false **仅当**存在事实或覆盖的严重问题；纯可读/美学问题视为可优化，passed=true 但仍列出 issues

输出 JSON：
{"passed": true/false, "issues": [{"dimension": "fact|coverage|readability|aesthetic", "target": "search|design|compose|render", "desc": "具体缺陷描述"}]}"""


CRITIQUE_SYSTEM_PROMPT = """你是方案批评家。设计还没开始做，你提前挑刺——找出方案里的结构性问题，让修改成本为零。

审查维度：
1. 形式是否合适：所选组件真的能表达这个主题吗？（比如没有时间顺序却用时间轴）
2. 视觉是否具体：visual_hint 是具体的设计方向，还是"简洁大方"这种空话？
3. 结构是否完整：页面从上到下讲得通吗？有没有明显的空洞？
4. 素材是否匹配：方案要求的素材量，现有素材够吗？

规则：
- 只挑真问题，每条给出「怎么改」的具体建议
- 找不到大问题就返回空列表（不要为了挑刺而挑刺）
- 输出 JSON：{"issues": [{"dimension": "form|visual|structure|material", "problem": "问题", "fix": "改法"}]}
- 最多 3 条，宁缺毋滥"""


async def critique_design(
    design: dict | None,
    user_input: str,
    material: list[dict],
    session_records: list[dict] | None = None,
    model: str | None = None,
) -> list[dict]:
    """设计阶段批评：render 前挑刺，返回 issues 列表（空=通过）。

    失败时返回 []（批评不阻塞设计）。
    """
    if not design:
        return []
    try:
        result = await chat_json(
            f"用户想了解：{user_input}\n\n设计方案：\n{json.dumps(design, ensure_ascii=False)[:800]}\n\n素材：\n{_material_brief_for_critique(material)}",
            system=skill_prompt("critique", CRITIQUE_SYSTEM_PROMPT),
            session_records=session_records,
            model=model,
        )
        parsed = safe_parse_json(result)
        issues = parsed.get("issues", []) if isinstance(parsed, dict) else []
        issues = [i for i in issues if isinstance(i, dict) and i.get("problem")][:3]
        logger.info("critique=done | issues=%d", len(issues))
        return issues
    except CircuitOpenError:
        raise  # 服务熔断中——不静默放行，让编排层快速失败
    except Exception as e:
        logger.warning("critique=failed | %s", e)
        return []


def _material_brief_for_critique(material: list[dict], limit: int = 5) -> str:
    if not material:
        return "(无素材)"
    return "\n".join(
        f"[{i+1}] {r.get('title', '')}: {r.get('snippet', r.get('content', ''))[:150]}"
        for i, r in enumerate(material[:limit])
    )


def _html_meta(html: str) -> str:
    """HTML 的结构特征摘要（不塞全文——LLM 看源码评美学不靠谱，看特征）。"""
    if not html:
        return "(无页面)"
    css_lines = html.count(";")
    has_anim = "@keyframes" in html or "transition" in html
    has_gradient = "linear-gradient" in html or "radial-gradient" in html
    fonts = set()
    for key in ("font-family", "sans-serif", "serif", "monospace"):
        if key in html:
            fonts.add(key)
    return (f"页面长度 {len(html)} 字符 · CSS 声明约 {css_lines} 条"
            f" · 动画 {'有' if has_anim else '无'} · 渐变 {'有' if has_gradient else '无'}"
            f" · 字体线索 {','.join(sorted(fonts)) or '无'}")


async def judge_page(
    user_input: str,
    design: dict | None,
    content: dict | None,
    material: list[dict],
    html: str,
    session_records: list[dict] | None = None,
    model: str | None = None,
) -> dict:
    """四维审查。返回 {passed, issues}；审查自身失败时默认通过。"""
    blocks = (content or {}).get("blocks", []) or []
    blocks_text = "\n".join(
        f"[{b.get('component', '?')}] {json.dumps(b, ensure_ascii=False)[:300]}"
        for b in blocks[:20]
    )
    material_brief = "\n".join(
        f"[来源{i + 1}] {r.get('title', '')}: {r.get('snippet', r.get('content', ''))[:300]}"
        for i, r in enumerate((material or [])[:8])
    )
    design_brief = json.dumps(design or {}, ensure_ascii=False)[:600]

    prompt = f"""用户想了解：{user_input}

视觉方案：
{design_brief or '(无)'}

页面内容块：
{blocks_text or '(空)'}

素材：
{material_brief or '(无素材)'}

页面结构特征：
{_html_meta(html)}

请按四维审查，输出 JSON。"""

    try:
        result = await chat_json(
            prompt, system=skill_prompt("judge", JUDGE_SYSTEM_PROMPT),
            session_records=session_records, model=model,
        )
    except CircuitOpenError:
        raise  # 服务熔断中——不静默放行，让编排层快速失败
    except Exception as e:
        logger.warning("judge=call_failed | %s", e)
        return {"passed": True, "issues": []}

    parsed = safe_parse_json(result)
    if parsed is None:
        logger.warning("judge=parse_failed")
        return {"passed": True, "issues": []}

    issues = parsed.get("issues", []) if isinstance(parsed.get("issues"), list) else []
    issues = [i for i in issues if isinstance(i, dict) and i.get("desc")][:10]
    passed = bool(parsed.get("passed", True))
    logger.info("judge=done | passed=%s | issues=%d", passed, len(issues))
    return {"passed": passed, "issues": issues}


def pick_rollback(issues: list[dict]) -> str:
    """从审查缺陷里选回退目标：严重维度优先，其次出现最多的 target。"""
    if not issues:
        return "render"
    # 事实/覆盖问题最严重，优先
    for i in issues:
        if i.get("dimension") in ("fact", "coverage"):
            return i.get("target") or "search"
    # 否则选出现最多的 target
    counts: dict[str, int] = {}
    for i in issues:
        t = i.get("target") or "render"
        counts[t] = counts.get(t, 0) + 1
    return max(counts, key=counts.get)
