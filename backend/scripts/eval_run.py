"""端到端评测 — 跑 N 个话题，收集真实数字（通过率/步数/成本）。

用法（在 backend 目录下）：
    ..\\venv\\Scripts\\python scripts/eval_run.py          # 默认 10 个话题
    ..\\venv\\Scripts\\python scripts/eval_run.py --topics 5

注意：会调用真实 DeepSeek API（消耗 token）。写 backend/data/eval_report.json。
"""

import argparse
import asyncio
import json
import os
import sys
import time

# 确保能 import app
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.agents.orchestrator import orchestrator_node  # noqa: E402
from app.core.eval_report import to_markdown, write_report  # noqa: E402
from app.demo import DEMO_TOPICS  # noqa: E402

# 评测话题：5 个 demo + 5 个补充（10 个不同话题）
TOPICS = DEMO_TOPICS + ["秦始皇统一六国", "长城修建", "兵马俑", "李白与唐诗", "嫦娥探月"]

REPORT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "eval_report.json")


async def run_one(topic: str, idx: int) -> dict:
    """跑一个话题，返回结果摘要。idx 用于独立 session——trace 可分离回放。"""
    records: list[dict] = []

    async def push(msg: dict):   # 必须是 async——orchestrator 里是 `await push(...)`
        records.append(msg)

    state = {
        "session_id": f"eval{idx:02d}",
        "user_input": topic,
        "_push": push,
        "_cost_records": [],
        "_preferences": {},
    }
    t0 = time.monotonic()
    result = await orchestrator_node(state)
    duration = time.monotonic() - t0
    return {
        "topic": topic,
        "status": result.get("status", "unknown"),
        "steps": result.get("steps", 0),
        "cost": result.get("budget", 0),
        "honest_mode": result.get("honest_mode", False),
        "duration_s": round(duration, 1),
        "issues": result.get("issues", []),
    }


async def main(topics_limit: int) -> int:
    print(f"🧪 评测开始：{topics_limit} 个话题（真实 DeepSeek 调用）")
    results: list[dict] = []
    for i, topic in enumerate(TOPICS[:topics_limit]):
        try:
            r = await run_one(topic, i)
        except Exception as e:  # noqa: BLE001 — 评测不因单个失败中断
            r = {"topic": topic, "status": "error", "error": str(e)[:120]}
        results.append(r)
        print(f"  {r.get('topic')}: {r.get('status')} | {r.get('steps', '?')} 步 | "
              f"¥{r.get('cost', 0)} | {r.get('duration_s', '?')}s")

    write_report(results, REPORT_PATH)
    report = json.load(open(REPORT_PATH, encoding="utf-8"))
    print("\n" + to_markdown(report))
    print(f"\n✅ 报告已写入: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--topics", type=int, default=10)
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.topics)))
