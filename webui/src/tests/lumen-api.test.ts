import { afterEach, describe, expect, it, vi } from "vitest";

import {
  deleteSession,
  extractArtifactId,
  fetchSessionAutomations,
  fetchWebuiThread,
  listSessions,
  lumenSessionKey,
  newLumenSessionId,
  projectIdFromKey,
  stripArtifactMarker,
} from "@/lib/lumen-api";

function jsonResponse(body: unknown): Response {
  return { ok: true, status: 200, json: async () => body } as unknown as Response;
}

function notFound(): Response {
  return { ok: false, status: 404, json: async () => ({}) } as unknown as Response;
}

/** fetchWithTimeout 调用 fetch(input, init)——给 mock 标类型，让 mock.calls 元组可索引。 */
function stubFetch(
  impl: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>,
): ReturnType<typeof vi.fn> {
  return vi.fn(impl);
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("lumen session key", () => {
  it("round-trips key <-> project id", () => {
    expect(lumenSessionKey("a1b2c3d4")).toBe("lumen:a1b2c3d4");
    expect(projectIdFromKey("lumen:a1b2c3d4")).toBe("a1b2c3d4");
  });

  it("generates 8-hex session ids compatible with backend artifact regex", () => {
    const id = newLumenSessionId();
    expect(id).toMatch(/^[0-9a-f]{8}$/);
  });
});

describe("listSessions", () => {
  it("maps projects to ChatSummary rows", async () => {
    const fetchMock = stubFetch(async () => jsonResponse({
      projects: [
        {
          id: "a1b2c3d4",
          topic: "秦始皇",
          created_at: 1000,
          versions: [{ iteration: 1, html: "<html/>", created_at: 2000 }],
          messages: [
            { role: "user", text: "秦始皇是谁" },
            { role: "assistant", text: "✅ 搜索完成\n\n✨ 成品已生成 [a1b2c3d4]" },
          ],
        },
      ],
    }));
    vi.stubGlobal("fetch", fetchMock);

    const rows = await listSessions("token");
    expect(rows).toHaveLength(1);
    const row = rows[0];
    expect(row.key).toBe("lumen:a1b2c3d4");
    expect(row.channel).toBe("lumen");
    expect(row.chatId).toBe("a1b2c3d4");
    expect(row.title).toBe("秦始皇");
    expect(row.preview).toContain("成品已生成");
    expect(row.createdAt).toBe(new Date(1000 * 1000).toISOString());
    expect(row.updatedAt).toBe(new Date(2000 * 1000).toISOString());
  });

  it("handles an empty project list", async () => {
    vi.stubGlobal("fetch", stubFetch(async () => jsonResponse({ projects: [] })));
    expect(await listSessions("token")).toEqual([]);
  });
});

describe("fetchWebuiThread", () => {
  it("maps project messages to replay UIMessage rows", async () => {
    const fetchMock = stubFetch(async () => jsonResponse({
      id: "a1b2c3d4",
      topic: "秦始皇",
      created_at: 1000,
      messages: [
        { role: "user", text: "秦始皇是谁" },
        {
          role: "assistant",
          text: "✅ 搜索完成\n\n✨ 成品已生成 [a1b2c3d4]",
          html: "<html/>",
          file_path: "a1b2c3d4_秦始皇_v1.html",
        },
      ],
    }));
    vi.stubGlobal("fetch", fetchMock);

    const payload = await fetchWebuiThread("token", "lumen:a1b2c3d4");
    expect(payload).not.toBeNull();
    // 回放重构：扁平文本 → [user][工具卡][成品]（✅ 行拆成工具卡，标记起为 content）
    expect(payload!.messages).toHaveLength(3);
    expect(payload!.messages[0].role).toBe("user");
    expect(payload!.messages[0].content).toBe("秦始皇是谁");
    expect(payload!.messages[1].role).toBe("tool");
    expect(payload!.messages[1].kind).toBe("trace");
    expect(payload!.messages[1].content).toBe("✅ 搜索完成");
    expect(payload!.messages[2].role).toBe("assistant");
    expect(payload!.messages[2].content).toContain("✨ 成品已生成");
    expect(payload!.has_pending_tool_calls).toBe(false);
    expect(payload!.completed_turn_ids).toEqual([]);
    expect(String(fetchMock.mock.calls[0][0])).toBe("/api/history/a1b2c3d4");
  });

  it("returns null on 404", async () => {
    vi.stubGlobal("fetch", stubFetch(async () => notFound()));
    expect(await fetchWebuiThread("token", "lumen:none")).toBeNull();
  });
});

describe("deleteSession", () => {
  it("deletes via DELETE /api/history/:id", async () => {
    const fetchMock = stubFetch(async () => jsonResponse({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await deleteSession("lumen:a1b2c3d4");
    expect(result.deleted).toBe(true);
    expect(result.blocked_by_automations).toBe(false);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("/api/history/a1b2c3d4");
    expect((init as RequestInit).method).toBe("DELETE");
  });

  it("reports not deleted when the backend says no", async () => {
    vi.stubGlobal("fetch", stubFetch(async () => jsonResponse({ ok: false })));
    expect((await deleteSession("lumen:a1b2c3d4")).deleted).toBe(false);
  });
});

describe("fetchSessionAutomations", () => {
  it("always returns an empty job list (Lumen has no automations)", async () => {
    const payload = await fetchSessionAutomations("token", "lumen:a1b2c3d4");
    expect(payload.jobs).toEqual([]);
  });
});

describe("artifact helpers", () => {
  it("extracts the 8-hex artifact id from assistant content", () => {
    expect(extractArtifactId("✨ 成品已生成 [a1b2c3d4]\nhttp://x")).toBe("a1b2c3d4");
    expect(extractArtifactId("没有成品的普通文本")).toBeNull();
  });

  it("strips the artifact marker from displayed content", () => {
    const content = "部分总结\n\n✨ 成品已生成 [a1b2c3d4]\nhttp://x";
    expect(stripArtifactMarker(content)).toBe("部分总结\n\n");
    expect(stripArtifactMarker("没有标记")).toBe("没有标记");
  });
});
