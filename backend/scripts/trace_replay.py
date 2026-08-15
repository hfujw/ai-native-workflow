"""trace_replay.py — 把决策轨迹 JSONL 变成可读的思考回放。

用法（backend 目录下）：
    ..\\venv\\Scripts\\python scripts/trace_replay.py <session_id>
    ..\\venv\\Scripts\\python scripts/trace_replay.py 5173c85c

输出：AI 每一步的思考 + 工具调用 + 成本，按时间顺序。
面试演示素材：能看到它"为什么这么决策"。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.observability.trace import get_trace  # noqa: E402


def main(session_id: str) -> int:
    entries = get_trace(session_id)
    if not entries:
        print(f"无 trace: {session_id}（backend/logs/traces/ 下没有该文件）")
        return 1

    print(f"{'═' * 52}")
    print(f"  决策轨迹回放 · session={session_id} · {len(entries)} 条")
    print(f"{'═' * 52}")

    for e in entries:
        step = e.get("step", "?")
        typ = e.get("type")
        tool = e.get("tool", "")

        if typ == "decide":
            print(f"\n── 第 {step} 步 · 决定用 [{tool}] ──")
            print(f"   💭 {e.get('thought', '')}")
        elif typ == "tool":
            cost = e.get("cost_delta", 0)
            summary = e.get("summary", "")
            print(f"   🔧 [{tool}] {summary}  (+¥{cost:.4f})")

    print(f"\n{'─' * 52}\n  （回放结束）")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python scripts/trace_replay.py <session_id>")
        sys.exit(1)
    sys.exit(main(sys.argv[1]))
