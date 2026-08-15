"""可插拔 skill — 所有 skill 都在一个目录 `backend/skills/`（gitignored）。

- 每个 skill 一个子目录，内含 SKILL.md（markdown-frontmatter：元数据 + 指令）
- 可选模板资产：`template.html`（页面骨架）+ `reference.css`（排版系统）——
  渲染时注入，给 LLM 一个"真人设计的骨架"而不是凭空发挥
- 内置的三个（像素/杂志/信息图）是**首次运行时播种**的默认内容，模板资产
  从 `app/skills/templates/<id>/` 复制而来（源码随仓库分发）
- 形式对齐 Claude skill 体系：frontmatter 放机器元数据，正文放注入 LLM 的指令
"""

import logging
import os
import re
import shutil

logger = logging.getLogger(__name__)

_SKILLS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "skills")  # backend/skills
_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")       # 源码内置模板

# 内置默认 skill（播种源——写在代码里，随仓库发布；运行时生成进 skills/）
_BUILTINS: dict[str, dict] = {
    "pixel": {
        "name": "像素风", "type": "风格", "icon": "🎮",
        "desc": "复古像素游戏画面，适合解谜与怀旧题材",
        "body": "低分辨率像素画面、有限色板、块状复古字体，主题围绕游戏化叙事",
    },
    "magazine": {
        "name": "杂志长图", "type": "风格", "icon": "📰",
        "desc": "编辑级杂志排版，图文混排长页",
        "body": "编辑级杂志排版、网格系统、图文混排、大标题与留白",
    },
    "infographic": {
        "name": "信息图", "type": "风格", "icon": "📊",
        "desc": "数据可视化，图表 + 关键数字一眼看懂",
        "body": "数据可视化优先、图表 + 关键数字突出、信息层次分明",
    },
}

_cache: list[dict] | None = None


# ── 内部 ──

def _render_skill_md(meta: dict) -> str:
    return (f"---\nname: {meta['name']}\ntype: {meta['type']}\n"
            f"icon: {meta['icon']}\ndesc: {meta['desc']}\n---\n{meta['body']}")


def _ensure_seeded() -> None:
    """首次运行播种内置 skill。只当目录整体不存在时播种——删过单个不重建。"""
    if os.path.isdir(_SKILLS_DIR):
        return
    os.makedirs(_SKILLS_DIR, exist_ok=True)
    for sid, meta in _BUILTINS.items():
        skill_dir = os.path.join(_SKILLS_DIR, sid)
        os.makedirs(skill_dir, exist_ok=True)
        with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(_render_skill_md(meta))
        _seed_assets(sid, skill_dir)
    logger.info("已播种 %d 个内置 skill → %s", len(_BUILTINS), _SKILLS_DIR)


def _seed_assets(sid: str, skill_dir: str) -> None:
    """把源码里的模板资产（template.html/reference.css）复制到运行时 skill 目录。"""
    src = os.path.join(_TEMPLATES_DIR, sid)
    if not os.path.isdir(src):
        return
    for name in ("template.html", "reference.css"):
        s = os.path.join(src, name)
        if os.path.isfile(s):
            shutil.copy2(s, os.path.join(skill_dir, name))
            logger.debug("skill 模板资产已播种: %s/%s", sid, name)


def _read_assets(skill_dir: str) -> dict:
    """读取 skill 的模板资产（不存在则为空）。"""
    assets: dict = {}
    for name in ("template.html", "reference.css"):
        p = os.path.join(skill_dir, name)
        if os.path.isfile(p):
            try:
                with open(p, encoding="utf-8") as f:
                    assets[name] = f.read()
            except OSError as e:
                logger.warning("skill 资产读取失败(%s): %s", name, e)
    return assets


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """解析 SKILL.md：--- 之间的 key: value frontmatter + 正文指令。不引 YAML 依赖。"""
    meta: dict = {}
    body = text.strip()
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        body = m.group(2).strip()
    return meta, body


def _load_all() -> list[dict]:
    """惰性加载：播种后扫描唯一目录。"""
    global _cache
    if _cache is not None:
        return _cache
    _ensure_seeded()
    found: list[dict] = []
    if os.path.isdir(_SKILLS_DIR):
        for entry in sorted(os.listdir(_SKILLS_DIR)):
            path = os.path.join(_SKILLS_DIR, entry, "SKILL.md")
            if not os.path.isfile(path):
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    text = f.read()
                text = text.lstrip("\ufeff")  # 容忍 UTF-8 BOM（某些编辑器会写）
                meta, body = _parse_frontmatter(text)
                if not meta.get("name"):
                    logger.warning("skill 缺 name，跳过: %s", entry)
                    continue
                found.append({
                    "id": entry,
                    "name": meta.get("name", entry),
                    "type": meta.get("type", "风格"),
                    "icon": meta.get("icon", "🧩"),
                    "desc": meta.get("desc", ""),
                    "prompt": body,
                    "builtin": entry in _BUILTINS,  # 内置标记（前端"我的 Skill"区分）
                    "assets": _read_assets(path.rsplit("SKILL.md", 1)[0]),
                })
            except OSError as e:
                logger.warning("skill 读取失败(%s): %s", entry, e)
    _cache = found
    return found


# ── 公开接口 ──

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


def reload_skills() -> None:
    """清缓存——安装/删除后调用，让 list_skills 重新扫描。"""
    global _cache
    _cache = None


def delete_skill(name: str) -> bool:
    """删除整个 skill 目录（前端删除 = 全删，不残留）。不存在返回 False。"""
    path = os.path.join(_SKILLS_DIR, name)
    if not os.path.isdir(path):
        return False
    shutil.rmtree(path, ignore_errors=True)
    reload_skills()
    return True


def install_skill(skill_id: str, markdown: str) -> dict | None:
    """写入一个 skill（DeepSeek 下载用）：把 markdown 存到 skills/<id>/SKILL.md。
    返回解析后的 skill；格式非法（缺 name）返回 None。"""
    skill_dir = os.path.join(_SKILLS_DIR, skill_id)
    os.makedirs(skill_dir, exist_ok=True)
    with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(markdown)
    reload_skills()
    return load_skill(skill_id)
