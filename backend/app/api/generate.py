"""生成端点 — REST /api/generate + WebSocket /ws/generate（含多轮迭代）。

这是产品主链路：接收主题 → 编排 Agent 生成 → 实时推送 → 多轮迭代 → 落盘历史。
本地桌面端工具：无 IP 限流 / 日预算帽 / Prometheus 指标（公网部署准备已移除）。
"""

import asyncio
import logging
import time
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.ws import ws_manager
from app.demo import DEMO_TOPICS
from app.llm.client import get_cost_summary

logger = logging.getLogger(__name__)

router = APIRouter()


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


# ── Phase C：偏好提取 ──
_PREF_KEYWORDS = ["暗色", "深色", "浅色", "亮色", "极简", "复古", "现代", "黑金", "水墨"]


def _extract_preferences(design: dict | None, content: dict | None) -> dict:
    """从生成结果抽取偏好信号（风格关键词 + 组件偏好）。"""
    vh = (design or {}).get("visual_hint", "") or ""
    hints = [k for k in _PREF_KEYWORDS if k in vh]
    comps = (design or {}).get("components", []) or []
    return {"style_hints": hints[:5], "preferred_components": comps[:3]}


class _GenerateRequest(BaseModel):
    topic: str
    params: dict | None = None  # 前端设置里的生成参数（会话级覆盖）
    model: str | None = None    # 前端 Composer 选择的模型（None=后端默认）


@router.post("/api/generate")
async def generate_api(req: _GenerateRequest):
    """程序化生成——POST 一个话题，同步返回 HTML（复用 orchestrator，无 WS）。"""
    from app.config import settings
    topic = req.topic.strip()
    if not topic or len(topic) > settings.input_max_length:
        # 注意：新版 FastAPI 不再支持 (dict, status) 元组返回——必须用 JSONResponse
        return JSONResponse(
            status_code=400,
            content={"error": f"话题不能为空且不超过 {settings.input_max_length} 字"},
        )

    session_id = str(uuid.uuid4())[:8]
    records: list[dict] = []
    from app.agent.orchestrator import orchestrator_node
    try:
        result = await orchestrator_node({
            "session_id": session_id, "user_input": topic,
            "_push": None, "_cost_records": records, "_preferences": {},
            "_params": req.params, "_model": req.model,
        })
    except Exception:
        raise
    cost = get_cost_summary(records)["estimated_cost_rmb"]

    from app.projects import save_project
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


@router.websocket("/ws/generate")
async def generate_page(websocket: WebSocket):
    """WebSocket 端点——接收用户输入，触发 Agent Pipeline，实时推送进度。"""
    session_id = str(uuid.uuid4())[:8]
    client_ip = websocket.client.host if websocket.client else ""
    if not await ws_manager.connect(session_id, websocket):
        return  # 连接被拒绝（超上限等），不做后续处理

    session_cost_records: list[dict] = []  # 本连接独立记账，不碰全局

    try:
        # 接收用户输入（加超时，防止连接挂起）
        try:
            data = await asyncio.wait_for(websocket.receive_json(), timeout=30)
        except asyncio.TimeoutError:
            await ws_manager.send_failed(session_id, "等待输入超时，请刷新页面后重试", [])
            return

        user_input = data.get("event", "").strip()
        gen_params = data.get("params") or None  # 前端设置里的生成参数（会话级覆盖）
        gen_model = data.get("model") or None    # 前端 Composer 选择的模型（None=后端默认）

        if not user_input:
            await ws_manager.send_failed(session_id, "请输入一个主题", [])
            return

        # 输入长度限制——防止误粘贴超长文本耗尽 API 预算
        from app.config import settings
        if len(user_input) > settings.input_max_length:
            logger.warning("输入过长拒绝 [%s] len=%d max=%d", session_id, len(user_input), settings.input_max_length)
            await ws_manager.send_failed(
                session_id,
                f"输入过长（最多 {settings.input_max_length} 字符），请精简后重试",
                DEMO_TOPICS,
            )
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
        from app.agent.orchestrator import orchestrator_node

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
            from app.preferences import get_preferences
            prefs = await get_preferences()
        except Exception:
            prefs = {}

        # 把独立账本传给编排器（包 Task + 全局超时）
        orch_task = asyncio.create_task(
            orchestrator_node({
                "session_id": session_id,
                "user_input": user_input,
                "_push": push,
                "_cost_records": session_cost_records,
                "_preferences": prefs,
                "_params": gen_params,
                "_model": gen_model,
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

        # 保存生成历史（可回看/续，Phase C 更新迭代数）
        from app.projects import save_project
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

        if result.get("status") == "success":
            # ── Phase C：提取偏好 + 多轮迭代 ──
            prefs = _extract_preferences(result.get("design"), result.get("content"))
            if prefs["style_hints"] or prefs["preferred_components"]:
                from app.preferences import update_preferences
                await update_preferences(prefs)
            iterations = 1
            MAX_ITERATIONS = 6  # 迭代上限（首轮 + 最多 5 次修改），防无限烧 token
            while iterations < MAX_ITERATIONS:
                try:
                    follow = await asyncio.wait_for(websocket.receive_json(), timeout=600)
                except (asyncio.TimeoutError, WebSocketDisconnect):
                    break
                instruction = (follow.get("instruction") or "").strip()
                if not instruction:
                    break
                # 指令同样限长——防超长 prompt 烧 token（topic 已有校验，指令此前无）
                if len(instruction) > settings.input_max_length:
                    await ws_manager.send_json(session_id, {
                        "type": "thinking", "step": 0,
                        "thought": f"这条修改要求太长了（最多 {settings.input_max_length} 字），请精简后重试。",
                        "tool": "system", "budget": 0,
                    })
                    continue
                # 迭代计入本次预算上限——防单会话迭代无限烧 token（orchestrator 只罩首轮）
                if get_cost_summary(session_cost_records)["estimated_cost_rmb"] >= settings.budget_total:
                    await ws_manager.send_json(session_id, {
                        "type": "thinking", "step": 0,
                        "thought": f"本次生成已达预算上限（¥{settings.budget_total}），迭代暂停。",
                        "tool": "system", "budget": 0,
                    })
                    break
                iterations += 1
                from app.agent.orchestrator import refine_page
                try:
                    ref = await refine_page(
                        result.get("design"), result.get("content"),
                        result.get("material"), result.get("html", ""),
                        user_input, instruction, push, session_cost_records,
                        preferences=prefs,
                        model=gen_model,
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
        await ws_manager.disconnect(session_id)
