"""评测报告生成 — eval_run.py 的结果 → JSON + Markdown。

位置：backend/data/eval_report.json（gitignored）
"""

import json
import os


def summarize(results: list[dict]) -> dict:
    """汇总评测结果：通过率、平均步数、成本。"""
    success = [r for r in results if r.get("status") == "success"]
    total = len(results)
    total_cost = sum(r.get("cost", 0) for r in results)
    avg_steps = sum(r.get("steps", 0) for r in results) / max(1, total)
    return {
        "total": total,
        "success": len(success),
        "failed": total - len(success),
        "pass_rate": round(len(success) / max(1, total), 3),
        "avg_steps": round(avg_steps, 1),
        "total_cost": round(total_cost, 4),
        "avg_cost": round(total_cost / max(1, total), 4),
        "results": results,
    }


def write_report(results: list[dict], path: str) -> dict:
    """写 JSON 报告，返回汇总。"""
    report = summarize(results)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    except OSError:
        pass
    return report


def to_markdown(report: dict) -> str:
    """Markdown 报告（终端/README 用）。"""
    lines = [
        "# 评测报告",
        "",
        f"- **通过率**：{report['pass_rate']:.0%}（{report['success']}/{report['total']}）",
        f"- **平均步数**：{report['avg_steps']}",
        f"- **总成本**：¥{report['total_cost']}（平均 ¥{report['avg_cost']}/任务）",
        "",
        "| 话题 | 状态 | 步数 | 成本 |",
        "|------|------|------|------|",
    ]
    for r in report.get("results", []):
        lines.append(f"| {r.get('topic', '?')} | {r.get('status', '?')} | "
                     f"{r.get('steps', '?')} | ¥{r.get('cost', 0)} |")
    return "\n".join(lines)
