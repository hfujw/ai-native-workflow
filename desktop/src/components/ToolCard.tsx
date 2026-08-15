import { useEffect, useState } from "react";
import type { ComponentType } from "react";
import type { IconProps } from "./icons";
import type { ToolCall, ToolId } from "../lib/api";
import {
  IconChevronDown,
  IconCode,
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
  compose: IconPencil,
  render: IconCode,
  verify: IconShieldCheck,
};

/**
 * DSH 式工具卡片：头部（状态点 + 图标 + 名称 + 结果/耗时/成本 + 展开箭头），
 * 点击展开思考正文与明细；running 时自动展开，思考内容逐字"长出来"。
 */
export default function ToolCard({ call }: { call: ToolCall }) {
  const [open, setOpen] = useState(call.status === "running");
  const [shown, setShown] = useState(0);

  const isRunning = call.status === "running";

  // 状态流转：running 自动展开并从头流式；done/error 展示全文
  useEffect(() => {
    if (isRunning) {
      setOpen(true);
      setShown(0);
    } else if (call.status === "done" || call.status === "error") {
      setShown(call.thought?.length ?? 0);
    }
  }, [call.status, call.thought, isRunning]);

  // 流式打字（think 正文逐字出现，像 DSH 的 Think 卡片）
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
  const hasBody = !!thoughtVisible || !!call.detail || !!call.error;

  return (
    <div className={`tool-card ${call.status}`}>
      <button className="tc-head" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span className="tc-dot" data-state={call.status} />
        <span className="tc-icon"><Icon size={14} /></span>
        <span className="tc-label">{call.title}</span>
        <span className="tc-meta">
          {isRunning && <span className="tc-running">进行中</span>}
          {call.status === "done" && call.summary && (
            <span className="tc-summary">{call.summary}</span>
          )}
          {call.status === "done" && (call.duration != null || call.cost != null) && (
            <span className="tc-stats">
              {call.duration != null && `${call.duration.toFixed(1)}s`}
              {call.cost != null && call.cost > 0 && ` · ¥${call.cost.toFixed(4)}`}
            </span>
          )}
        </span>
        {hasBody && (
          <IconChevronDown size={13} className={`tc-chev ${open ? "open" : ""}`} />
        )}
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
