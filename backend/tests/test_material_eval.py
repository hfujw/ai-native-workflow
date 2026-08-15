"""测试 evaluate_material — 素材相关性评估。"""
from app.agent.evaluate import evaluate_material


def test_no_material_returns_none():
    result = evaluate_material([], "秦始皇")
    assert result["level"] == "none"
    assert "零素材" in result["reason"]


def test_all_relevant_returns_high():
    material = [
        {"title": "秦始皇统一六国", "snippet": "公元前221年", "content": ""},
        {"title": "长城修建", "snippet": "秦始皇征发民夫", "content": ""},
        {"title": "秦始皇陵", "snippet": "兵马俑发现", "content": ""},
    ]
    result = evaluate_material(material, "秦始皇")
    assert result["level"] == "high"
    assert "3条" in result["reason"]


def test_one_relevant_returns_medium(sample_material):
    result = evaluate_material(sample_material[:1], "秦始皇")
    assert result["level"] == "medium"


def test_zero_relevant_returns_low():
    result = evaluate_material(
        [{"title": "Python入门", "snippet": "编程语言", "content": ""}],
        "秦始皇"
    )
    assert result["level"] == "low"
