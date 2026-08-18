import type {
  ChatSummary,
  SessionAutomationJob,
  SessionAutomationsPayload,
  SessionDeleteResult,
  UIMessage,
  WebuiThreadPersistedPayload,
} from "./types";
import { ApiError } from "./api";
import { fetchWithTimeout } from "./http";

/**
 * Lumen 数据层（task 13 方案 3）——useSessions / useSessionHistory 的数据源。
 *
 * 深度后端的"会话" = 一个生成主题（projects.json 里的 project）。
 * key 约定 `lumen:{project_id}`，与 nanobot 的 `websocket:{chat_id}` 同构，
 * 这样 UI 层的 splitKey / ChatSummary.chatId 语义保持不变。
 */

const LUMEN_CHANNEL = "lumen";

export function lumenSessionKey(projectId: string): string {
  return `${LUMEN_CHANNEL}:${projectId}`;
}

export function projectIdFromKey(key: string): string {
  const idx = key.indexOf(":");
  return idx === -1 ? key : key.slice(idx + 1);
}

/** 生成一个会话/主题 id——8 位 hex，与后端 compat._find_artifact_id 的正则 `[0-9a-f]{8}` 兼容。 */
export function newLumenSessionId(): string {
  return crypto.randomUUID().replace(/-/g, "").slice(0, 8);
}

interface LumenProjectMessage {
  role?: string;
  text?: string;
  html?: string;
  file_path?: string;
}

interface LumenProjectVersion {
  iteration: number;
  html: string;
  created_at?: number;
}

interface LumenProject {
  id: string;
  topic?: string;
  created_at?: number;
  status?: string;
  html?: string;
  messages?: LumenProjectMessage[];
  versions?: LumenProjectVersion[];
}

function unixToIso(unix: number | null | undefined): string | null {
  if (typeof unix !== "number" || !Number.isFinite(unix) || unix <= 0) return null;
  return new Date(unix * 1000).toISOString();
}

function lastMessageText(project: LumenProject): string {
  const messages = project.messages ?? [];
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const text = messages[i]?.text?.trim();
    if (text) return text;
  }
  return "";
}

/** GET /api/history → 会话列表（新的在前）。 */
export async function listSessions(token: string, base: string = ""): Promise<ChatSummary[]> {
  const res = await fetchWithTimeout(`${base}/api/history`, {
    headers: { Authorization: `Bearer ${token}` },
    credentials: "same-origin",
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(res.status, `HTTP ${res.status}`);
  const body = (await res.json()) as { projects?: LumenProject[] };
  const projects = Array.isArray(body.projects) ? body.projects : [];
  return projects.map((project) => {
    const versions = project.versions ?? [];
    const latestVersionCreatedAt = versions[versions.length - 1]?.created_at;
    return {
      key: lumenSessionKey(project.id),
      channel: LUMEN_CHANNEL,
      chatId: project.id,
      createdAt: unixToIso(project.created_at),
      updatedAt: unixToIso(latestVersionCreatedAt ?? project.created_at),
      title: project.topic ?? "",
      preview: lastMessageText(project),
      runStartedAt: null,
    };
  });
}

/** GET /api/history/{project_id} → 历史回放消息（与实时流同形状，供 merge 重叠合并）。 */
export async function fetchWebuiThread(
  token: string,
  key: string,
  optionsOrBase?: {
    limit?: number;
    direction?: "latest";
    before?: string | null;
    signal?: AbortSignal;
  } | string,
  base: string = "",
): Promise<WebuiThreadPersistedPayload | null> {
  const resolvedBase = typeof optionsOrBase === "string" ? optionsOrBase : base;
  const signal = typeof optionsOrBase === "object" ? optionsOrBase?.signal : undefined;
  const projectId = projectIdFromKey(key);
  const res = await fetchWithTimeout(
    `${resolvedBase}/api/history/${encodeURIComponent(projectId)}`,
    {
      headers: { Authorization: `Bearer ${token}` },
      credentials: "same-origin",
      cache: "no-store",
      signal,
    },
  );
  if (res.status === 404) return null;
  if (!res.ok) throw new ApiError(res.status, `HTTP ${res.status}`);
  const project = (await res.json()) as LumenProject;

  const messages: UIMessage[] = (project.messages ?? []).map((m, idx) => {
    const role = m.role === "user" ? "user" : "assistant";
    return {
      id: `hist-${project.id}-${idx}`,
      role,
      content: m.text ?? "",
      createdAt: project.created_at ? project.created_at * 1000 + idx : Date.now(),
      ...(role === "assistant" ? { completedAt: (project.created_at ?? 0) * 1000 + idx } : {}),
    };
  });

  return {
    schemaVersion: 1,
    sessionKey: key,
    savedAt: unixToIso(project.created_at) ?? undefined,
    messages,
    completed_turn_ids: [],
    has_pending_tool_calls: false,
    active_turn_id: null,
  };
}

/** DELETE /api/history/{project_id} → 删除作品。 */
export async function deleteSession(
  key: string,
  optionsOrBase?: { deleteAutomations?: boolean } | string,
): Promise<SessionDeleteResult> {
  const base = typeof optionsOrBase === "string" ? optionsOrBase : "";
  const projectId = projectIdFromKey(key);
  const res = await fetchWithTimeout(
    `${base}/api/history/${encodeURIComponent(projectId)}`,
    { method: "DELETE", credentials: "same-origin" },
  );
  if (!res.ok) throw new ApiError(res.status, `HTTP ${res.status}`);
  const body = (await res.json()) as { ok?: boolean };
  return { deleted: body.ok === true, blocked_by_automations: false };
}

/** 深度后端无自动化——恒空列表，保持接口形状。 */
export async function fetchSessionAutomations(
  _token: string,
  _key: string,
  _base: string = "",
): Promise<SessionAutomationsPayload> {
  return { jobs: [] as SessionAutomationJob[] };
}
