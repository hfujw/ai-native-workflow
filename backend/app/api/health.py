"""系统状态 + 监控端点：health 探针 / metrics / events / rate-limit / eval。"""

import logging
import os

from fastapi import APIRouter, Response

from app.demo import DEMO_TOPICS, DEMOS_DIR
from app.knowledge.kb import get_all_events
from app.observability.metrics import metrics_text
from app.security.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

router = APIRouter()


def _playwright_browsers_dir() -> str:
    """Playwright 浏览器目录——跨平台：Windows 在 %LOCALAPPDATA%，其他在 ~/.cache。"""
    override = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if override:
        return override
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return os.path.join(os.environ["LOCALAPPDATA"], "ms-playwright")
    return os.path.expanduser("~/.cache/ms-playwright")


@router.get("/api/health")
async def health():
    """启动时本地校验 + 运行时依赖状态。不发真实 LLM 请求（避免冷启动慢 + 消耗 Token）。"""
    import os as _os

    from app.config import settings

    checks = {}

    # Config 完整性
    try:
        _ = settings.deepseek_api_key
        checks["config"] = "ok"
    except Exception as e:
        checks["config"] = f"fail: {e}"

    # Playwright 浏览器
    pw_dir = _playwright_browsers_dir()
    checks["playwright_browser"] = "ok" if _os.path.isdir(pw_dir) else "missing"

    # Demo 就绪状态
    ready = sum(1 for t in DEMO_TOPICS if _os.path.exists(_os.path.join(DEMOS_DIR, f"{t}.html")))
    checks["demos"] = f"{ready} ready / {len(DEMO_TOPICS)} total"

    all_ok = all(v == "ok" or v.startswith("ok") or "ready" in v for v in checks.values())
    return {"status": "healthy" if all_ok else "degraded", "checks": checks}


@router.get("/api/health/live")
async def health_live():
    """Liveness 探针——进程是否存活。Kubernetes/Docker 用这个决定是否重启容器。"""
    return {"status": "alive"}


@router.get("/api/health/ready")
async def health_ready():
    """Readiness 探针——依赖是否就绪。Kubernetes 用这个决定是否路由流量。"""
    import os as _os

    from app.config import settings

    checks = {}
    # Config + API Key
    try:
        _ = settings.deepseek_api_key
        checks["config"] = "ok"
    except Exception as e:
        checks["config"] = f"fail: {e}"

    # Playwright 浏览器（render 工具必需）
    pw_dir = _playwright_browsers_dir()
    checks["playwright_browser"] = "ok" if _os.path.isdir(pw_dir) else "missing"

    all_ok = all(v == "ok" for v in checks.values())
    return {
        "status": "ready" if all_ok else "not_ready",
        "checks": checks,
    }


@router.get("/api/events")
async def list_events(category: str = None):
    """返回示例话题列表。category 可选过滤：'computer_history' / 'bagu' / 不传=全部。"""
    events = get_all_events(category=category if category else None)
    result = []
    for e in events:
        name = e.get("title", "")
        result.append({
            "name": name,
            "category": e.get("category", "computer_history"),
        })
    return {"events": result, "total": len(result)}


@router.get("/metrics")
async def metrics():
    """Prometheus 指标端点。"""
    return Response(content=metrics_text(), media_type="text/plain")


@router.get("/api/rate-limit")
async def get_rate_limit():
    """返回当前费率限制状态（供前端展示剩余次数）。"""
    return await rate_limiter.stats()


@router.get("/api/eval")
async def get_eval():
    """返回评测报告（由 scripts/eval_run.py 生成）。没跑过返回占位。"""
    import json as _json
    report_path = os.path.join("data", "eval_report.json")
    try:
        with open(report_path, encoding="utf-8") as f:
            return _json.load(f)
    except (FileNotFoundError, _json.JSONDecodeError):
        return {"status": "not_run",
                "message": "评测还没跑过——用 `cd backend && ..\\venv\\Scripts\\python scripts/eval_run.py` 生成"}
