"""AI-Native Workflow — FastAPI 入口。"""

import logging
import os
import sys
import time
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
# 业务 import
# ═══════════════════════════════════════════════════════════════
import asyncio
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.llm.client import get_cost_summary
from app.network.rate_limiter import rate_limiter
from app.network.ws_manager import ws_manager


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

    from app.demo import DEMO_TOPICS, DEMOS_DIR

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
    """从 WebSocket 获取真实客户端 IP。

    仅在配置了反向代理（TRUST_PROXY=true，如 docker-compose + Caddy）时信任
    X-Forwarded-For，否则直接取 TCP 对端 IP——防止客户端伪造 XFF 绕过 IP 限流。
    取最后一个值：Caddy 会把真实客户端 IP 追加到 XFF 末尾，客户端塞在开头的伪造值被忽略。
    """
    from app.core.config import settings
    if settings.trust_proxy:
        forwarded = websocket.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[-1].strip()
    return websocket.client.host if websocket.client else "unknown"


# ── Phase C：偏好提取 ──
_PREF_KEYWORDS = ["暗色", "深色", "浅色", "亮色", "极简", "复古", "现代", "黑金", "水墨"]


def _extract_preferences(design: dict | None, content: dict | None) -> dict:
    """从生成结果抽取偏好信号（风格关键词 + 组件偏好）。"""
    vh = (design or {}).get("visual_hint", "") or ""
    hints = [k for k in _PREF_KEYWORDS if k in vh]
    comps = (design or {}).get("components", []) or []
    return {"style_hints": hints[:5], "preferred_components": comps[:3]}


from fastapi import Response

from app.core.metrics import metrics_text
from app.demo import DEMO_TOPICS, load_demo_html


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
    return await rate_limiter.stats()


@app.get("/api/eval")
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


# ═══════════════════════════════════════════════════════════════
# Phase E: REST API（程序化调用——demo → 系统）
# ═══════════════════════════════════════════════════════════════

class _GenerateRequest(BaseModel):
    topic: str


class _PreferenceRequest(BaseModel):
    style_hints: list[str] = []
    preferred_components: list[str] = []


@app.post("/api/generate")
async def generate_api(req: _GenerateRequest, request: Request):
    """程序化生成——POST 一个话题，同步返回 HTML（复用 orchestrator，无 WS）。"""
    from app.core.config import settings
    topic = req.topic.strip()
    if not topic or len(topic) > settings.input_max_length:
        return {"error": f"话题不能为空且不超过 {settings.input_max_length} 字"}, 400

    # 限流（REST 也受 IP 试用/日预算约束）
    ip = request.client.host if request.client else "unknown"
    allowed, reason = await rate_limiter.can_generate(ip)
    if not allowed:
        return {"error": reason}, 429

    session_id = str(uuid.uuid4())[:8]
    records: list[dict] = []
    from app.agents.orchestrator import orchestrator_node
    result = await orchestrator_node({
        "session_id": session_id, "user_input": topic,
        "_push": None, "_cost_records": records, "_preferences": {},
    })
    cost = get_cost_summary(records)["estimated_cost_rmb"]
    await rate_limiter.record_cost(cost)
    if result.get("status") == "success":
        await rate_limiter.record_success(ip)

    from app.core.projects import save_project
    save_project({
        "id": session_id, "topic": topic, "created_at": int(time.time()),
        "status": result.get("status", "unknown"),
        "steps": result.get("steps", 0), "cost": cost, "iterations": 1,
        "html": result.get("html", ""), "trace_path": f"logs/traces/{session_id}.jsonl",
    })
    return {
        "project_id": session_id, "topic": topic,
        "status": result.get("status"),
        "html": result.get("html", ""),
        "steps": result.get("steps", 0),
        "cost": cost,
    }


@app.get("/api/history")
async def list_history():
    """生成历史列表（新的在前）。"""
    from app.core.projects import get_projects
    return {"projects": get_projects()}


@app.get("/api/history/{project_id}")
async def get_history(project_id: str):
    """单个生成记录（可回看页面）。"""
    from app.core.projects import get_project
    project = get_project(project_id)
    if project is None:
        return {"error": "未找到该项目"}, 404
    return project


@app.get("/api/preferences")
async def get_pref():
    """当前用户偏好。"""
    from app.core.preferences import get_preferences
    return await get_preferences()


@app.put("/api/preferences")
async def put_pref(req: _PreferenceRequest):
    """更新用户偏好。"""
    from app.core.preferences import update_preferences
    return await update_preferences(req.model_dump(exclude_defaults=True))


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
                    "type": "thinking_stream", "step": msg.get("step", 0),
                    "chunk": msg.get("chunk", ""), "tool": msg.get("tool", ""),
                    "budget": msg.get("budget", 0),
                })
            elif msg.get("type") == "heartbeat":
                await ws_manager.send_json(session_id, {
                    "type": "heartbeat", "tool": msg.get("tool", ""),
                    "step": msg.get("step", 0), "budget": msg.get("budget", 0),
                })
            elif msg.get("type") == "thinking":
                await ws_manager.send_json(session_id, {
                    "type": "thinking", "step": msg.get("step", 0),
                    "thought": msg.get("thought", ""), "tool": msg.get("tool", ""),
                    "budget": msg.get("budget", 0),
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

        # 读用户偏好（记忆注入）——失败不阻断生成
        try:
            from app.core.preferences import get_preferences
            prefs = await get_preferences()
        except Exception:
            prefs = {}

        # 把独立账本传给编排器（包 Task + 全局超时）
        from app.core.config import settings
        orch_task = asyncio.create_task(
            orchestrator_node({
                "session_id": session_id,
                "user_input": user_input,
                "_push": push,
                "_cost_records": session_cost_records,
                "_preferences": prefs,
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

        # 保存生成历史（可回看/续，Phase C 更新迭代数）
        from app.core.projects import save_project
        save_project({
            "id": session_id,
            "topic": user_input,
            "created_at": int(_time.time()),
            "status": result.get("status", "unknown"),
            "steps": result.get("steps", 0),
            "cost": cost["estimated_cost_rmb"],
            "iterations": 1,
            "html": result.get("html", ""),
            "trace_path": f"logs/traces/{session_id}.jsonl",
        })

        from app.core.metrics import GENERATION_DURATION, GENERATION_STEPS, GENERATIONS
        GENERATIONS.labels(status=result.get("status", "unknown")).inc()
        if t_start:
            GENERATION_DURATION.observe(_time.monotonic() - t_start)
            GENERATION_STEPS.observe(result.get("steps", 0))

        if result.get("status") == "success":
            # 成功才计为一次试用（失败不扣）
            await rate_limiter.record_success(client_ip)

            # ── Phase C：提取偏好 + 多轮迭代 ──
            prefs = _extract_preferences(result.get("design"), result.get("content"))
            if prefs["style_hints"] or prefs["preferred_components"]:
                from app.core.preferences import update_preferences
                await update_preferences(prefs)
            iterations = 1
            last_cost = cost["estimated_cost_rmb"]  # 首轮成本已记入日预算
            MAX_ITERATIONS = 6  # 迭代上限（首轮 + 最多 5 次修改），防无限烧 token
            while iterations < MAX_ITERATIONS:
                try:
                    follow = await asyncio.wait_for(websocket.receive_json(), timeout=600)
                except (asyncio.TimeoutError, WebSocketDisconnect):
                    break
                instruction = (follow.get("instruction") or "").strip()
                if not instruction:
                    break
                iterations += 1
                from app.agents.orchestrator import refine_page
                try:
                    ref = await refine_page(
                        result.get("design"), result.get("content"),
                        result.get("material"), result.get("html", ""),
                        user_input, instruction, push, session_cost_records,
                        preferences=prefs,
                    )
                except Exception as e:
                    logger.warning("迭代失败 | session=%s | error=%s", session_id, e)
                    await ws_manager.send_json(session_id, {
                        "type": "thinking", "step": 0,
                        "thought": "这步修改没成功，换个说法再试。", "tool": "system", "budget": 0,
                    })
                    continue
                result["design"] = ref.get("design")
                result["content"] = ref.get("content")
                result["material"] = ref.get("material")
                result["html"] = ref.get("html", "")
                # 记录本轮迭代成本到日预算（防白嫖 token）
                new_cost = get_cost_summary(session_cost_records)["estimated_cost_rmb"]
                if new_cost > last_cost:
                    await rate_limiter.record_cost(new_cost - last_cost)
                    last_cost = new_cost
                # 本轮偏好更新
                prefs = _extract_preferences(ref.get("design"), ref.get("content"))
                if prefs["style_hints"] or prefs["preferred_components"]:
                    await update_preferences(prefs)
                # 更新历史（同 id 覆盖，迭代数 +）
                save_project({
                    "id": session_id, "topic": user_input,
                    "created_at": int(_time.time()),
                    "status": "success",
                    "steps": result.get("steps", 0),
                    "cost": get_cost_summary(session_cost_records)["estimated_cost_rmb"],
                    "iterations": iterations,
                    "html": result["html"],
                    "trace_path": f"logs/traces/{session_id}.jsonl",
                })
                # 推送新版本
                await ws_manager.send_page_ready(session_id, result["html"])
            if iterations >= MAX_ITERATIONS:
                await ws_manager.send_json(session_id, {
                    "type": "thinking", "step": 0,
                    "thought": "已达本轮修改上限，可换个新话题重新生成。",
                    "tool": "system", "budget": 0,
                })
        elif not failed_sent:
            # orchestrator 已经把失败原因推进了 DecisionLog（via push），
            # 这里只在 push 没发过失败消息时才补发
            reason = result.get("reason", "未知原因")
            issues = result.get("issues", [])
            detail = ""
            if issues:
                issue_texts = [f"· {i.get('description', str(i))}" for i in issues[:99] if isinstance(i, dict)]
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
