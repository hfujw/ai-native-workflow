// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import TraceTimeline from "./TraceTimeline";
import { fetchTrace } from "../lib/api";

// mock fetchTrace：不真实请求后端
vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return { ...actual, fetchTrace: vi.fn() };
});

const mockedFetchTrace = vi.mocked(fetchTrace);

const MOCK_ENTRIES = [
  { type: "decide", step: 1, tool: "search", thought: "我对恐龙灭绝有把握，先搜证据确认关键数字" },
  { type: "tool", step: 1, tool: "search", summary: "搜索结束，共找到 6 条可信素材" },
  { type: "decide", step: 2, tool: "design", thought: "用时间线 + 撞击说/火山说对比卡片呈现" },
  { type: "decide", step: 3, tool: "render", thought: "开始渲染杂志长图" },
];

beforeEach(() => {
  cleanup();
  mockedFetchTrace.mockResolvedValue({ entries: MOCK_ENTRIES, total: 4 });
});

describe("TraceTimeline 思考回放时间轴", () => {
  it("按 step 渲染阶段列表：探索发现 / 构思设计 / 撰写生成", async () => {
    render(<TraceTimeline projectId="abc" onClose={() => {}} />);

    // 等待 fetch 完成渲染
    await waitFor(() => expect(screen.getByText("探索发现")).toBeTruthy());
    expect(screen.getByText("构思设计")).toBeTruthy();
    expect(screen.getByText("撰写生成")).toBeTruthy();
    // 每个阶段一行
    expect(screen.getAllByRole("button").filter((b) => b.className.includes("trace-step-head"))).toHaveLength(3);
  });

  it("默认不展开 thought，点击步骤头后展开显示思考内容", async () => {
    render(<TraceTimeline projectId="abc" onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText("探索发现")).toBeTruthy());

    // 默认收起：thought 内容不可见
    expect(screen.queryByText("用时间线 + 撞击说/火山说对比卡片呈现")).toBeNull();

    // 点击「构思设计」步骤头 → thought 展开
    fireEvent.click(screen.getByText("构思设计"));
    expect(screen.getByText("用时间线 + 撞击说/火山说对比卡片呈现")).toBeTruthy();
  });

  it("projectId 为空时不渲染", () => {
    const { container } = render(<TraceTimeline projectId={null} onClose={() => {}} />);
    expect(container.firstChild).toBeNull();
  });
});
