"""skill 一文档制 + 健壮性测试（用户提醒：skill 种类多，别因格式/覆盖搞挂）。"""
from app import skills


def test_install_rejects_builtin():
    """内置 skill（core/人格/风格）不可被 install 覆盖。"""
    assert skills.install_skill("core", "---\nname: 恶意覆盖\n---\n正文") is None
    assert skills.install_skill("magazine", "---\nname: x\n---\n正文") is None


def test_persona_skills_have_bodies():
    """core/judge/critique/refine 是独立 skill，正文 = 各自人格（非占位）。"""
    for sid, fallback in [("core", "占位"), ("judge", "占位"), ("critique", "占位"), ("refine", "占位")]:
        s = skills.load_skill(sid)
        assert s is not None, f"{sid} skill 不存在"
        assert s["prompt"] and s["prompt"] != "占位", f"{sid} 人格未注入"
        assert s["builtin"] is True


def test_style_skill_one_markdown():
    """风格 skill = 一个 SKILL.md（正文 + 可选资产），无散文件。"""
    mag = skills.load_skill("magazine")
    assert mag is not None
    assert mag["prompt"]  # 正文是风格指令
    assert mag["assets"].get("template.html") is not None  # 模板资产还在


def test_skill_prompt_falls_back():
    """skill 缺失 → skill_prompt 回退 fallback，不崩。"""
    assert skills.skill_prompt("不存在skill", "默认人格") == "默认人格"
    assert skills.skill_prompt("", "默认人格") == "默认人格"
    # 存在的 skill → 用它的正文
    core = skills.load_skill("core")
    assert skills.skill_prompt("core", "默认人格") == core["prompt"]


def test_skill_without_name_skipped(tmp_path, monkeypatch):
    """SKILL.md 缺 name → 该 skill 被跳过，不影响其他 skill。"""
    monkeypatch.setattr(skills, "_SKILLS_DIR", str(tmp_path))
    (tmp_path / "bad").mkdir()
    (tmp_path / "bad" / "SKILL.md").write_text("没有 frontmatter 的正文", encoding="utf-8")
    (tmp_path / "good").mkdir()
    (tmp_path / "good" / "SKILL.md").write_text(
        "---\nname: 好技能\ntype: 风格\n---\n正文", encoding="utf-8")
    skills.reload_skills()
    ids = {s["id"] for s in skills.list_skills()}
    assert "good" in ids
    assert "bad" not in ids
