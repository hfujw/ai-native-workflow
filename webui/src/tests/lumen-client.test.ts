import { describe, expect, it, vi } from "vitest";

import { LumenClient } from "@/lib/lumen-client";

describe("LumenClient run lifecycle", () => {
  it("tracks a run from beginRun to endRun", () => {
    const client = new LumenClient();
    const runStatus = vi.fn();
    const unsub = client.onRunStatus(runStatus);

    client.beginRun("abc", "turn-1", 1000);
    expect(client.getRunStartedAt("abc")).toBe(1000);
    expect(client.getRunGeneration("abc")).toBe(1);
    expect(client.hasUnsettledRun("abc")).toBe(true);
    expect(runStatus).toHaveBeenCalledWith("abc", 1000);

    client.endRun("abc", "turn-1");
    expect(client.getRunStartedAt("abc")).toBeNull();
    expect(client.hasUnsettledRun("abc")).toBe(false);
    expect(runStatus).toHaveBeenLastCalledWith("abc", null);
    unsub();
  });

  it("emits a thread session update on endRun", () => {
    const client = new LumenClient();
    const onSession = vi.fn();
    client.onSessionUpdate(onSession);

    client.beginRun("abc", "turn-1", 1000);
    client.endRun("abc", "turn-1");
    expect(onSession).toHaveBeenCalledTimes(1);
    expect(onSession.mock.calls[0]?.[0]).toBe("abc");
    expect(onSession.mock.calls[0]?.[1]).toBe("thread");
  });

  it("refuses canonical reconciliation while a run is unsettled", () => {
    const client = new LumenClient();
    client.beginRun("abc", "turn-1", 1000);
    expect(client.canReconcileCanonicalCompletion("abc", 1, [])).toBe(false);
    client.endRun("abc", "turn-1");
    expect(client.canReconcileCanonicalCompletion("abc", 1, [])).toBe(true);
  });

  it("rejects stale-generation snapshots", () => {
    const client = new LumenClient();
    client.beginRun("abc", "turn-1", 1000);
    client.endRun("abc", "turn-1");
    client.beginRun("abc", "turn-2", 2000); // generation becomes 2
    // 老快照（gen=1）在 turn-2 在飞时不可采纳
    expect(client.canReconcileCanonicalCompletion("abc", 1, [])).toBe(false);
    client.endRun("abc", "turn-2");
    expect(client.canReconcileCanonicalCompletion("abc", 2, [])).toBe(true);
  });

  it("reconcileCanonicalCompletion settles a completed run", () => {
    const client = new LumenClient();
    client.beginRun("abc", "turn-1", 1000);
    client.endRun("abc", "turn-1");
    expect(client.reconcileCanonicalCompletion("abc", 1, [])).toBe(true);
    expect(client.hasUnsettledRun("abc")).toBe(false);
    expect(client.getRunStartedAt("abc")).toBeNull();
  });
});

describe("LumenClient subscriptions", () => {
  it("replays the current status on subscribe", () => {
    const client = new LumenClient();
    const onStatus = vi.fn();
    client.onStatus(onStatus);
    expect(onStatus).toHaveBeenCalledWith("open");
  });

  it("unsubscribes event handlers", () => {
    const client = new LumenClient();
    const onSession = vi.fn();
    const unsub = client.onSessionUpdate(onSession);
    unsub();
    client.emitSessionUpdate("abc", "thread");
    expect(onSession).not.toHaveBeenCalled();
  });
});

describe("LumenClient unsupported ops fail fast", () => {
  it("rejects requestMutation / fork / transcribe", async () => {
    const client = new LumenClient();
    await expect(client.requestMutation("x")).rejects.toThrow();
    await expect(client.forkChat("a", 0)).rejects.toThrow();
    await expect(client.transcribeAudio("data:")).rejects.toThrow();
  });

  it("no-ops WS-specific actions", async () => {
    const client = new LumenClient();
    client.connect();
    client.sendSystemCommand("abc", "/model default");
    client.attach("abc");
    client.setWorkspaceScope("abc", { project_path: "/x", access_mode: "full" });
    const sidebar = await client.setSidebarState({
      schema_version: 1,
      pinned_keys: [],
      archived_keys: [],
      session_order: [],
      title_overrides: {},
      project_name_overrides: {},
      tags_by_key: {},
      collapsed_groups: {},
      view: {
        density: "comfortable",
        show_previews: true,
        show_timestamps: true,
        show_archived: false,
        sort: "updated_desc",
      },
    });
    expect(sidebar.view.sort).toBe("updated_desc");
    expect(client.status).toBe("open");
  });
});
