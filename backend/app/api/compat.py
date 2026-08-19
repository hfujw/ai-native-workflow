"""OpenAI 兼容网关 — LobeChat 前端接入（Responses API 流式）。

架构（2026-08-19 拍板）：LobeChat（成熟前端，通用层用轮子）→ 本网关 →
orchestrator 深度编排（发散-收敛 / judge / verify / 诚实模式，原封不动）。

为什么是 Responses API：
- LobeChat 2.x 的 Agent 模式（Lobe AI）走 OpenAI Responses API（/v1/responses），
  只有它才支持工具调用展示；chat/completions 是传统聊天。
- 深度编排在**后端服务端自治**，前端只显示思考流文本——所以网关把
  orchestrator 的每步推送转成 `response.output_text.delta` 流式文本，
  LobeChat 显示成 markdown 思考流（spike 已验证此链路）。

职责：
- /v1/responses  主端点：新生成（orchestrator）或迭代（refine_page），SSE 流式
- /v1/models     模型列表（LobeChat 配置服务商用）
- 成品落盘：生成/迭代完成 → save_project + save_page → 返回作品链接
"""

import asyncio
import json
import logging
import time
import uuid

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.tools.search import bind_search_service

logger = logging.getLogger(__name__)

router = APIRouter()

ARTIFACT_MARKER = "✨ 成品已生成"  # 我们回复里的成品标记（迭代识别用）


class ResponsesRequest(BaseModel):
    input: list | None = None  # [{role, content}] 或 Responses 格式
    model: str | None = None
    stream: bool = True
    tools: list | None = None  # LobeChat 可能声明可用工具——我们服务端自治，忽略
    session_id: str | None = None  # WebUI 前端先建会话，前端定 project_id（后端兜底生成）
    # WebUI 前端填的搜索服务 {name, api_key, base_url}（现在固定 Tavily，后续可扩展任意服务；
    # 前端填了就优先，None = 不联网，只走本地 KB）
    search_service: dict | None = None


# ── SSE 工具 ──

def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _parse_input(raw: list | None) -> list[dict]:
    """兼容两种 input 格式：{role, content: str} 或 {role, content: [{type, text}]}。"""
    out: list[dict] = []
    for m in raw or []:
        if not isinstance(m, dict):
            continue
        role = m.get("role", "")
        content = m.get("content", "")
        if isinstance(content, list):  # Responses 格式
            texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("text")]
            content = "\n".join(texts)
        out.append({"role": role, "content": str(content or "")})
    return out


def _last_user_text(msgs: list[dict]) -> str:
    for m in reversed(msgs):
        if m.get("role") == "user":
            return m.get("content", "").strip()
    return ""


def _find_artifact_id(msgs: list[dict]) -> str | None:
    """从对话历史里找我们上次回复里的成品 id（迭代识别）。"""
    for m in reversed(msgs):
        if m.get("role") != "assistant":
            continue
        content = m.get("content", "")
        if ARTIFACT_MARKER not in content:
            continue
        import re
        m2 = re.search(r"[0-9a-f]{8}", content)
        if m2:
            return m2.group(0)
    return None


def _msg_to_text(msg: dict) -> str | None:
    """orchestrator 推送 → 思考流文本（None = 不进文本流）。"""
    t = msg.get("type")
    if t == "thinking":
        return f"{msg.get('thought', '')}\n"
    if t == "thinking_stream":
        return msg.get("chunk", "")
    if t == "tool_result":
        summary = msg.get("summary", "")
        return f"✅ {summary}\n" if summary else None
    if t == "system":
        return None
    if t == "heartbeat":
        return None
    if t == "html_chunk":
        return None  # 渲染过程不进文本流（成品在 final 返回）
    return None


def _msg_structured(msg: dict) -> dict | None:
    """orchestrator 推送 → WebUI 结构化事件（思考块/工具卡）。

    WebUI 模式（前端传 session_id）下，思考流不进 output_text.delta 纯文本，
    而是拆成结构化事件供前端渲染 ReasoningRow / 工具卡片——这就是
    "DecisionLog 思考过程全透明"的载体。LobeChat（无 session_id）保持纯文本。
    """
    t = msg.get("type")
    if t == "thinking":
        text = msg.get("thought", "")
        return {"type": "lumen.reasoning.delta", "text": f"{text}\n"} if text else None
    if t == "thinking_stream":
        chunk = msg.get("chunk", "")
        return {"type": "lumen.reasoning.delta", "text": chunk} if chunk else None
    if t == "tool_result":
        summary = msg.get("summary", "")
        return {"type": "lumen.tool", "summary": summary} if summary else None
    return None


def _friendly_error(e: Exception) -> str:
    msg = str(e).lower()
    if "api key" in msg or "auth" in msg or "unauthorized" in msg:
        return "AI 服务认证失败——请检查模型 API Key"
    if "timeout" in msg or "timed out" in msg:
        return "AI 服务响应超时，请稍后重试"
    if "circuit" in msg:
        return "AI 服务暂时不可用，请稍后重试"
    return "生成失败，请重试"


# ── 主端点 ──

@router.post("/v1/responses")
async def responses(
    req: ResponsesRequest,
    request: Request,
    authorization: str | None = Header(None),
):
    msgs = _parse_input(req.input)
    query = _last_user_text(msgs)
    if not query:
        return JSONResponse(status_code=400, content={"error": "缺少用户消息"})
    # 输入限长（安全护栏）——config.input_max_length
    from app.config import settings
    if len(query) > settings.input_max_length:
        return JSONResponse(
            status_code=400,
            content={"error": f"输入过长（上限 {settings.input_max_length} 字符）"},
        )

    # 会话级 Key：LobeChat 把服务商配置的 API Key 放 Authorization: Bearer
    # （架构延续：Key 不进后端配置，随会话传入；必须在 create_task 前 bind，
    #   contextvar 会随任务复制到 orchestrator 的 LLM 调用）
    api_key = None
    if authorization and authorization.lower().startswith("bearer "):
        api_key = authorization[7:].strip()
    if api_key:
        from app.llm.client import bind_session_client
        bind_session_client(api_key)
        logger.info("compat=session_client | key_bound=%s", bool(api_key))

    # WebUI 前端填的搜索服务 {name, api_key, base_url}——前端填了就优先（后续可扩展任意服务）
    search_svc = req.search_service or None
    if search_svc and (search_svc.get("api_key") or search_svc.get("apiKey") or "").strip():
        bind_search_service(search_svc)
        logger.info("compat=search_bound | svc=%s", search_svc.get("name", "?"))

    rsp_id = f"rsp_{uuid.uuid4().hex[:8]}"
    msg_id = f"msg_{uuid.uuid4().hex[:8]}"
    artifact_id = _find_artifact_id(msgs)

    async def event_gen():
        # ── 开场事件：建立 assistant message item ──
        yield _sse({"type": "response.created", "response": {"id": rsp_id, "object": "response", "status": "in_progress", "output": []}})
        yield _sse({"type": "response.in_progress", "response": {"id": rsp_id, "status": "in_progress", "output": []}})
        yield _sse({"type": "response.output_item.added", "output_index": 0,
                    "item": {"id": msg_id, "type": "message", "status": "in_progress", "role": "assistant", "content": []}})
        yield _sse({"type": "response.content_part.added", "item_id": msg_id, "output_index": 0, "content_index": 0,
                    "part": {"type": "output_text", "text": "", "annotations": []}})

        queue: asyncio.Queue = asyncio.Queue()
        _END = object()  # 终止哨兵：done 后消费完剩余文本再退出（防丢增量）
        terminal = {"done": False, "html": "", "error": ""}
        # WebUI 前端先建会话（session_id=前端 chatId），生成/迭代都沿用同一个
        # project_id；LobeChat 不传 session_id → 退回历史识别 / 后端生成。
        session_id = (req.session_id or artifact_id) or uuid.uuid4().hex[:8]
        # WebUI 模式：session_id 是前端传的 → 思考流拆结构化事件（思考块/工具卡）；
        # 否则（LobeChat）保持纯文本流。
        webui_mode = bool(req.session_id)
        full_text = ""

        async def push(msg: dict):
            nonlocal full_text
            text = _msg_to_text(msg)
            if text:
                # full_text 始终累积纯文本——落盘/回放/refine 识别都用它
                full_text += text
            if webui_mode:
                structured = _msg_structured(msg)
                if structured is not None:
                    await queue.put(structured)
                elif text:
                    await queue.put(text)
            elif text:
                await queue.put(text)
            if msg.get("type") == "complete":
                terminal["done"] = True
                terminal["html"] = msg.get("html", "")
                await queue.put(_END)
            elif msg.get("type") == "failed":
                terminal["done"] = True
                terminal["error"] = msg.get("reason", "生成失败")
                await queue.put(_END)

        # ── 新生成 or 迭代 ──
        from app.agent.orchestrator import orchestrator_node, refine_page

        task: asyncio.Task | None = None
        if artifact_id:
            # 迭代：从 projects.json 恢复上次成品上下文（含编排 state），用户新消息 = 修改指令
            from app.projects import get_project
            proj = get_project(artifact_id) or {}
            last_ver = (proj.get("versions") or [{}])[-1]
            state = proj.get("state") or {}
            state_html = (last_ver or {}).get("html", "") or proj.get("html", "")
            logger.info("compat=refine | session=%s | topic=%s", artifact_id, query)
            task = asyncio.create_task(refine_page(
                state.get("design"), state.get("content"), state.get("material"),
                state_html, proj.get("topic", query), query,
                push, [], model=req.model,
            ))
        else:
            logger.info("compat=generate | session=%s | topic=%s", session_id, query)
            task = asyncio.create_task(orchestrator_node({
                "session_id": session_id, "user_input": query,
                "_push": push, "_cost_records": [], "_params": None, "_model": req.model,
            }))

        result = None
        # ── 流式转发思考文本 ──
        # 断连检测：前端 stop / 关页面 = SSE 断开。Starlette 只在 yield 之间检查断连，
        # 队列长时间无事件时会卡住 → 这里每 1s 轮询一次：断连立即 return（finally 里
        # task.cancel() 取消编排任务，且跳过下方落盘——被删会话不会被救回）。
        # is_disconnected() 用 anyio CancelScope 实现，非阻塞：无缓冲 disconnect 消息即返回 False。
        stall_limit = int(settings.generate_stall_timeout)
        silent_seconds = 0
        try:
            while True:
                if await request.is_disconnected():
                    logger.info("compat=disconnect | session=%s", session_id)
                    return
                try:
                    # 1s 小超时：既允许每轮轮询断连，又不改变"无事件则一直等"的语义。
                    item = await asyncio.wait_for(queue.get(), timeout=1)
                except asyncio.TimeoutError:
                    silent_seconds += 1
                    if silent_seconds >= stall_limit:
                        # 完全静默超时（无任何 SSE 事件）→ 判卡死，走下方超时分支取消任务
                        raise asyncio.TimeoutError
                    continue
                silent_seconds = 0
                if item is _END:
                    break
                if isinstance(item, dict):
                    # WebUI 结构化事件（lumen.reasoning.delta / lumen.tool）原样转发
                    yield _sse(item)
                else:
                    yield _sse({"type": "response.output_text.delta", "item_id": msg_id,
                                "output_index": 0, "content_index": 0, "delta": item})
            if task and not task.done():
                await asyncio.wait_for(task, timeout=30)
            if task and not task.cancelled():
                result = task.result()
        except asyncio.TimeoutError:
            # 静默超时也要让用户看到明确的失败原因（而不是流无声结束）
            terminal["error"] = _friendly_error(asyncio.TimeoutError("timeout"))
            logger.warning("compat=timeout | session=%s", session_id)
        except Exception as e:
            terminal["error"] = _friendly_error(e)
            logger.exception("compat=error | session=%s", session_id)
        finally:
            if task and not task.done():
                task.cancel()

        # ── 最终文本 ──
        final_text = ""
        if terminal["html"]:
            final_text = f"\n\n{ARTIFACT_MARKER} [{session_id}]\nhttp://localhost:8001/works/{session_id}"
        elif terminal["error"]:
            final_text = f"\n\n❌ {terminal['error']}"

        full_text += final_text

        # ── 落盘成品（在 full_text += final_text 之后——落盘消息 = 实时流最终气泡，
        #    历史回放才能和实时流内容一致，mergeLatestHistory 靠 content 重叠合并）──
        if terminal["html"]:
            from app.projects import save_project
            from app.workspace import save_page
            try:
                file_path = save_page(session_id, query, terminal["html"], 1)
                save_project({
                    "id": session_id, "topic": query,
                    "created_at": int(time.time()),
                    "status": "success", "steps": 0, "cost": 0, "iterations": 1,
                    "html": terminal["html"],
                    "trace_path": f"logs/traces/{session_id}.jsonl",
                    "file_path": file_path,
                    "state": {
                        "design": (result or {}).get("design"),
                        "content": (result or {}).get("content"),
                        "material": (result or {}).get("material"),
                    } if result else None,
                    "messages": [
                        {"role": "user", "text": query},
                        {"role": "assistant", "text": full_text, "html": terminal["html"], "file_path": file_path},
                    ],
                })
            except Exception as e:
                logger.warning("compat=save_failed | session=%s | err=%s", session_id, e)

        # ── 收尾事件 ──
        if final_text:
            yield _sse({"type": "response.output_text.delta", "item_id": msg_id,
                        "output_index": 0, "content_index": 0, "delta": final_text})
        yield _sse({"type": "response.output_text.done", "item_id": msg_id,
                    "output_index": 0, "content_index": 0, "text": full_text})
        yield _sse({"type": "response.content_part.done", "item_id": msg_id, "output_index": 0, "content_index": 0,
                    "part": {"type": "output_text", "text": full_text, "annotations": []}})
        yield _sse({"type": "response.output_item.done", "output_index": 0,
                    "item": {"id": msg_id, "type": "message", "status": "completed", "role": "assistant",
                             "content": [{"type": "output_text", "text": full_text, "annotations": []}]}})
        yield _sse({"type": "response.completed", "response": {"id": rsp_id, "status": "completed", "output": []}})
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/v1/models")
async def models():
    """模型列表（LobeChat 自定义服务商探测用）。

    必须返回 DeepSeek 官方名——llm/client.normalize_model() 对未知模型原样透传，
    传品牌名（lumen-deep）会打到 DeepSeek API 报"模型不存在"。
    """
    return {"object": "list", "data": [
        {"id": "deepseek-v4-flash", "object": "model", "owned_by": "deepseek", "created": 0},
    ]}
