"""Phase D 测试——评测报告生成。"""
import json

import pytest

from app.core.eval_report import summarize, to_markdown, write_report


def test_summarize_calculates_metrics():
    results = [
        {"topic": "a", "status": "success", "steps": 5, "cost": 0.1},
        {"topic": "b", "status": "success", "steps": 7, "cost": 0.2},
        {"topic": "c", "status": "failed", "steps": 10, "cost": 0.3},
    ]
    report = summarize(results)
    assert report["total"] == 3
    assert report["success"] == 2
    assert report["failed"] == 1
    assert report["pass_rate"] == pytest.approx(0.667, abs=0.001)
    assert report["avg_steps"] == pytest.approx(7.33, abs=0.1)
    assert report["total_cost"] == pytest.approx(0.6)
    assert report["avg_cost"] == pytest.approx(0.2)


def test_write_report_creates_json(tmp_path):
    results = [{"topic": "a", "status": "success", "steps": 5, "cost": 0.1}]
    path = str(tmp_path / "report.json")
    report = write_report(results, path)
    loaded = json.load(open(path, encoding="utf-8"))
    assert loaded["success"] == 1
    assert report["pass_rate"] == 1.0


def test_to_markdown_has_numbers():
    report = {"total": 2, "success": 1, "failed": 1, "pass_rate": 0.5, "avg_steps": 6.0,
              "total_cost": 0.3, "avg_cost": 0.15,
              "results": [{"topic": "a", "status": "success", "steps": 5, "cost": 0.1}]}
    md = to_markdown(report)
    assert "50%" in md
    assert "¥0.15" in md
