"""AI-Native Workflow — FastAPI 入口。"""

import logging
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
import sys
import os

# ═══════════════════════════════════════════════════════════════
# 日志系统 — 必须在所有业务 import 之前配置，防止被 uvicorn 抢占
# ═══════════════════════════════════════════════════════════════
LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")
os.makedirs(LOG_DIR, exist_ok=True)

root = logging.getLogger()
root.setLevel(logging.DEBUG)
for h in list(root.handlers):
    try: h.close()
    except: pass
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
# 业务 import
# ═══════════════════════════════════════════════════════════════
import uuid
import asyncio

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from app.llm.client import get_cost_summary
from app.network.ws_manager import ws_manager
from app.network.rate_limiter import rate_limiter
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动校验 + 优雅关闭。"""
    logger.info("服务启动中...")
    yield
    logger.info("正在关闭，等待飞行中请求完成...")
    await ws_manager.shutdown(timeout=5.0)
    logger.info("服务已关闭")

app = FastAPI(title="AI-Native Workflow", version="2.0.0", lifespan=lifespan)

# CORS — 允许前端开发时的跨域请求（Vite dev server: localhost:5173）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.knowledge.kb import get_all_events


@app.get("/api/health")
async def health():
    """启动时本地校验 + 运行时依赖状态。不发真实 LLM 请求（避免冷启动慢 + 消耗 Token）。"""
    import os as _os
    from app.demo import DEMOS_DIR, DEMO_TOPICS

    checks = {}

    # Config 完整性
    try:
        from app.core.config import settings
        _ = settings.deepseek_api_key
        checks["config"] = "ok"
    except Exception as e:
        checks["config"] = f"fail: {e}"

    # Playwright 浏览器
    pw_dir = _os.path.expanduser("~/.cache/ms-playwright")
    checks["playwright_browser"] = "ok" if _os.path.isdir(pw_dir) else "missing"

    # Demo 就绪状态
    ready = sum(1 for t in DEMO_TOPICS if _os.path.exists(_os.path.join(DEMOS_DIR, f"{t}.html")))
    checks["demos"] = f"{ready} ready / {len(DEMO_TOPICS)} total"

    all_ok = all(v == "ok" or v.startswith("ok") or "ready" in v for v in checks.values())
    return {"status": "healthy" if all_ok else "degraded", "checks": checks}


@app.get("/api/health/live")
async def health_live():
    """Liveness 探针——进程是否存活。Kubernetes/Docker 用这个决定是否重启容器。"""
    return {"status": "alive"}


@app.get("/api/health/ready")
async def health_ready():
    """Readiness 探针——依赖是否就绪。Kubernetes 用这个决定是否路由流量。"""
    import os as _os

    checks = {}
    # Config + API Key
    try:
        from app.core.config import settings
        _ = settings.deepseek_api_key
        checks["config"] = "ok"
    except Exception as e:
        checks["config"] = f"fail: {e}"

    # Playwright 浏览器（render 工具必需）
    pw_dir = _os.path.expanduser("~/.cache/ms-playwright")
    checks["playwright_browser"] = "ok" if _os.path.isdir(pw_dir) else "missing"

    all_ok = all(v == "ok" for v in checks.values())
    return {
        "status": "ready" if all_ok else "not_ready",
        "checks": checks,
    }


@app.get("/api/cost")
async def get_cost():
    """返回 LLM 调用花费统计。"""
    return get_cost_summary()


@app.get("/api/events")
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

# ── 工具函数 ──

def _friendly_error(e: Exception) -> str:
    """将原始异常映射为用户可理解的错误信息，避免泄漏技术细节。"""
    msg = str(e).lower()
    if "timeout" in msg or "timed out" in msg:
        return "AI 服务响应超时，请稍后重试"
    if "rate limit" in msg or "rate_limit" in msg:
        return "请求过于频繁，请稍等片刻再试"
    if "auth" in msg or "api key" in msg or "unauthorized" in msg:
        return "AI 服务认证失败，请联系管理员"
    if "connection" in msg or "refused" in msg or "network" in msg or "unreachable" in msg:
        return "无法连接到 AI 服务，请检查网络后重试"
    if "json" in msg or "decode" in msg or "parse" in msg:
        return "AI 返回了异常响应，请重试"
    # 兜底：不暴露原始异常
    return "生成过程中出现意外错误，请刷新页面后重试"


# ── 工具函数 ──

def _get_client_ip(websocket: WebSocket) -> str:
    """从 WebSocket 获取真实客户端 IP。支持反向代理（nginx/caddy）场景。"""
    forwarded = websocket.headers.get("x-forwarded-for", "")
    if forwarded:
        # X-Forwarded-For 可能包含多个 IP，取第一个（原始客户端）
        return forwarded.split(",")[0].strip()
    return websocket.client.host if websocket.client else "unknown"


from app.demo import DEMO_TOPICS, load_demo_html
from app.core.metrics import metrics_text
from fastapi import Response


@app.get("/metrics")
async def metrics():
    """Prometheus 指标端点。"""
    return Response(content=metrics_text(), media_type="text/plain")


@app.get("/api/demos/{name}")
async def get_demo(name: str):
    """返回预生成的演示 HTML。"""
    html, cached = load_demo_html(name)
    if html is None:
        return {"error": "未找到该演示"}, 404
    return {"html": html, "name": name, "cached": cached}


@app.get("/api/demos")
async def list_demos():
    """返回可用演示列表及就绪状态。"""
    from app.demo import list_demo_status
    return {"demos": list_demo_status()}


@app.get("/api/rate-limit")
async def get_rate_limit():
    """返回当前费率限制状态（供前端展示剩余次数）。"""
    return rate_limiter.stats


@app.websocket("/ws/generate")
async def generate_page(websocket: WebSocket):
    """WebSocket 端点——接收用户输入，触发 Agent Pipeline，实时推送进度。"""
    session_id = str(uuid.uuid4())[:8]
    client_ip = _get_client_ip(websocket)
    if not await ws_manager.connect(session_id, websocket, client_ip):
        return  # 连接被拒绝（超上限等），不做后续处理

    session_cost_records: list[dict] = []  # 本连接独立记账，不碰全局
    t_start = None  # 用于记录生成开始时间（GENERATION_DURATION 埋点）

    try:
        # 接收用户输入（加超时，防止连接挂起）
        try:
            data = await asyncio.wait_for(websocket.receive_json(), timeout=30)
        except asyncio.TimeoutError:
            await ws_manager.send_failed(session_id, "等待输入超时，请刷新页面后重试", [])
            return

        user_input = data.get("event", "").strip()

        if not user_input:
            await ws_manager.send_failed(session_id, "请输入一个主题", [])
            return

        # P0 安全修复：输入长度限制——防止恶意长文本耗尽 API 预算
        from app.core.config import settings
        if len(user_input) > settings.input_max_length:
            logger.warning("输入过长拒绝 [%s] len=%d max=%d", session_id, len(user_input), settings.input_max_length)
            await ws_manager.send_failed(
                session_id,
                f"输入过长（最多 {settings.input_max_length} 字符），请精简后重试",
                DEMO_TOPICS,
            )
            return

        # ── 速率限制 ──
        allowed, reason = await rate_limiter.can_generate(client_ip)
        if not allowed:
            logger.info("限流拒绝 [%s] IP=%s reason=%s", session_id, client_ip, reason)
            await ws_manager.send_failed(session_id, reason, DEMO_TOPICS)
            return

        logger.info("新请求 | session=%s | topic=%s | ip=%s", session_id, user_input, client_ip)

        # T+0 立即推第一条日志，不等 Agent 启动
        await ws_manager.send_json(session_id, {
            "type": "thinking",
            "step": 0,
            "thought": f"收到主题「{user_input}」，准备策展...",
            "tool": "thinking",
            "budget": 0,
        })

        # 运行编排Agent（包成 Task，断开时能取消）
        import time as _time
        t_start = _time.monotonic()
        from app.agents.orchestrator import orchestrator_node

        failed_sent = False  # 防止双重失败推送
        orch_task: asyncio.Task | None = None

        async def push(msg: dict):
            """实时推送到前端。"""
            nonlocal failed_sent
            if msg.get("type") == "thinking_stream":
                await ws_manager.send_json(session_id, {
                    "type": "thinking_stream", "step": msg["step"],
                    "chunk": msg["chunk"], "tool": msg["tool"],
                    "budget": msg["budget"],
                })
            elif msg.get("type") == "heartbeat":
                await ws_manager.send_json(session_id, {
                    "type": "heartbeat", "tool": msg["tool"],
                    "step": msg["step"], "budget": msg["budget"],
                })
            elif msg.get("type") == "thinking":
                await ws_manager.send_json(session_id, {
                    "type": "thinking", "step": msg["step"],
                    "thought": msg["thought"], "tool": msg["tool"],
                    "budget": msg["budget"],
                })
            elif msg.get("type") == "tool_result":
                await ws_manager.send_json(session_id, {
                    "type": "tool_result", "step": msg["step"],
                    "tool": msg["tool"], "summary": msg["summary"],
                    "budget": msg["budget"],
                })
            elif msg.get("type") == "html_chunk":
                await ws_manager.send_json(session_id, {
                    "type": "html_chunk", "html": msg["html"],
                })
            elif msg.get("type") == "complete":
                await ws_manager.send_page_ready(session_id, msg["html"])
            elif msg.get("type") == "failed":
                await ws_manager.send_failed(session_id, msg["reason"], [])
                failed_sent = True

        # 把独立账本传给编排器（包 Task + 全局超时）
        from app.core.config import settings
        orch_task = asyncio.create_task(
            orchestrator_node({
                "session_id": session_id,
                "user_input": user_input,
                "_push": push,
                "_cost_records": session_cost_records,
            })
        )
        try:
            result = await asyncio.wait_for(orch_task, timeout=settings.generation_timeout)
        except asyncio.TimeoutError:
            orch_task.cancel()
            logger.warning("生成超时 | session=%s | timeout=%ds", session_id, settings.generation_timeout)
            await ws_manager.send_failed(session_id, "生成超时，请稍后重试", DEMO_TOPICS)
            return

        cost = get_cost_summary(session_cost_records)
        logger.info("生成结束 | session=%s | status=%s | steps=%d | cost=¥%.4f | llm_calls=%d",
                    session_id, result.get("status"), result.get("steps"),
                    cost["estimated_cost_rmb"], cost["calls"])

        # 记录花费（在生成结束后累加，用于日预算帽）
        await rate_limiter.record_cost(cost["estimated_cost_rmb"])

        from app.core.metrics import GENERATIONS, GENERATION_DURATION, GENERATION_STEPS
        GENERATIONS.labels(status=result.get("status", "unknown")).inc()
        if t_start:
            GENERATION_DURATION.observe(_time.monotonic() - t_start)
            GENERATION_STEPS.observe(result.get("steps", 0))

        if result.get("status") == "success":
            # 成功才计为一次试用（失败不扣）
            await rate_limiter.record_success(client_ip)
        elif not failed_sent:
            # orchestrator 已经把失败原因推进了 DecisionLog（via push），
            # 这里只在 push 没发过失败消息时才补发
            reason = result.get("reason", "未知原因")
            issues = result.get("issues", [])
            detail = ""
            if issues:
                issue_texts = [f"· {i.get('description', str(i))}" for i in issues[:3]]
                detail = "。具体问题：\n" + "\n".join(issue_texts)
            await ws_manager.send_failed(
                session_id,
                f"AI 在 {result.get('steps', 0)} 步后未能完成「{data.get('event', '')}」：{reason}{detail}",
                [],
            )

    except WebSocketDisconnect:
        if orch_task and not orch_task.done():
            orch_task.cancel()
            logger.info("用户断开，取消生成 | session=%s", session_id)
    except Exception as e:
        logger.exception("生成流程异常")
        try:
            await ws_manager.send_failed(session_id, _friendly_error(e), [])
        except Exception:
            pass
    finally:
        await ws_manager.disconnect(session_id, client_ip)
