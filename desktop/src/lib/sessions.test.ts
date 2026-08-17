import { beforeEach, describe, expect, it } from "vitest";
import { dedupeSessions, deleteSession, loadSessions, saveSession } from "./sessions";
import type { Msg } from "./api";

// node 环境没有 localStorage —— 用最小 stub
const store = new Map<string, string>();
beforeEach(() => { store.clear(); });
globalThis.localStorage = {
  getItem: (k: string) => store.get(k) ?? null,
  setItem: (k: string, v: string) => { store.set(k, v); },
  removeItem: (k: string) => { store.delete(k); },
  clear: () => store.clear(),
  key: () => null,
  length: 0,
} as unknown as Storage;

const msg = (text: string): Msg => ({ id: 1, role: "user", text });

describe("dedupeSessions", () => {
  it("按首条用户消息合并重复会话，保留 updatedAt 最新", () => {
    const a = { id: "a", title: "恐龙", updatedAt: 1, messages: [msg("恐龙")] };
    const b = { id: "b", title: "恐龙", updatedAt: 2, messages: [msg("恐龙")] };
    const merged = dedupeSessions([a, b]);
    expect(merged).toHaveLength(1);
    expect(merged[0].id).toBe("b");
  });

  it("首条消息不同则不合并", () => {
    const a = { id: "a", title: "恐龙", updatedAt: 1, messages: [msg("恐龙")] };
    const b = { id: "b", title: "黑洞", updatedAt: 2, messages: [msg("黑洞")] };
    expect(dedupeSessions([a, b])).toHaveLength(2);
  });

  it("空首条消息用 id 兜底，不误合并", () => {
    const a = { id: "a", title: "", updatedAt: 1, messages: [] };
    const b = { id: "b", title: "", updatedAt: 2, messages: [] };
    expect(dedupeSessions([a, b])).toHaveLength(2);
  });
});

describe("saveSession / deleteSession", () => {
  it("保存 → 读取 → 同 id 覆盖不重复", () => {
    const s = { id: "s1", title: "恐龙", updatedAt: 1, messages: [msg("恐龙")] };
    saveSession(s);
    expect(loadSessions()).toHaveLength(1);
    saveSession({ ...s, updatedAt: 2 });
    expect(loadSessions()).toHaveLength(1); // 覆盖不新增
    expect(loadSessions()[0].updatedAt).toBe(2);
  });

  it("deleteSession 移除指定会话", () => {
    const s = { id: "s1", title: "恐龙", updatedAt: 1, messages: [msg("恐龙")] };
    saveSession(s);
    deleteSession("s1");
    expect(loadSessions()).toHaveLength(0);
  });
});
