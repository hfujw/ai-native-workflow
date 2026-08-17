import { useEffect, useRef, useState } from "react";
import type { ComponentType } from "react";
import { fetchTrace } from "../lib/api";
import type { IconProps } from "./icons";
import {
  IconChevronDown,
  IconClose,
  IconCode,
  IconPenTool,
  IconSearch,
  IconShieldCheck,
  IconSparkle,
} from "./icons";

type TraceEntry = { type: string; step: number; tool: string; thought?: string; summary?: string };

/** 教育叙事阶段：tool → 图标/标签/说明（全复用现有 SVG 图标） */
const STAGE_META: Record<string, { label: string; icon: ComponentType<IconProps>; desc: string }> = {
  search: { label: "探索发现", icon: IconSearch, desc: "查找相关资料" },
  design: { label: "构思设计", icon: IconPenTool, desc: "规划页面结构" },
  render: { label: "撰写生成", icon: IconCode, desc: "编写页面内容" },
  verify: { label: "审查优化", icon: IconShieldCheck, desc: "检查准确性" },
  judge: { label: "质量评估", icon: IconSparkle, desc: "评估表达效果" },
};

type Step = { step: number; tool: string; thought: string; summary: string };

/** 思考回放时间轴："AI 是怎么想到这些的？"——教育叙事抽屉 */
export default function TraceTimeline({
  projectId,
  onClose,
}: {
  projectId: string | null;
  onClose: () => void;
}) {
  const [entries, setEntries] = useState<TraceEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [openSteps, setOpenSteps] = useState<Set<number>>(new Set());
  const [playStep, setPlayStep] = useState<number | null>(null);
  const stepRefs = useRef<Map<number, HTMLDivElement>>(new Map());

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    setLoading(true);
    setEntries([]);
    setOpenSteps(new Set());
    setPlayStep(null);
    fetchTrace(projectId)
      .then((d) => { if (!cancelled) setEntries(d.entries as TraceEntry[]); })
      .catch(() => { if (!cancelled) setEntries([]); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [projectId]);

  // 按 step 分组 → 每步一个节点（decide 的 thought + tool 的 summary）
  const steps: Step[] = [];
  const byStep = new Map<number, TraceEntry[]>();
  for (const e of entries) {
    const arr = byStep.get(e.step) ?? [];
    arr.push(e);
    byStep.set(e.step, arr);
  }
  for (const [step, list] of [...byStep.entries()].sort((a, b) => a[0] - b[0])) {
    steps.push({
      step,
      tool: list.find((e) => e.tool)?.tool ?? "",
      thought: list.find((e) => e.thought)?.thought ?? "",
      summary: list.find((e) => e.summary)?.summary ?? "",
    });
  }

  // 自动浏览：每 2.5s 推进一步，自动滚动到当前步骤
  useEffect(() => {
    if (playStep == null || steps.length === 0) return;
    const iv = window.setInterval(() => {
      setPlayStep((cur) => {
        const next = (cur ?? 0) + 1;
        return next < steps.length ? next : null;
      });
    }, 2500);
    return () => window.clearInterval(iv);
  }, [playStep, steps.length]);

  useEffect(() => {
    if (playStep == null) return;
    const el = stepRefs.current.get(playStep);
    el?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [playStep]);

  if (!projectId) return null;
  return (
    <div className="trace-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="trace-drawer" onMouseDown={(e) => e.stopPropagation()}>
        <div className="trace-header">
          <span className="trace-title">AI 是怎么想到这些的？</span>
          <button className="trace-close" onClick={onClose} title="关闭">
            <IconClose size={15} />
          </button>
        </div>

        {loading ? (
          <div className="trace-empty">加载中…</div>
        ) : steps.length === 0 ? (
          <div className="trace-empty">暂无思考记录（该作品生成于思考记录功能之前）</div>
        ) : (
          <>
            <button
              className="trace-play"
              onClick={() => setPlayStep(playStep == null ? (steps[0]?.step ?? 0) : null)}
            >
              {playStep == null ? "▶ 自动浏览" : "⏸ 暂停"}
            </button>
            <div className="trace-steps">
              {steps.map((s) => {
                const meta = STAGE_META[s.tool] ?? STAGE_META.search;
                const Icon = meta.icon;
                const active = playStep === s.step;
                const open = openSteps.has(s.step) || active;
                return (
                  <div
                    key={s.step}
                    ref={(el) => { if (el) stepRefs.current.set(s.step, el); }}
                    className={`trace-step ${active ? "active" : ""}`}
                  >
                    <button
                      className="trace-step-head"
                      onClick={() =>
                        setOpenSteps((prev) => {
                          const n = new Set(prev);
                          if (n.has(s.step)) n.delete(s.step);
                          else n.add(s.step);
                          return n;
                        })
                      }
                    >
                      <span className="trace-step-icon"><Icon size={14} /></span>
                      <span className="trace-step-label">{meta.label}</span>
                      <span className="trace-step-summary">{s.summary || meta.desc}</span>
                      <IconChevronDown size={12} className={`trace-step-chev ${open ? "open" : ""}`} />
                    </button>
                    {open && s.thought && (
                      <div className="trace-step-thought">{s.thought}</div>
                    )}
                  </div>
                );
              })}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
