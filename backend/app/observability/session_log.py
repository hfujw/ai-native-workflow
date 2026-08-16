"""会话日志 — 每次生成一个独立日志文件（logs/sessions/<session_id>.log）。

detail.log 只留非会话日志（启动/全局错误）；生成会话的日志自动路由到自己的文件，
不再全堆在一个文件里——想回看某次生成，直接开 sessions/<id>.log。

实现：contextvars 标记当前会话。生成期间（generate_page 生命周期 + 其子任务）
日志自动写进该会话的文件；非会话日志照旧进 detail.log。
"""

import contextvars
import logging
import os

_SESSION_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "logs", "sessions")

_session_id: contextvars.ContextVar = contextvars.ContextVar("lumen_session_id", default=None)

_FORMAT = logging.Formatter(
    "%(asctime)s | %(name)-22s | %(levelname)-8s | %(message)s", datefmt="%H:%M:%S")


def bind_session(session_id: str):
    """绑定当前会话。返回 token，finally 里 unbind。"""
    return _session_id.set(session_id)


def unbind_session(token) -> None:
    _session_id.reset(token)


class _SessionFileHandler(logging.Handler):
    """把当前会话的日志写到 logs/sessions/<session_id>.log。非会话日志忽略。"""

    def emit(self, record):
        sid = _session_id.get()
        if not sid:
            return
        try:
            os.makedirs(_SESSION_DIR, exist_ok=True)
            path = os.path.join(_SESSION_DIR, f"{sid}.log")
            with open(path, "a", encoding="utf-8") as f:
                f.write(self.format(record) + "\n")
        except OSError:
            pass


class _NoSessionInDetail(logging.Filter):
    """detail.log 排除会话日志（它们有自己的文件，别重复堆）。"""

    def filter(self, record):
        return not _session_id.get()


def install() -> None:
    """挂到 root logger：会话日志 → 独立文件；detail.log 只留非会话。"""
    root = logging.getLogger()

    h = _SessionFileHandler()
    h.setLevel(logging.DEBUG)
    h.setFormatter(_FORMAT)
    root.addHandler(h)

    # 给已有的文件 handler（detail.log）加"排除会话日志"过滤；stdout 保持全量（实时看生成）
    for h in root.handlers:
        if isinstance(h, logging.FileHandler) and not isinstance(h, _SessionFileHandler):
            h.addFilter(_NoSessionInDetail())
