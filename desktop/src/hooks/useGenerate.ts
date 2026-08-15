import { useCallback, useRef, useState } from "react";
import { BACKEND_URL } from "../lib/api";
import type { GenParams } from "../lib/api";

/** 生成 WebSocket 地址（http → ws） */
export const WS_URL = `${BACKEND_URL.replace(/^http/, "ws")}/ws/generate`;

export type GenStatus = "idle" | "connecting" | "running" | "ready" | "done" | "error";

type SendOptions = {
  /** 前端设置里的生成参数（会话级覆盖后端配置） */
  params?: GenParams;
  /** 前端 Composer 选中的模型（会话级覆盖后端默认模型） */
  model?: string;
  /** 用户自定义 LLM API Key（会话级覆盖后端默认） */
  apiKey?: string;
  /** 用户自定义 LLM Base URL（会话级覆盖后端默认） */
  apiBase?: string;
  /** 用户选择的搜索服务（{name, apiKey, baseUrl}；不传=不联网） */
  searchService?: { name: string; apiKey: string; baseUrl: string };
  /** 每条 WS 消息（已 JSON.parse） */
  onMessage: (msg: Record<string, unknown>) => void;
  /** 连接失败 / 中途断开 */
  onError?: (reason: string) => void;
};

/** 生成 WebSocket 客户端：连接 /ws/generate，发 event + params，分发消息 */
export function useGenerate() {
  const wsRef = useRef<WebSocket | null>(null);
  const [status, setStatus] = useState<GenStatus>("idle");

  const send = useCallback((event: string, options: SendOptions) => {
    // 关掉上一次的连接（同一时间只跑一个生成）
    if (wsRef.current) {
      wsRef.current.onclose = null;
      wsRef.current.close();
    }

    let settled = false;
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;
    setStatus("connecting");

    ws.onopen = () => {
      setStatus("running");
      const payload: Record<string, unknown> = { event };
      if (options.params) payload.params = options.params;
      if (options.model) payload.model = options.model;
      if (options.apiKey) payload.apiKey = options.apiKey;
      if (options.apiBase) payload.apiBase = options.apiBase;
      if (options.searchService) payload.searchService = options.searchService;
      ws.send(JSON.stringify(payload));
    };

    ws.onmessage = (e) => {
      let msg: Record<string, unknown>;
      try {
        msg = JSON.parse(e.data as string);
      } catch {
        return;
      }
      // page_ready：主生成完成、连接保持（后端在等迭代指令）→ 解锁输入
      if (msg.type === "page_ready") setStatus("ready");
      options.onMessage(msg);
    };

    ws.onerror = () => {
      if (!settled) {
        settled = true;
        setStatus("error");
        options.onError?.("无法连接后端（请确认后端已启动：uvicorn app.main:app --port 8001）");
      }
    };

    ws.onclose = () => {
      if (!settled) {
        settled = true;
        setStatus("done");
      }
      wsRef.current = null;
    };
  }, []);

  const stop = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.onclose = null;
      wsRef.current.close();
      wsRef.current = null;
    }
    setStatus("idle");
  }, []);

  /** 成品迭代：复用已建立的连接，把用户要求作为 instruction 发给后端 refine */
  const sendInstruction = useCallback((instruction: string) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify({ instruction }));
    setStatus("running");
    return true;
  }, []);

  return { status, send, sendInstruction, stop };
}
