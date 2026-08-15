"""可插拔 skill 目录 — 每个子目录一个 skill，内含 skill.json 清单。

技能格式：{name, type: 风格|工具, desc, icon, prompt}。
本轮只提供清单加载；生成流程接入留待后端整体整合。
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

_SKILLS_DIR = os.path.dirname(__file__)

_cache: list[dict] | None = None


def _load_all() -> list[dict]:
    """惰性加载全部 skill——glob 各子目录的 skill.json，损坏的降级跳过。"""
    global _cache
    if _cache is not None:
        return _cache
    skills = []
    for entry in sorted(os.listdir(_SKILLS_DIR)):
        path = os.path.join(_SKILLS_DIR, entry, "skill.json")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or not data.get("name"):
                logger.warning("skill 清单缺 name，跳过: %s", entry)
                continue
            data["id"] = entry
            skills.append(data)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("skill 加载失败(%s): %s", entry, e)
    _cache = skills
    return skills


def list_skills(skill_type: str | None = None) -> list[dict]:
    """列出全部 skill，可按类型（风格/工具）过滤。"""
    skills = _load_all()
    if skill_type:
        return [s for s in skills if s.get("type") == skill_type]
    return list(skills)


def load_skill(name: str) -> dict | None:
    """按目录名取单个 skill，不存在返回 None。"""
    for s in _load_all():
        if s.get("id") == name:
            return s
    return None
