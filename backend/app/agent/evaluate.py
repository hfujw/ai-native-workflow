"""素材评估 — 外置判定素材质量，不是 LLM 判断。"""


def evaluate_material(material: list, user_input: str) -> dict:
    """评估素材够不够、关不相关。返回 level + reason + suggestion。

    纯规则判定：统计素材标题/内容中包含用户关键词的条目数。
    """
    if not material:
        return {"level": "none", "reason": "零素材", "suggestion": "诚实说明素材不足"}
    query = user_input.lower()
    # 检查多少素材里包含用户输入的关键词
    relevant = [m for m in material if any(
        w in (m.get("title", "") + m.get("snippet", m.get("content", ""))).lower()
        for w in query.split() if len(w) >= 2
    )]
    if len(relevant) >= 3:
        return {"level": "high", "reason": f"{len(relevant)}条直接相关", "suggestion": "正常生成"}
    elif len(relevant) >= 1:
        return {"level": "medium", "reason": f"仅{len(relevant)}条弱相关",
                "suggestion": "降级：基于现有素材做关联呈现"}
    else:
        return {"level": "low", "reason": "素材与主题不直接相关",
                "suggestion": "诚实模式：生成资料局限声明页"}
