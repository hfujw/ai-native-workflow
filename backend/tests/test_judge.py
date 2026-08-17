"""质量审查器测试：judge_page 四维审查 + 回退目标选择。"""

from unittest.mock import AsyncMock, patch

import pytest

from app.llm.judge import judge_page, pick_rollback


def _base_args():
    return {
        "user_input": "秦始皇修长城",
        "design": {"components": ["timeline"], "visual_hint": "秦汉黑红金"},
        "content": {"blocks": [{"component": "timeline", "claims": [{"text": "前221年统一", "source": "s1"}]}]},
        "material": [{"title": "长城历史", "snippet": "前221年秦始皇统一六国"}],
        "html": "<!DOCTYPE html><html><body><h1>测试</h1></body></html>",
    }


@pytest.mark.asyncio
async def test_judge_passed():
    with patch("app.llm.judge.chat_json", new=AsyncMock(return_value='{"passed": true, "issues": []}')):
        verdict = await judge_page(**_base_args())
    assert verdict["passed"] is True
    assert verdict["issues"] == []


@pytest.mark.asyncio
async def test_judge_finds_issues():
    raw = '{"passed": false, "issues": [{"dimension": "fact", "target": "research", "desc": "页面称动员百万民夫，素材无此数据"}, {"dimension": "aesthetic", "target": "design", "desc": "视觉方案无配色"}, {"dimension": "readability", "target": "compose", "desc": "术语堆砌"}]}'
    with patch("app.llm.judge.chat_json", new=AsyncMock(return_value=raw)):
        verdict = await judge_page(**_base_args())
    assert verdict["passed"] is False
    assert len(verdict["issues"]) == 3
    assert verdict["issues"][0]["dimension"] == "fact"


@pytest.mark.asyncio
async def test_judge_parse_failure_defaults_passed():
    with patch("app.llm.judge.chat_json", new=AsyncMock(return_value="不是 JSON")):
        verdict = await judge_page(**_base_args())
    assert verdict["passed"] is True  # 审查自身失败不阻塞交付


@pytest.mark.asyncio
async def test_judge_call_failure_defaults_passed():
    with patch("app.llm.judge.chat_json", new=AsyncMock(side_effect=RuntimeError("api down"))):
        verdict = await judge_page(**_base_args())
    assert verdict["passed"] is True


def test_pick_rollback_fact_priority():
    issues = [
        {"dimension": "aesthetic", "target": "render", "desc": "a"},
        {"dimension": "fact", "target": "research", "desc": "b"},
        {"dimension": "coverage", "target": "compose", "desc": "c"},
    ]
    assert pick_rollback(issues) == "research"  # fact 优先


def test_pick_rollback_education_maps_to_compose():
    """教育适配问题 → 回退到 compose（改文案），不是严重回退。"""
    issues = [
        {"dimension": "education", "target": "render", "desc": "术语太多"},
        {"dimension": "aesthetic", "target": "design", "desc": "配色"},
    ]
    assert pick_rollback(issues) == "compose"


def test_pick_rollback_readability_maps_to_compose():
    """可读性问题 → compose。"""
    issues = [
        {"dimension": "readability", "target": "render", "desc": "段落太长"},
        {"dimension": "aesthetic", "target": "design", "desc": "b"},
        {"dimension": "aesthetic", "target": "design", "desc": "c"},
    ]
    assert pick_rollback(issues) == "compose"


def test_pick_rollback_majority_fallback():
    """无 fact/coverage/education/readability/aesthetic 明确维度 → 多数 target 兜底。"""
    issues = [
        {"dimension": "unknown_dim", "target": "design", "desc": "a"},
        {"dimension": "unknown_dim", "target": "design", "desc": "b"},
        {"dimension": "unknown_dim", "target": "render", "desc": "c"},
    ]
    assert pick_rollback(issues) == "design"


def test_pick_rollback_empty():
    assert pick_rollback([]) == "render"
