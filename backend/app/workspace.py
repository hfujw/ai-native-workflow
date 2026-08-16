"""生成页面工作区 — 每次生成/迭代 = 一份独立产物文件。

位置：backend/workspace/（gitignored）
命名：<session_id>_<主题>_v<迭代号>.html —— 迭代修改生成 v2/v3…，不覆盖旧版，
用户自己决定删不删（前端作品卡删除 = 连带删文件）。
好处：能直接拿去分享；以后做精美页面/游戏要用更多文件工具时，这里就是工作区。
"""

import logging
import os
import re

logger = logging.getLogger(__name__)

_WORKSPACE_DIR = os.path.join(os.path.dirname(__file__), "..", "workspace")


def workspace_dir() -> str:
    return _WORKSPACE_DIR


def save_page(session_id: str, topic: str, html: str, iteration: int = 1) -> str:
    """把一版页面 HTML 写到工作区（v<iteration>.html），返回文件路径。失败返回空串。"""
    if not html:
        return ""
    try:
        os.makedirs(_WORKSPACE_DIR, exist_ok=True)
        safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", topic or "").strip()[:40] or "page"
        path = os.path.join(_WORKSPACE_DIR, f"{session_id}_{safe}_v{iteration}.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        logger.info("产物已落盘工作区: %s", path)
        return path
    except OSError as e:
        logger.warning("工作区写入失败: %s", e)
        return ""


def delete_page(filename: str) -> bool:
    """删除工作区里的一个产物文件（前端作品卡删除用）。

    文件名白名单校验：只允许文件名（不含路径分隔符/上级跳转），防路径穿越。
    """
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        return False
    path = os.path.join(_WORKSPACE_DIR, filename)
    if not os.path.isfile(path):
        return False
    try:
        os.remove(path)
        logger.info("产物已删除: %s", path)
        return True
    except OSError as e:
        logger.warning("产物删除失败: %s", e)
        return False
