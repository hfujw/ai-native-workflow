"""决策轨迹落盘 — 每次生成的思考/行动全记录（JSONL）。

用途：调试回放、评测数据源、面试演示素材。
位置：backend/logs/traces/{session_id}.jsonl（gitignored）
"""

import json
import logging
import os
import time

logger = logging.getLogger(__name__)

_TRACE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "logs", "traces")
TRACE_RETENTION_DAYS = 7  # trace 保留 7 天，到期自动清理


def _ensure_dir() -> None:
    os.makedirs(_TRACE_DIR, exist_ok=True)


def _prune_old_traces() -> None:
    """清理超过保留期的 trace 文件，防止无限堆积。"""
    try:
        now = time.time()
        cutoff = now - TRACE_RETENTION_DAYS * 86400
        for f in os.listdir(_TRACE_DIR):
            if f.endswith(".jsonl"):
                path = os.path.join(_TRACE_DIR, f)
                try:
                    if os.path.getmtime(path) < cutoff:
                        os.remove(path)
                except OSError:
                    pass
    except OSError:
        pass


def log_trace(session_id: str, entry: dict) -> None:
    """追加一行 trace。entry 含 type/step/tool/thought/summary/cost 等字段。"""
    try:
        _ensure_dir()
        _prune_old_traces()
        path = os.path.join(_TRACE_DIR, f"{session_id}.jsonl")
        line = json.dumps({"ts": time.time(), "session": session_id, **entry}, ensure_ascii=False)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:
        logger.debug("trace 写入失败: %s", e)


def get_trace(session_id: str) -> list[dict]:
    """读取一个会话的完整 trace（回放/评测用）。文件不存在返回空列表。"""
    path = os.path.join(_TRACE_DIR, f"{session_id}.jsonl")
    try:
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    except (FileNotFoundError, json.JSONDecodeError):
        return []
