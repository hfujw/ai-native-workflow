"""AI-Native Workflow — FastAPI 入口（只做装配：日志 + app + 路由挂载）。"""

import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler

# ═══════════════════════════════════════════════════════════════
# 日志系统 — 必须在所有业务 import 之前配置，防止被 uvicorn 抢占
# ═══════════════════════════════════════════════════════════════
LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")
os.makedirs(LOG_DIR, exist_ok=True)

root = logging.getLogger()
root.setLevel(logging.DEBUG)
for h in list(root.handlers):
    try:
        h.close()
    except Exception:
        pass
    root.removeHandler(h)

# 终端：INFO 及以上 → stdout
_sh = logging.StreamHandler(sys.stdout)
_sh.setLevel(logging.INFO)
_sh.setFormatter(logging.Formatter("%(asctime)s | %(name)-22s | %(levelname)-8s | %(message)s", datefmt="%H:%M:%S"))
root.addHandler(_sh)

# 文件：DEBUG 及以上 → detail.log
# 使用 TimedRotatingFileHandler：每天午夜轮转，保留 30 天
_fh = TimedRotatingFileHandler(
    os.path.join(LOG_DIR, "detail.log"),
    when="midnight", interval=1, backupCount=30, encoding="utf-8",
)
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s"))
root.addHandler(_fh)

# 压低第三方噪音
for _n in ("uvicorn.access", "httpx", "httpcore", "openai"):
    logging.getLogger(_n).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# 装配
# ═══════════════════════════════════════════════════════════════
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import demos, generate, health, history, preferences
from app.api.ws import ws_manager
from app.config import settings as _settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动校验 + 优雅关闭。"""
    logger.info("服务启动中...")
    yield
    logger.info("正在关闭，等待飞行中请求完成...")
    await ws_manager.shutdown(timeout=5.0)
    logger.info("服务已关闭")


app = FastAPI(title="AI-Native Workflow", version="2.0.0", lifespan=lifespan)

# CORS — 白名单（dev 走 vite 代理同源；收紧避免任意站点调用后端烧预算）
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 路由
app.include_router(health.router)
app.include_router(demos.router)
app.include_router(generate.router)
app.include_router(history.router)
app.include_router(preferences.router)
