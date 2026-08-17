"""可插拔 skill — 所有 skill 都在一个目录 `backend/skills/`（gitignored）。

每个 skill = **一个 markdown 文档**（SKILL.md）：frontmatter 放元数据（name/type/icon/desc），
正文放该 skill 的人格/指令——对齐 Claude skill 机制，一个能力一个文档，不拆散。

- 内置核心人格 skill（core/judge/critique/refine）是**系统管理**的：正文由代码常量注入，
  每次启动同步最新人格；builtin 不可删、不可被安装覆盖。
- 风格 skill（像素/杂志/信息图）用户可编辑、可在前端删除；可带模板资产（template.html/reference.css）。
- 健壮性：格式坏/缺 name → 跳过该 skill 不崩；core 缺失 → 调用方回退代码常量。
"""

import importlib
import logging
import os
import re
import shutil

logger = logging.getLogger(__name__)

_SKILLS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "skills")  # backend/skills
_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")       # 源码内置模板

# 内置默认 skill（播种源——随仓库发布；运行时生成进 skills/）
_BUILTINS: dict[str, dict] = {
    "core": {
        "name": "核心编排", "type": "工具", "icon": "🧠",
        "desc": "Lumen 核心编排人格（内置，不可删）——决定何时搜索/设计/渲染/审查",
        "body": "核心编排人格（由系统注入）",
    },
    "judge": {
        "name": "质量审查", "type": "工具", "icon": "🔍",
        "desc": "四维审查人格（内置，不可删）——事实/覆盖/可读/美学挑刺",
        "body": "质量审查人格（由系统注入）",
    },
    "critique": {
        "name": "方案批评家", "type": "工具", "icon": "💢",
        "desc": "设计前挑刺人格（内置，不可删）——方案结构问题零成本修正",
        "body": "方案批评家人格（由系统注入）",
    },
    "refine": {
        "name": "多轮迭代", "type": "工具", "icon": "🔁",
        "desc": "成品迭代人格（内置，不可删）——用户改页面时决定怎么改",
        "body": "迭代人格（由系统注入）",
    },
    "pixel": {
        "name": "像素风", "type": "风格", "icon": "🎮",
        "desc": "复古 8-bit 像素美学——有限色板、块状像素、霓虹荧光。适合游戏化叙事、怀旧题材、独立游戏介绍页；生成『有游戏感』的像素风长页，字块、发光、颗粒感十足",
        "body": "低分辨率像素画面、有限色板、块状复古字体，主题围绕游戏化叙事",
        # 方向 A：Skill 是编排策略——组件优先级/文案语气/交互基因（播种时写进 SKILL.md frontmatter）
        "design_priority": ["cards", "timeline", "portrait"],
        "compose_tone": "游戏化",
        "max_paragraph_lines": 2,
        "interaction": "none",
        "target_age": "12-18",
    },
    "magazine": {
        "name": "杂志长图", "type": "风格", "icon": "📰",
        "desc": "编辑级杂志排版——网格系统、大标题、图文混排、留白节奏。适合品牌故事、深度报道、产品发布长文；生成编辑部审美的长页，信息层级清楚、排版克制精致",
        "body": "编辑级杂志排版、网格系统、图文混排、大标题与留白",
        "design_priority": ["timeline", "blockquote", "portrait", "cards"],
        "compose_tone": "叙事感",
        "max_paragraph_lines": 3,
        "interaction": "reading-progress",
        "target_age": "12-18",
    },
    "infographic": {
        "name": "信息图", "type": "风格", "icon": "📊",
        "desc": "数据可视化优先——图表、关键数字、对比面板。适合年度总结、数据报告、SaaS 特性页；生成『一眼看懂』的数据叙事长页，数字突出、信息层次分明",
        "body": "数据可视化优先、图表 + 关键数字突出、信息层次分明",
        "design_priority": ["datapanel", "comparison", "cards", "flowchart"],
        "compose_tone": "数据化",
        "max_paragraph_lines": 2,
        "interaction": "count-up",
        "target_age": "12-18",
    },
}

# 系统管理的人格 skill → 正文从哪个模块常量注入（单一来源，不复制粘贴）
_PERSONA_SOURCE: dict[str, tuple[str, str]] = {
    "core": ("app.agent.orchestrator", "ORCHESTRATOR_SYSTEM_PROMPT"),
    "judge": ("app.llm.judge", "JUDGE_SYSTEM_PROMPT"),
    "critique": ("app.llm.judge", "CRITIQUE_SYSTEM_PROMPT"),
    "refine": ("app.agent.orchestrator", "REFINE_SYSTEM_PROMPT"),
}

_cache: list[dict] | None = None


# ── 内部 ──

def _render_skill_md(meta: dict) -> str:
    """把 skill 元数据渲染成 SKILL.md。编排配置字段（方向 A）写进 frontmatter，
    clone 后播种时从 _BUILTINS 自动生成，GitHub 上不丢配置。"""
    lines = [f"name: {meta['name']}", f"type: {meta['type']}",
             f"icon: {meta['icon']}", f"desc: {meta['desc']}"]
    for key in ("design_priority", "compose_tone", "max_paragraph_lines",
                "interaction", "target_age"):
        if key in meta:
            v = meta[key]
            if isinstance(v, list):
                v = "[" + ", ".join(v) + "]"
            lines.append(f"{key}: {v}")
    return f"---\n{chr(10).join(lines)}\n---\n{meta['body']}"


def _persona_body(sid: str, fallback: str) -> str:
    """系统管理人格 skill 的正文 = 代码常量（保持单一来源，代码更新即同步）。"""
    src = _PERSONA_SOURCE.get(sid)
    if not src:
        return fallback
    try:
        mod, const = src
        return getattr(importlib.import_module(mod), const, fallback)
    except Exception as e:
        logger.warning("人格注入失败(%s) 用占位: %s", sid, e)
        return fallback


def _ensure_seeded() -> None:
    """逐 skill 播种。人格 skill（core/judge/critique/refine）每次覆盖（系统管理）；
    风格 skill 只写缺失的 SKILL.md/资产（用户可编辑）。"""
    os.makedirs(_SKILLS_DIR, exist_ok=True)
    for sid, meta in _BUILTINS.items():
        skill_dir = os.path.join(_SKILLS_DIR, sid)
        os.makedirs(skill_dir, exist_ok=True)
        md_path = os.path.join(skill_dir, "SKILL.md")
        system_managed = sid in _PERSONA_SOURCE
        if system_managed or not os.path.isfile(md_path):
            body = _persona_body(sid, meta["body"]) if system_managed else meta["body"]
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(_render_skill_md({**meta, "body": body}))
        if not os.path.isfile(md_path):  # 风格 skill 首次
            _seed_assets(sid, skill_dir)
        else:
            # 逐资产补缺：新增资产文件（如 interactions.js）也要补种到旧运行时目录
            _seed_missing_assets(sid, skill_dir)


def _seed_assets(sid: str, skill_dir: str) -> None:
    """把源码里的模板资产（template.html/reference.css/interactions.js）复制到运行时 skill 目录。"""
    src = os.path.join(_TEMPLATES_DIR, sid)
    if not os.path.isdir(src):
        return
    for name in ("template.html", "reference.css", "interactions.js"):
        s = os.path.join(src, name)
        if os.path.isfile(s):
            shutil.copy2(s, os.path.join(skill_dir, name))
            logger.debug("skill 模板资产已播种: %s/%s", sid, name)


def _seed_missing_assets(sid: str, skill_dir: str) -> None:
    """逐资产补缺——新资产文件（如 interactions.js）补种到已存在的运行时目录。"""
    src = os.path.join(_TEMPLATES_DIR, sid)
    if not os.path.isdir(src):
        return
    for name in ("template.html", "reference.css", "interactions.js"):
        s = os.path.join(src, name)
        if os.path.isfile(s) and not os.path.exists(os.path.join(skill_dir, name)):
            shutil.copy2(s, os.path.join(skill_dir, name))
            logger.debug("skill 资产补种: %s/%s", sid, name)


def _read_assets(skill_dir: str) -> dict:
    """读取 skill 的模板资产（不存在则为空）。"""
    assets: dict = {}
    for name in ("template.html", "reference.css", "interactions.js"):
        p = os.path.join(skill_dir, name)
        if os.path.isfile(p):
            try:
                with open(p, encoding="utf-8") as f:
                    assets[name] = f.read()
            except OSError as e:
                logger.warning("skill 资产读取失败(%s): %s", name, e)
    return assets


def _parse_int(raw) -> int:
    """安全解析 frontmatter 里的整数，失败回退默认值。"""
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 3


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """解析 SKILL.md：--- 之间的 key: value frontmatter + 正文指令。不引 YAML 依赖。

    支持简单列表（`[a, b, c]`）和标量。新字段（design_priority / compose_tone /
    max_paragraph_lines / interaction / target_age）都从这里进 skill_config。
    """
    meta: dict = {}
    body = text.strip()
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                key, raw = k.strip(), v.strip()
                # `[a, b, c]` 列表 → list
                if raw.startswith("[") and raw.endswith("]"):
                    meta[key] = [x.strip() for x in raw[1:-1].split(",") if x.strip()]
                else:
                    meta[key] = raw
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
                text = text.lstrip("﻿")  # 容忍 UTF-8 BOM（某些编辑器会写）
                meta, body = _parse_frontmatter(text)
                if not meta.get("name"):
                    logger.warning("skill 缺 name，跳过: %s", entry)
                    continue
                skill_dir = path.rsplit("SKILL.md", 1)[0]
                found.append({
                    "id": entry,
                    "name": meta.get("name", entry),
                    "type": meta.get("type", "风格"),
                    "icon": meta.get("icon", "🧩"),
                    "desc": meta.get("desc", ""),
                    "prompt": body,
                    "builtin": entry in _BUILTINS,  # 内置标记（前端"我的 Skill"区分）
                    "assets": _read_assets(skill_dir),
                    # 编排配置（方向 A/C）：影响 design/compose/render 的生成约束
                    "skill_config": {
                        "design_priority": meta.get("design_priority", []),
                        "compose_tone": meta.get("compose_tone", ""),
                        "max_paragraph_lines": _parse_int(meta.get("max_paragraph_lines", 3)),
                        "interaction": meta.get("interaction", ""),
                        "target_age": meta.get("target_age", "12-18"),
                    },
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


def skill_prompt(skill_id: str, fallback: str) -> str:
    """从 skill 取人格 prompt（正文）。skill 缺失/坏 → 回退 fallback，绝不崩。

    这样系统管理人格（core/judge/critique/refine）以 skill 形式存在、可替换，
    坏文件/被删也不会让调用方崩。
    """
    if not skill_id:
        return fallback
    try:
        sk = load_skill(skill_id)
    except Exception as e:
        logger.warning("skill_prompt 读取失败(%s) 回退默认: %s", skill_id, e)
        return fallback
    if not sk:
        return fallback
    return sk.get("prompt") or fallback


def is_builtin(skill_id: str) -> bool:
    """该 skill 是否内置（core/人格/风格）——内置不可删除、不可被安装覆盖。"""
    return skill_id in _BUILTINS


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
    返回解析后的 skill；格式非法（缺 name）或覆盖内置 → 返回 None。"""
    if skill_id in _BUILTINS:
        logger.warning("拒绝覆盖内置 skill: %s", skill_id)
        return None  # 内置（core/人格/风格）不可被安装覆盖
    skill_dir = os.path.join(_SKILLS_DIR, skill_id)
    os.makedirs(skill_dir, exist_ok=True)
    with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(markdown)
    reload_skills()
    return load_skill(skill_id)
