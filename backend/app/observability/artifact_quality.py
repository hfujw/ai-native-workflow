"""产物质量自动评估（纯正则，不引依赖）——把"肉眼评估"变成可重复的客观打分。

六维底线（教育场景）：
  1. 信息架构  有 h1/h2 + 段落分层（不是一坨文字）
  2. 视觉层次  至少 2 种字号 + 有区块/边框/分隔
  3. 段落长度  单段平均不超过儿童注意力阈值
  4. 事实锚定  有至少 1 个来源引用（URL 或"来源"字样）
  5. 互动元素  至少 1 个可点击/悬停（button / a / :hover / onclick）
  6. 教育适配  有引导性提问 / 有可交互或折叠元素（主动学习信号）

用途：
  - 生成流程验证后对产物打分（<4/6 视为不合格，调 prompt 重跑）
  - 产物落盘时记录质量分，供回看
"""

import re

# 段落最大平均长度（字符）——儿童注意力阈值
MAX_PARA_AVG = 200
# 单段硬上限（字符）
MAX_PARA_LEN = 350


def _text_length(text: str) -> int:
    """按中文字符计长度（中文 1 字符 = 1，英文按单词折算）。"""
    # 中文 + 全角
    zh = len(re.findall(r"[一-鿿　-〿＀-￯]", text))
    # 英文单词
    en = len(re.findall(r"[A-Za-z]+", text))
    return zh + en


def assess_artifact(html: str) -> dict:
    """对产物 HTML 打分，返回 {score, results: {dimension: (ok, detail)}}。

    score: 通过维度数（0-5）。每个维度返回 ok + 说明，便于定位不达标原因。
    """
    low = html.lower()

    results: dict[str, tuple[bool, str]] = {}

    # ── 1. 信息架构：有标题体系 + 至少 2 个段落 ──
    has_h1 = bool(re.search(r"<h1[\s>]", low))
    has_h2 = bool(re.search(r"<h2[\s>]", low))
    para_tags = re.findall(r"<p[\s>].*?</p>", low, re.DOTALL)
    para_count = len(para_tags)
    architecture_ok = has_h1 and para_count >= 2
    results["信息架构"] = (
        architecture_ok,
        f"h1={has_h1} h2={has_h2} 段落x{para_count}",
    )

    # ── 2. 视觉层次：≥2 种字号 + 有区块分隔 ──
    # 字号层级：h1/h2 与正文 p 天然不同字号 → 算 1 层；再查是否有独立样式块/边框/分隔
    has_heading = has_h1 or has_h2
    has_section = bool(re.search(r"<div[^>]*class=[\"'][^\"']*(figure|tl|grid|card|panel|timeline|blockquote)[^\"']*[\"']", low))
    has_hr_or_border = bool(re.search(r"<(hr|blockquote)[\s>]", low)) or "border" in low
    visual_ok = has_heading and (has_section or has_hr_or_border)
    results["视觉层次"] = (
        visual_ok,
        f"标题={has_heading} 结构块={has_section} 分隔={has_hr_or_border}",
    )

    # ── 3. 段落长度：平均 + 单段上限 ──
    if para_count:
        lengths = [_text_length(re.sub(r"<[^>]+>", "", p)) for p in para_tags]
        avg = sum(lengths) / len(lengths)
        longest = max(lengths)
        para_ok = avg <= MAX_PARA_AVG and longest <= MAX_PARA_LEN
        results["段落长度"] = (
            para_ok,
            f"平均{int(avg)}字符 最长{longest} 上限{MAX_PARA_AVG}/{MAX_PARA_LEN}",
        )
    else:
        results["段落长度"] = (False, "无 <p> 段落")

    # ── 4. 事实锚定：URL 引用或"来源/参考"字样 ──
    has_link = bool(re.search(r'href=["\']https?://', low))
    has_source_note = bool(re.search(r"来源|参考|引用|据|according to|source", low))
    fact_ok = has_link or has_source_note
    results["事实锚定"] = (
        fact_ok,
        f"链接={has_link} 来源字样={has_source_note}",
    )

    # ── 5. 互动元素：button / 链接 / 悬停 / 点击 ──
    has_button = bool(re.search(r"<(button|a|details|input)[\s>]", low))
    has_hover = ":hover" in low
    has_onclick = "onclick" in low or "addEventListener" in low
    inter_ok = has_button and (has_hover or has_onclick)
    results["互动元素"] = (
        inter_ok,
        f"可点元素={has_button} 悬停={has_hover} 点击事件={has_onclick}",
    )

    # ── 6. 教育适配：引导性提问 / 交互或折叠元素（主动学习信号） ──
    has_question = bool(re.search(r"你知道|为什么|什么是|怎么|了解.*吗|吗\?|吗？", low))
    has_active_learning = (
        bool(re.search(r"(details|flip-card|count-up|onclick|addEventListener|accordion|tab)", low))
        or has_hover
    )
    edu_ok = has_question or has_active_learning
    results["教育适配"] = (
        edu_ok,
        f"引导提问={has_question} 主动学习={has_active_learning}",
    )

    score = sum(1 for ok, _ in results.values() if ok)
    return {"score": score, "results": results}


def assess_artifact_file(path: str) -> dict:
    """对产物 HTML 文件打分。"""
    with open(path, encoding="utf-8") as f:
        return assess_artifact(f.read())
