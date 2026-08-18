import type { Msg } from "./api";

/** 存档会话（"新对话"把当前对话存档在这里，可找回） */
export type SavedSession = {
  id: string;
  title: string;
  updatedAt: number;
  messages: Msg[];
};

const KEY = "lumen.savedSessions";
const MAX_SESSIONS = 10;

function safeParse(raw: string | null): SavedSession[] {
  if (!raw) return [];
  try {
    const data = JSON.parse(raw);
    return Array.isArray(data) ? data : [];
  } catch {
    return [];
  }
}

export function loadSessions(): SavedSession[] {
  try {
    return safeParse(localStorage.getItem(KEY));
  } catch {
    return [];
  }
}

/** 存档或更新一个会话（按 updatedAt 排序，最多保留 10 个） */
export function saveSession(session: SavedSession): SavedSession[] {
  const sessions = loadSessions().filter((s) => s.id !== session.id);
  sessions.unshift(session);
  const trimmed = sessions.slice(0, MAX_SESSIONS);
  try {
    localStorage.setItem(KEY, JSON.stringify(trimmed));
  } catch {
    /* 溢出/不可用时静默——存档丢失不影响运行 */
  }
  return trimmed;
}

export function deleteSession(id: string): SavedSession[] {
  const sessions = loadSessions().filter((s) => s.id !== id);
  try {
    localStorage.setItem(KEY, JSON.stringify(sessions));
  } catch {
    /* 静默 */
  }
  return sessions;
}

/** 会话去重——按 id 去重（同一 id 保留最新），绝不按首条消息合并。
 *  两个不同对话即使首条消息相同（同名主题），也是不同对话，不能合并。 */
export function dedupeSessions(sessions: SavedSession[]): SavedSession[] {
  const byId = new Map<string, SavedSession>();
  for (const s of sessions) {
    const existing = byId.get(s.id);
    if (!existing || s.updatedAt > existing.updatedAt) {
      byId.set(s.id, s);
    }
  }
  return [...byId.values()].sort((a, b) => b.updatedAt - a.updatedAt);
}
