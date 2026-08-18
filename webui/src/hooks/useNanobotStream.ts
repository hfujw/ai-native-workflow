import { useCallback, useEffect, useRef, useState } from "react";

import { useClient } from "@/providers/ClientProvider";
import { hasPendingAgentActivity } from "@/lib/activity-timeline";
import type { StreamError } from "@/lib/nanobot-client";
import {
  finalizeStreamedTurn,
  findActiveAssistantPlaceholderIndex,
  findStreamingAssistantIndex,
  isReasoningOnlyPlaceholder,
  matchesTurn,
  pruneReasoningOnlyPlaceholders,
  replaceMessageAt,
  stampLastAssistantCompletion,
} from "@/lib/thread-event-projection";
import type { UIMessageTurnFields } from "@/lib/thread-event-projection";
import { formatQuotedUserMessage } from "@/lib/user-message-quote";
import type {
  OutboundCliAppMention,
  OutboundMcpPresetMention,
  OutboundMedia,
  SessionMention,
  GoalStateWsPayload,
  MessageDeliveryStatus,
  UIMediaAttachment,
  UIMessage,
  WorkspaceScopePayload,
} from "@/lib/types";

interface StreamBuffer {
  /** ID of the assistant message currently receiving deltas (cleared when its segment closes). */
  messageId: string;
}

interface ActiveAssistantCursor {
  id: string;
  index: number;
}

type PendingStreamEvent =
  | { kind: "delta"; text: string; turn: UIMessageTurnFields; source?: UIMessage["source"] }
  | { kind: "reasoning"; text: string; turn: UIMessageTurnFields };

const BACKGROUND_STREAM_FLUSH_INTERVAL_MS = 1_000;

/**
 * Append a reasoning chunk to the last open reasoning stream in ``prev``.
 *
 * Lookup rule: reasoning can only extend the current reasoning placeholder.
 * Once ordinary answer text has appeared, the next reasoning chunk starts a
 * fresh Thought block so streamed output stays in arrival order:
 * Thought -> answer -> Thought -> answer.
 */
function attachReasoningChunk(
  prev: UIMessage[],
  chunk: string,
  segments?: {
    ensure: () => string;
  },
  turn: UIMessageTurnFields = {},
): UIMessage[] {
  for (let i = prev.length - 1; i >= 0; i -= 1) {
    const candidate = prev[i];
    // A user turn is a hard boundary: reasoning after it belongs to the new
    // assistant turn, never to an earlier assistant reply.
    if (candidate.role === "user") break;
    // A trace row (e.g. Used tools) is also a phase boundary. Reasoning after
    // tools belongs to the next assistant iteration, not the assistant turn
    // that produced those tool calls.
    if (candidate.kind === "trace") break;
    if (candidate.role !== "assistant") continue;
    if (!matchesTurn(candidate, turn)) break;
    const activitySegmentId = candidate.activitySegmentId ?? segments?.ensure();
    const hasAnswer = candidate.content.length > 0;
    if (hasAnswer) break;
    if (
      candidate.reasoningStreaming
      || candidate.reasoning !== undefined
      || candidate.isStreaming
    ) {
      const merged: UIMessage = {
        ...candidate,
        reasoning: (candidate.reasoning ?? "") + chunk,
        reasoningStreaming: true,
        ...(activitySegmentId ? { activitySegmentId } : {}),
        ...turn,
      };
      return [...prev.slice(0, i), merged, ...prev.slice(i + 1)];
    }
    break;
  }
  const activitySegmentId = segments?.ensure();
  return [
    ...prev,
    {
      id: crypto.randomUUID(),
      role: "assistant",
      content: "",
      isStreaming: true,
      reasoning: chunk,
      reasoningStreaming: true,
      ...(activitySegmentId ? { activitySegmentId } : {}),
      ...turn,
      createdAt: Date.now(),
    },
  ];
}

/**
 * Subscribe to a chat by ID. Returns the in-memory message list for the chat,
 * a streaming flag, and a ``send`` function. Initial history must be seeded
 * separately (e.g. via ``fetchWebuiThread``) since the server only replays
 * live events.
 */
/** Payload passed to ``send`` when the user attaches one or more files.
 *
 * ``media`` is handed to the wire client verbatim; ``preview`` powers the
 * optimistic user bubble. Keeping the two separate lets the bubble re-use the
 * local data URL even after the server persists the file under a different
 * name. */
export interface SendAttachment {
  media: OutboundMedia;
  preview: UIMediaAttachment;
}

export interface SendOptions {
  cliApps?: OutboundCliAppMention[];
  mcpPresets?: OutboundMcpPresetMention[];
  sessionMentions?: SessionMention[];
  quotedContext?: string;
  workspaceScope?: WorkspaceScopePayload | null;
  sideChannel?: boolean;
  finalizeActiveTurn?: boolean;
  /** Append guidance to the running turn without detaching its active answer segment. */
  continueActiveTurn?: boolean;
}

export interface SubmittedTurn {
  turnId: string;
  userMessageId: string;
  sideChannel: boolean;
}

function transitionTurnDelivery(
  messages: UIMessage[],
  turnId: string,
  status: MessageDeliveryStatus,
): UIMessage[] {
  let changed = false;
  const next = messages.map((message) => {
    if (
      message.role !== "user"
      || message.turnId !== turnId
      || message.deliveryStatus === status
      || (status === "accepted" && message.deliveryStatus !== "sending")
    ) {
      return message;
    }
    changed = true;
    return { ...message, deliveryStatus: status };
  });
  return changed ? next : messages;
}

/** 组装 /v1/responses 的 input：历史里 user/assistant 文本行 + 最新一条用户消息。
 *
 * 附带完整历史（含上一轮 assistant 的 `✨ 成品已生成 [id]` 标记）——后端
 * compat._find_artifact_id 靠它识别"迭代"而不是新生成。
 */
function buildResponsesInput(
  messages: UIMessage[],
  newContent: string,
): { role: string; content: string }[] {
  const rows: { role: string; content: string }[] = [];
  for (const message of messages) {
    if (message.role !== "user" && message.role !== "assistant") continue;
    const content = message.content.trim();
    if (!content) continue;
    rows.push({ role: message.role, content });
  }
  const trimmed = newContent.trim();
  if (trimmed) rows.push({ role: "user", content: trimmed });
  return rows;
}

export function useNanobotStream(
  chatId: string | null,
  initialMessages: UIMessage[] = [],
  hasPendingToolCalls = false,
  onTurnEnd?: () => void,
): {
  messages: UIMessage[];
  /** Whether ``messages`` belongs to the current ``chatId`` after a session switch. */
  messagesReady: boolean;
  isStreaming: boolean;
  /** Unix epoch seconds when the current user turn started (WebSocket ``goal_status``). */
  runStartedAt: number | null;
  /** Latest sustained goal for this ``chatId`` (``goal_state`` WS events). */
  goalState: GoalStateWsPayload | undefined;
  send: (
    content: string,
    images?: SendAttachment[],
    options?: SendOptions,
  ) => SubmittedTurn | null;
  transcribeAudio: (dataUrl: string, options?: { durationMs?: number }) => Promise<string>;
  stop: () => void;
  /** Mark an accepted canonical snapshot as the definitive end of the active turn. */
  reconcileTurnComplete: () => void;
  setMessages: React.Dispatch<React.SetStateAction<UIMessage[]>>;
  /** Latest transport-level fault raised since the last ``dismissStreamError``.
   * ``null`` when there is nothing to show. */
  streamError: StreamError | null;
  /** Clear the current ``streamError`` (e.g. after the user dismisses the
   * notification or starts a fresh action). */
  dismissStreamError: () => void;
} {
  const { client } = useClient();
  const initialRunStartedAt = chatId ? client.getRunStartedAt(chatId) : null;
  const [messages, setMessages] = useState<UIMessage[]>(initialMessages);
  const [messageOwnerChatId, setMessageOwnerChatId] = useState(chatId);
  /** If history ends in unfinished agent activity, keep the loading spinner alive. */
  const initialStreaming = hasPendingAgentActivity(initialMessages);
  const [isStreaming, setIsStreaming] = useState(
    initialStreaming || hasPendingToolCalls || initialRunStartedAt !== null,
  );
  /** Unix epoch seconds when the current user turn started; cleared on ``idle``. */
  const [runStartedAt, setRunStartedAt] = useState<number | null>(initialRunStartedAt);
  const [goalState, setGoalState] = useState<GoalStateWsPayload | undefined>(undefined);
  const [streamError, setStreamError] = useState<StreamError | null>(null);
  const buffer = useRef<StreamBuffer | null>(null);
  const activeAssistantRef = useRef<ActiveAssistantCursor | null>(null);
  const closedAssistantStreamIdsRef = useRef<Set<string>>(new Set());
  const activitySegmentRef = useRef<string | null>(null);
  const fileEditSegmentRef = useRef<string | null>(null);
  const activitySegmentCounterRef = useRef(0);
  const pendingStreamEventsRef = useRef<PendingStreamEvent[]>([]);
  const streamFrameRef = useRef<number | null>(null);
  const streamTimerRef = useRef<number | null>(null);
  const suppressStreamUntilTurnEndRef = useRef(false);
  const sideChannelTurnIdsRef = useRef<Set<string>>(new Set());
  /** Timer that defers ``isStreaming = false`` after ``stream_end``.
   *
   * When the model finishes a text segment and calls a tool, the server
   * sends ``stream_end`` but the agent is still "thinking" while the tool
   * executes.  By deferring the flag reset by a short window (1 s) we keep
   * the loading spinner alive across tool-call boundaries without needing
   * backend changes. */
  const streamEndTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  /** task 13（Lumen）：在飞 /v1/responses SSE 请求的取消句柄；stop/切会话时中止。 */
  const activeSseAbortRef = useRef<AbortController | null>(null);
  /** task 13（Lumen）：最新消息快照——send 组装 /v1/responses 历史时用（state 异步，用 ref 同步读）。 */
  const messagesRef = useRef<UIMessage[]>(messages);
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  const dismissStreamError = useCallback(() => setStreamError(null), []);

  const clearPendingStreamWork = useCallback(() => {
    if (streamFrameRef.current !== null) {
      window.cancelAnimationFrame(streamFrameRef.current);
      streamFrameRef.current = null;
    }
    if (streamTimerRef.current !== null) {
      window.clearTimeout(streamTimerRef.current);
      streamTimerRef.current = null;
    }
    pendingStreamEventsRef.current = [];
  }, []);

  const cancelStreamEndTimer = useCallback(() => {
    if (streamEndTimerRef.current === null) return;
    clearTimeout(streamEndTimerRef.current);
    streamEndTimerRef.current = null;
  }, []);

  const createActivitySegmentId = useCallback((activate = true) => {
    activitySegmentCounterRef.current += 1;
    const id = `activity-${activitySegmentCounterRef.current}`;
    if (activate) activitySegmentRef.current = id;
    return id;
  }, []);

  const freshActivitySegmentId = useCallback(
    () => createActivitySegmentId(true),
    [createActivitySegmentId],
  );

  const ensureActivitySegmentId = useCallback(() => {
    if (activitySegmentRef.current) return activitySegmentRef.current;
    return freshActivitySegmentId();
  }, [freshActivitySegmentId]);

  const clearActivitySegment = useCallback(() => {
    activitySegmentRef.current = null;
    fileEditSegmentRef.current = null;
  }, []);

  const closeActiveAssistantStream = useCallback(() => {
    const closedStreamId = buffer.current?.messageId ?? activeAssistantRef.current?.id;
    if (closedStreamId) closedAssistantStreamIdsRef.current.add(closedStreamId);
    buffer.current = null;
    activeAssistantRef.current = null;
    return !!closedStreamId;
  }, []);

  const applyStreamError = useCallback((err: StreamError) => {
    // One multiplexed client serves every thread. A correlated send fault
    // belongs only to its target chat. An uncorrelated transport close can
    // still be shown in the mounted thread, but cannot roll back any turn.
    if (!chatId || (err.chatId && err.chatId !== chatId)) return;
    setStreamError(err);
    if (!err.turnId) return;

    const rejectedTurnId = err.turnId;
    pendingStreamEventsRef.current = pendingStreamEventsRef.current.filter(
      (event) => event.turn.turnId !== rejectedTurnId,
    );
    sideChannelTurnIdsRef.current.delete(rejectedTurnId);
    cancelStreamEndTimer();
    setMessages((prev) => {
      const rejectedRows = prev.filter((message) => message.turnId === rejectedTurnId);
      if (rejectedRows.length === 0) return prev;
      const rejectedIds = new Set(rejectedRows.map((message) => message.id));
      const rejectedSegments = new Set(
        rejectedRows
          .map((message) => message.activitySegmentId)
          .filter((segmentId): segmentId is string => typeof segmentId === "string"),
      );
      if (
        activeAssistantRef.current
        && rejectedIds.has(activeAssistantRef.current.id)
      ) {
        activeAssistantRef.current = null;
      }
      if (buffer.current && rejectedIds.has(buffer.current.messageId)) {
        buffer.current = null;
      }
      for (const id of rejectedIds) closedAssistantStreamIdsRef.current.delete(id);
      if (
        activitySegmentRef.current
        && rejectedSegments.has(activitySegmentRef.current)
      ) {
        activitySegmentRef.current = null;
      }
      if (
        fileEditSegmentRef.current
        && rejectedSegments.has(fileEditSegmentRef.current)
      ) {
        fileEditSegmentRef.current = null;
      }
      return prev.flatMap((message) => {
        if (message.turnId !== rejectedTurnId) return [message];
        if (message.role !== "user") return [];
        return [{
          ...message,
          deliveryStatus: "failed",
          deliveryErrorKind: err.kind,
        }];
      });
    });

    const remainingStartedAt = client.getRunStartedAt(chatId);
    const hasRemainingRun = (
      remainingStartedAt !== null
      || client.hasUnsettledRun(chatId)
    );
    setRunStartedAt(remainingStartedAt);
    setIsStreaming(hasRemainingRun);
    if (!hasRemainingRun) suppressStreamUntilTurnEndRef.current = false;
  }, [cancelStreamEndTimer, chatId, client]);

  useEffect(() => client.onError(applyStreamError), [applyStreamError, client]);

  const resolveActiveAssistantIndex = useCallback((
    prev: UIMessage[],
    turn: UIMessageTurnFields = {},
  ): number | null => {
    const cursor = activeAssistantRef.current;
    if (!cursor) return null;
    const indexed = prev[cursor.index];
    if (
      indexed?.id === cursor.id
      && indexed.role === "assistant"
      && indexed.kind !== "trace"
      && indexed.isStreaming
      && matchesTurn(indexed, turn)
    ) {
      return cursor.index;
    }
    const idx = prev.findIndex((m) => m.id === cursor.id);
    if (idx === -1) {
      activeAssistantRef.current = null;
      return null;
    }
    const found = prev[idx];
    if (
      found.role !== "assistant"
      || found.kind === "trace"
      || !found.isStreaming
      || !matchesTurn(found, turn)
    ) {
      activeAssistantRef.current = null;
      return null;
    }
    activeAssistantRef.current = { id: cursor.id, index: idx };
    return idx;
  }, []);

  const appendAnswerChunk = useCallback(
    (
      prev: UIMessage[],
      chunk: string,
      turn: UIMessageTurnFields = {},
      source?: UIMessage["source"],
    ): UIMessage[] => {
      let next = prev;
      let targetIndex = resolveActiveAssistantIndex(next, turn);

      if (targetIndex === null) {
        targetIndex = findActiveAssistantPlaceholderIndex(next, turn);
      }
      if (targetIndex === null) {
        targetIndex = findStreamingAssistantIndex(next, closedAssistantStreamIdsRef.current, turn);
      }
      if (targetIndex === null) {
        const id = crypto.randomUUID();
        next = [
          ...next,
          {
            id,
            role: "assistant",
            content: "",
            isStreaming: true,
            createdAt: Date.now(),
          },
        ];
        targetIndex = next.length - 1;
      }

      const target = next[targetIndex];
      const merged: UIMessage = {
        ...target,
        content: target.content + chunk,
        isStreaming: true,
        ...turn,
        ...(source ? { source } : {}),
      };
      closedAssistantStreamIdsRef.current.delete(merged.id);
      activeAssistantRef.current = { id: merged.id, index: targetIndex };
      buffer.current = { messageId: merged.id };
      return replaceMessageAt(next, targetIndex, merged);
    },
    [resolveActiveAssistantIndex],
  );

  const applyPendingStreamEvents = useCallback(
    (prev: UIMessage[], events: PendingStreamEvent[]): UIMessage[] => {
      let next = prev;
      for (const event of events) {
        if (event.kind === "delta") {
          next = appendAnswerChunk(next, event.text, event.turn, event.source);
        } else {
          if (closeActiveAssistantStream()) clearActivitySegment();
          next = attachReasoningChunk(
            next,
            event.text,
            { ensure: ensureActivitySegmentId },
            event.turn,
          );
        }
      }
      return next;
    },
    [appendAnswerChunk, clearActivitySegment, closeActiveAssistantStream, ensureActivitySegmentId],
  );

  const flushPendingStreamEvents = useCallback((options?: {
    closeAnswerSegment?: boolean;
    finalAnswerText?: string;
    turn?: UIMessageTurnFields;
    source?: UIMessage["source"];
  }) => {
    if (streamFrameRef.current !== null) {
      window.cancelAnimationFrame(streamFrameRef.current);
      streamFrameRef.current = null;
    }
    if (streamTimerRef.current !== null) {
      window.clearTimeout(streamTimerRef.current);
      streamTimerRef.current = null;
    }
    const events = pendingStreamEventsRef.current;
    const finalAnswerText = options?.finalAnswerText;
    const turn = options?.turn ?? {};
    const source = options?.source;
    if (events.length === 0 && finalAnswerText === undefined && source === undefined) {
      if (options?.closeAnswerSegment) closeActiveAssistantStream();
      return;
    }
    pendingStreamEventsRef.current = [];
    setMessages((prev) => {
      let next = events.length > 0 ? applyPendingStreamEvents(prev, events) : prev;
      if (finalAnswerText !== undefined) {
        const targetIndex =
          resolveActiveAssistantIndex(next, turn)
          ?? findStreamingAssistantIndex(next, closedAssistantStreamIdsRef.current, turn);
        if (targetIndex !== null) {
          const target = next[targetIndex];
          const merged = {
            ...target,
            content: finalAnswerText,
            isStreaming: true,
            ...turn,
            ...(source ? { source } : {}),
          };
          next = replaceMessageAt(next, targetIndex, merged);
          if (!options?.closeAnswerSegment) {
            closedAssistantStreamIdsRef.current.delete(merged.id);
            activeAssistantRef.current = { id: merged.id, index: targetIndex };
            buffer.current = { messageId: merged.id };
          }
        } else {
          const id = crypto.randomUUID();
          next = [
            ...next,
            {
              id,
              role: "assistant",
              content: finalAnswerText,
              isStreaming: true,
              ...turn,
              ...(source ? { source } : {}),
              createdAt: Date.now(),
            },
          ];
          if (options?.closeAnswerSegment) {
            closedAssistantStreamIdsRef.current.add(id);
          } else {
            activeAssistantRef.current = { id, index: next.length - 1 };
            buffer.current = { messageId: id };
          }
        }
      } else if (source) {
        const targetIndex =
          resolveActiveAssistantIndex(next, turn)
          ?? findStreamingAssistantIndex(next, closedAssistantStreamIdsRef.current, turn);
        if (targetIndex !== null) {
          const target = next[targetIndex];
          next = replaceMessageAt(next, targetIndex, {
            ...target,
            ...turn,
            source,
          });
        }
      }
      if (options?.closeAnswerSegment) closeActiveAssistantStream();
      return next;
    });
  }, [applyPendingStreamEvents, closeActiveAssistantStream, resolveActiveAssistantIndex]);

  const schedulePendingStreamFlush = useCallback(() => {
    if (streamFrameRef.current !== null || streamTimerRef.current !== null) return;
    if (document.visibilityState === "hidden") {
      streamTimerRef.current = window.setTimeout(() => {
        streamTimerRef.current = null;
        const events = pendingStreamEventsRef.current;
        if (events.length === 0) return;
        pendingStreamEventsRef.current = [];
        setMessages((prev) => applyPendingStreamEvents(prev, events));
      }, BACKGROUND_STREAM_FLUSH_INTERVAL_MS);
      return;
    }
    streamFrameRef.current = window.requestAnimationFrame(() => {
      streamFrameRef.current = null;
      const events = pendingStreamEventsRef.current;
      if (events.length === 0) return;
      pendingStreamEventsRef.current = [];
      setMessages((prev) => applyPendingStreamEvents(prev, events));
    });
  }, [applyPendingStreamEvents]);

  useEffect(() => {
    const flushOnReturn = () => {
      if (document.visibilityState !== "visible") return;
      if (pendingStreamEventsRef.current.length === 0) return;
      flushPendingStreamEvents();
    };
    document.addEventListener("visibilitychange", flushOnReturn);
    return () => document.removeEventListener("visibilitychange", flushOnReturn);
  }, [flushPendingStreamEvents]);

  useEffect(() => {
    return client.onStatus((status) => {
      if (status !== "reconnecting" && status !== "closed") return;
      // A transport drop does not prove the backend turn completed. Keep the
      // semantic running state intact so queued guidance is not flushed early.
      cancelStreamEndTimer();
    });
  }, [cancelStreamEndTimer, client]);

  // Reset local state when switching chats. Do not reset on every
  // ``initialMessages`` update: a brand-new chat can receive an empty/404
  // history response after the optimistic first message has already rendered.
  useEffect(() => {
    // 切会话：中止上一会话在飞的 SSE 请求，防止串流。
    activeSseAbortRef.current?.abort();
    activeSseAbortRef.current = null;
    const restoredRunStartedAt = chatId ? client.getRunStartedAt(chatId) : null;
    setMessages(initialMessages);
    setMessageOwnerChatId(chatId);
    setIsStreaming(
      hasPendingAgentActivity(initialMessages)
      || hasPendingToolCalls
      || restoredRunStartedAt !== null,
    );
    setStreamError(null);
    setRunStartedAt(restoredRunStartedAt);
    setGoalState(chatId ? client.getGoalState(chatId) : undefined);
    buffer.current = null;
    activeAssistantRef.current = null;
    closedAssistantStreamIdsRef.current.clear();
    clearActivitySegment();
    clearPendingStreamWork();
    sideChannelTurnIdsRef.current.clear();
    suppressStreamUntilTurnEndRef.current = false;
    cancelStreamEndTimer();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatId, client, cancelStreamEndTimer, clearActivitySegment, clearPendingStreamWork]);

  useEffect(() => {
    if (hasPendingToolCalls) setIsStreaming(true);
  }, [hasPendingToolCalls]);

  /** task 13（Lumen）：SSE 流收尾（等价 nanobot 的 turn_end）——flush 残量、停转、
   * 落 isStreaming=false、清 run 生命周期、通知外层刷新历史。
   */
  const finalizeSseTurn = useCallback(
    (chatId: string, turnId: string) => {
      flushPendingStreamEvents({ closeAnswerSegment: true, turn: { turnId } });
      cancelStreamEndTimer();
      setIsStreaming(false);
      setRunStartedAt(null);
      const completedAt = Date.now();
      setMessages((prev) => {
        let finalized = prev.map((m) => (m.isStreaming ? { ...m, isStreaming: false } : m));
        finalized = pruneReasoningOnlyPlaceholders(finalized);
        finalized = stampLastAssistantCompletion(finalized, { completedAt }, turnId);
        buffer.current = null;
        activeAssistantRef.current = null;
        clearActivitySegment();
        closedAssistantStreamIdsRef.current.clear();
        return finalized;
      });
      suppressStreamUntilTurnEndRef.current = false;
      client.endRun(chatId, turnId);
      onTurnEnd?.();
    },
    [cancelStreamEndTimer, clearActivitySegment, client, flushPendingStreamEvents, onTurnEnd],
  );

  /** task 13（Lumen）：POST /v1/responses + 读 SSE。delta → 现有 PendingStreamEvent
   * 管线（appendAnswerChunk 实时追加进 assistant 气泡）；[DONE]/completed → finalize。
   */
  const streamGenerate = useCallback(
    async (chatId: string, turnId: string, content: string) => {
      const controller = new AbortController();
      activeSseAbortRef.current = controller;
      const fail = (reason: string) => {
        client.finishRunLocally(chatId);
        applyStreamError({
          kind: "turn_rejected",
          detail: "lumen_stream_error",
          reason,
          chatId,
          turnId,
        });
      };
      let res: Response;
      try {
        res = await fetch("/v1/responses", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            input: buildResponsesInput(messagesRef.current, content),
            model: "deepseek-v4-flash",
            session_id: chatId,
          }),
          signal: controller.signal,
        });
      } catch (e) {
        if ((e as Error).name === "AbortError") return;
        fail((e as Error).message);
        return;
      }
      if (!res.ok) {
        let reason = `HTTP ${res.status}`;
        try {
          const body = (await res.json()) as { error?: { message?: string } };
          if (body.error?.message) reason = body.error.message;
        } catch {
          // 保持 HTTP 状态兜底
        }
        fail(reason);
        return;
      }
      const reader = res.body?.getReader();
      if (!reader) {
        fail("响应无流");
        return;
      }
      const decoder = new TextDecoder();
      let buffer = "";
      let completed = false;
      const handleData = (payload: string): void => {
        if (payload === "[DONE]") {
          completed = true;
          return;
        }
        try {
          const event = JSON.parse(payload) as { type?: string; delta?: string };
          if (event.type === "response.completed") {
            completed = true;
            return;
          }
          if (
            event.type === "response.output_text.delta"
            && typeof event.delta === "string"
            && event.delta
          ) {
            pendingStreamEventsRef.current.push({
              kind: "delta",
              text: event.delta,
              turn: { turnId },
            });
            schedulePendingStreamFlush();
          }
        } catch {
          // 忽略无法解析的 data 行
        }
      };
      try {
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          let boundary: number;
          while ((boundary = buffer.indexOf("\n\n")) !== -1) {
            const block = buffer.slice(0, boundary);
            buffer = buffer.slice(boundary + 2);
            for (const line of block.split("\n")) {
              if (!line.startsWith("data:")) continue;
              const payload = line.slice(5).trim();
              if (!payload) continue;
              handleData(payload);
              if (completed) break;
            }
            if (completed) break;
          }
          if (completed) break;
        }
        if (!completed) {
          // 尾部残块（流未以 \n\n 结尾）
          for (const line of buffer.split("\n")) {
            if (!line.startsWith("data:")) continue;
            const payload = line.slice(5).trim();
            if (!payload) continue;
            handleData(payload);
            if (completed) break;
          }
        }
      } catch (e) {
        if ((e as Error).name === "AbortError") return;
        fail((e as Error).message);
        return;
      } finally {
        if (activeSseAbortRef.current === controller) activeSseAbortRef.current = null;
      }
      finalizeSseTurn(chatId, turnId);
    },
    [applyStreamError, client, finalizeSseTurn, schedulePendingStreamFlush],
  );

  const send = useCallback(
    (content: string, images?: SendAttachment[], options?: SendOptions) => {
      if (!chatId) return null;
      const hasAttachments = !!images && images.length > 0;
      // Text is optional when files are attached — the agent will still see
      // them via ``media`` paths.
      if (!hasAttachments && !content.trim()) return null;

      const sideChannel = options?.sideChannel === true;
      const finalizeActiveTurn = options?.finalizeActiveTurn === true;
      const continueActiveTurn = options?.continueActiveTurn === true;
      const outboundContent = options?.quotedContext
        ? formatQuotedUserMessage(content, options.quotedContext)
        : content;
      flushPendingStreamEvents();
      if (finalizeActiveTurn) {
        cancelStreamEndTimer();
        setIsStreaming(false);
      }
      const turnId = crypto.randomUUID();
      const userMessageId = crypto.randomUUID();
      if (sideChannel) sideChannelTurnIdsRef.current.add(turnId);
      const previews = hasAttachments ? images!.map((i) => i.preview) : undefined;
      setMessages((prev) => {
        if ((!sideChannel && !continueActiveTurn) || finalizeActiveTurn) {
          buffer.current = null;
          activeAssistantRef.current = null;
          closedAssistantStreamIdsRef.current.clear();
          clearActivitySegment();
          suppressStreamUntilTurnEndRef.current = false;
        } else if (continueActiveTurn) {
          // Guidance belongs to the active backend turn. Preserve the answer
          // cursor so its resuming stream_end can finalize the text already
          // shown before the new user row, while starting fresh activity after it.
          clearActivitySegment();
        }
        const base = finalizeActiveTurn ? finalizeStreamedTurn(prev) : prev;
        return [
          ...(sideChannel || continueActiveTurn ? base : pruneReasoningOnlyPlaceholders(base)),
          {
            id: userMessageId,
            role: "user",
            content: outboundContent,
            turnId,
            turnPhase: "user",
            turnSeq: 0,
            deliveryStatus: "sending",
            createdAt: Date.now(),
            ...(previews ? { media: previews } : {}),
            ...(options?.cliApps?.length ? { cliApps: options.cliApps } : {}),
            ...(options?.mcpPresets?.length ? { mcpPresets: options.mcpPresets } : {}),
            ...(options?.sessionMentions?.length
              ? { sessionMentions: options.sessionMentions }
              : {}),
          },
        ];
      });
      if (!sideChannel) setIsStreaming(true);
      // Lumen：SSE 生成。先置本地 + client 的 run 状态（ThreadShell/App 靠
      // getRunStartedAt / onRunStatus / hasUnsettledRun 追踪 running），
      // 再把乐观用户消息标为 accepted（SSE 没有单独的 accepted 帧）。
      const startedAt = Math.floor(Date.now() / 1000);
      setRunStartedAt(startedAt);
      client.beginRun(chatId, turnId, startedAt);
      setMessages((prev) => transitionTurnDelivery(prev, turnId, "accepted"));
      void streamGenerate(chatId, turnId, outboundContent);
      return { turnId, userMessageId, sideChannel };
    },
    [cancelStreamEndTimer, chatId, clearActivitySegment, client, flushPendingStreamEvents, streamGenerate],
  );

  const stop = useCallback(() => {
    if (!chatId) return;
    // 中止在飞 SSE 请求——streamGenerate 的 AbortError 分支会直接返回（不收尾）。
    activeSseAbortRef.current?.abort();
    activeSseAbortRef.current = null;
    flushPendingStreamEvents();
    setIsStreaming(false);
    setMessages((prev) => {
      buffer.current = null;
      activeAssistantRef.current = null;
      closedAssistantStreamIdsRef.current.clear();
      clearActivitySegment();
      return prev.map((m) => (m.isStreaming ? { ...m, isStreaming: false } : m));
    });
    suppressStreamUntilTurnEndRef.current = false;
    setRunStartedAt(null);
    client.finishRunLocally(chatId);
  }, [chatId, clearActivitySegment, client, flushPendingStreamEvents]);

  const reconcileTurnComplete = useCallback(() => {
    cancelStreamEndTimer();
    clearPendingStreamWork();
    buffer.current = null;
    activeAssistantRef.current = null;
    closedAssistantStreamIdsRef.current.clear();
    clearActivitySegment();
    suppressStreamUntilTurnEndRef.current = false;
    setRunStartedAt(null);
    setIsStreaming(false);
  }, [cancelStreamEndTimer, clearActivitySegment, clearPendingStreamWork]);

  const transcribeAudio = useCallback(
    (dataUrl: string, options?: { durationMs?: number }) =>
      client.transcribeAudio(dataUrl, options),
    [client],
  );

  return {
    messages,
    messagesReady: messageOwnerChatId === chatId,
    isStreaming,
    runStartedAt,
    goalState,
    send,
    transcribeAudio,
    stop,
    reconcileTurnComplete,
    setMessages,
    streamError,
    dismissStreamError,
  };
}
