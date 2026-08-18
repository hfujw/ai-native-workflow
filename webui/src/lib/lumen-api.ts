import type {
  ChatSummary,
  SessionAutomationJob,
  SessionAutomationsPayload,
  SessionDeleteResult,
  SkillSummary,
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

/** 后端落盘的 assistant 文本 = 思考流全文 + `✨ 成品已生成 [id]` 标记。
 * 实时流里思考走 reasoning 块、标记走 content——回放按标记拆分，保持一致。 */
const ARTIFACT_MARKER = "✨ 成品已生成";
const ARTIFACT_ID_PATTERN = /✨ 成品已生成\s*\[([0-9a-f]{8})\]/;

/** 回放重构：扁平 assistant 文本 → [思考块][工具卡]…[成品]。
 * 落盘文本 = 思考 + `✅ 工具结果` 行 + `✨ 成品已生成 [id]`。
 * 按 ✅ 行切开——✅ 前是思考段（→ reasoning 块），✅ 行本身 → 工具卡。
 * 与实时流（lumen.reasoning.delta / lumen.tool）同构，刷新后不会塌成一个 thought。 */
function reconstructAssistantRows(
  text: string,
  projectId: string,
  projectIdx: number,
  baseCreated: number,
): UIMessage[] {
  const markerIdx = text.indexOf(ARTIFACT_MARKER);
  const reasoningPart = markerIdx === -1 ? text : text.slice(0, markerIdx);
  const contentPart = markerIdx === -1 ? "" : text.slice(markerIdx);
  const rows: UIMessage[] = [];
  let reasoningBuf = "";
  let sub = 0;
  const nextCreatedAt = () => baseCreated + projectIdx + sub;
  const flushReasoning = () => {
    const trimmed = reasoningBuf.trim();
    if (trimmed) {
      rows.push({
        id: `hist-${projectId}-${projectIdx}-${sub++}`,
        role: "assistant",
        content: "",
        reasoning: reasoningBuf,
        createdAt: nextCreatedAt(),
      });
    }
    reasoningBuf = "";
  };
  for (const line of reasoningPart.split("\n")) {
    const trimmed = line.trim();
    if (trimmed.startsWith("✅")) {
      flushReasoning();
      rows.push({
        id: `hist-${projectId}-${projectIdx}-${sub++}`,
        role: "tool",
        kind: "trace",
        content: trimmed,
        traces: [trimmed],
        createdAt: nextCreatedAt(),
      });
    } else {
      reasoningBuf += `${line}\n`;
    }
  }
  flushReasoning();
  if (contentPart.trim()) {
    rows.push({
      id: `hist-${projectId}-${projectIdx}-${sub++}`,
      role: "assistant",
      content: contentPart,
      completedAt: nextCreatedAt(),
      createdAt: nextCreatedAt(),
    });
  }
  return rows;
}

/** 从 assistant 内容里提取成品 id（没有 → null）。 */
export function extractArtifactId(content: string): string | null {
  const match = ARTIFACT_ID_PATTERN.exec(content);
  return match ? match[1] : null;
}

/** 剥掉成品标记+链接（成品卡渲染时，raw 标记文本不再显示）。 */
export function stripArtifactMarker(content: string): string {
  const idx = content.indexOf(ARTIFACT_MARKER);
  return idx === -1 ? content : content.slice(0, idx);
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

  const baseCreated = project.created_at ? project.created_at * 1000 : Date.now();
  const messages: UIMessage[] = (project.messages ?? []).flatMap((m, idx) => {
    const role: UIMessage["role"] = m.role === "user" ? "user" : "assistant";
    const createdAt = baseCreated + idx;
    if (role === "user") {
      return [{
        id: `hist-${project.id}-${idx}`,
        role,
        content: m.text ?? "",
        createdAt,
      }];
    }
    // 回放重构：把扁平文本（思考+✅工具行+成品标记）拆成 思考块 + 工具卡 + 成品，
    // 与实时流（lumen.reasoning.delta / lumen.tool）同构——否则刷新后塌成一个 thought
    return reconstructAssistantRows(m.text ?? "", project.id, idx, baseCreated);
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

interface LumenSkill {
  name?: string;
  description?: string;
  type?: string;
  icon?: string;
  builtin?: boolean;
}

/** GET /api/skills → Lumen skill 列表（风格/工具）。 */
export async function fetchLumenSkills(): Promise<SkillSummary[]> {
  const res = await fetchWithTimeout("/api/skills", {
    credentials: "same-origin",
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(res.status, `HTTP ${res.status}`);
  const body = (await res.json()) as { skills?: LumenSkill[] };
  return (body.skills ?? []).map((skill) => ({
    name: skill.name ?? "",
    description: skill.description ?? "",
    source: skill.type === "风格" ? "style" : skill.type === "工具" ? "tool" : (skill.type ?? "skill"),
    available: true,
    deletable: skill.builtin !== true,
  }));
}

/** POST /api/skills/install——安装一个 skill（markdown 内容）。 */
export async function installLumenSkill(id: string, markdown: string): Promise<SkillSummary> {
  const res = await fetchWithTimeout("/api/skills/install", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: id.trim(), markdown }),
    credentials: "same-origin",
  });
  if (!res.ok) {
    let reason = `HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { error?: string };
      if (body.error) reason = body.error;
    } catch {
      // keep status fallback
    }
    throw new Error(reason);
  }
  return (await res.json()) as SkillSummary;
}

/** DELETE /api/skills/{id}——删除一个 skill。 */
export async function deleteLumenSkill(id: string): Promise<void> {
  const res = await fetchWithTimeout(`/api/skills/${encodeURIComponent(id)}`, {
    method: "DELETE",
    credentials: "same-origin",
  });
  if (!res.ok) throw new ApiError(res.status, `HTTP ${res.status}`);
}
