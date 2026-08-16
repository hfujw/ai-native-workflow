import { useEffect, useState } from "react";
import type { ComponentType } from "react";
import type { IconProps } from "./icons";
import type { ToolCall, ToolId } from "../lib/api";
import {
  IconCode,
  IconGrid,
  IconPencil,
  IconPenTool,
  IconSearch,
  IconShieldCheck,
  IconSparkle,
} from "./icons";

const TOOL_ICONS: Record<ToolId, ComponentType<IconProps>> = {
  think: IconSparkle,
  search: IconSearch,
  design: IconPenTool,
  brainstorm: IconGrid,
  compose: IconPencil,
  render: IconCode,
  verify: IconShieldCheck,
  judge: IconShieldCheck,
};

/** DSH 精确还原：一行 [图标(悬停变箭头)] [标题] · [摘要截断]，点击展开正文。 */
export default function ToolCard({ call }: { call: ToolCall }) {
  const [open, setOpen] = useState(call.status === "running");
  const [shown, setShown] = useState(0);

  const isRunning = call.status === "running";

  useEffect(() => {
    if (isRunning) {
      setOpen(true);
      setShown(0);
    } else if (call.status === "done" || call.status === "error") {
      setShown(call.thought?.length ?? 0);
    }
  }, [call.status, call.thought, isRunning]);

  useEffect(() => {
    if (!isRunning || !call.thought) return;
    const iv = window.setInterval(() => {
      setShown((s) => {
        if (s >= (call.thought?.length ?? 0)) {
          window.clearInterval(iv);
          return s;
        }
        return s + 3;
      });
    }, 14);
    return () => window.clearInterval(iv);
  }, [isRunning, call.thought]);

  const Icon = TOOL_ICONS[call.tool];
  const thoughtVisible = isRunning ? (call.thought ?? "").slice(0, shown) : call.thought;
  // 行内摘要：运行中已展开时清空（思考在正文，头部不重复出现两遍）
  const inline =
    open && isRunning
      ? ""
      : isRunning
        ? thoughtVisible
        : call.status === "error"
          ? call.error || call.summary || call.thought
          : call.summary || call.thought;
  const hasBody = !!thoughtVisible || !!call.detail || !!call.error;

  return (
    <div className={`tool-card ${call.status} ${open ? "open" : ""}`}>
      <button
        className="tc-head"
        onClick={() => hasBody && setOpen((v) => !v)}
        aria-expanded={open}
      >
        {/* 图标区：默认工具图标，hover 变箭头；展开后固定显示向下箭头 */}
        <span className="tc-icon-wrap">
          <span className="tc-tool-icon">
            <Icon size={14} />
          </span>
          <span className="tc-arrow" />
        </span>

        <span className="tc-label">{call.title}</span>
        <span className="tc-sep">·</span>
        <span className="tc-inline">
          {inline}
          {isRunning && <span className="tc-caret" />}
        </span>
      </button>

      {hasBody && open && (
        <div className="tc-body">
          {thoughtVisible && (
            <div className="tc-thought">
              {thoughtVisible}
              {isRunning && <span className="tc-caret" />}
            </div>
          )}
          {call.error && <div className="tc-error">{call.error}</div>}
          {call.detail && <pre className="tc-detail">{call.detail}</pre>}
        </div>
      )}
    </div>
  );
}
