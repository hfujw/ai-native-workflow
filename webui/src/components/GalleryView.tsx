import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Calendar, GalleryVerticalEnd } from "lucide-react";

import type { ChatSummary } from "@/lib/types";
import { fmtDateTime } from "@/lib/format";

/** 作品画廊（task 14）：独立视图，卡片 = 标题/摘要/日期，点击进聊天。 */
export function GalleryView({
  sessions,
  loading,
  onSelect,
}: {
  sessions: ChatSummary[];
  loading: boolean;
  onSelect: (key: string) => void;
}) {
  const { t } = useTranslation();
  const sorted = useMemo(
    () => [...sessions].sort(
      (a, b) => (
        (Date.parse(b.updatedAt ?? b.createdAt ?? "") || 0)
        - (Date.parse(a.updatedAt ?? a.createdAt ?? "") || 0)
      ),
    ),
    [sessions],
  );

  return (
    <div className="h-full overflow-y-auto px-6 py-8 sm:px-10 lg:px-14">
      <header data-tauri-drag-region className="mb-6 flex items-center gap-2.5">
        <GalleryVerticalEnd className="h-5 w-5 text-muted-foreground" aria-hidden />
        <h1 className="text-lg font-semibold tracking-[-0.01em]">
          {t("gallery.title", { defaultValue: "作品画廊" })}
        </h1>
      </header>
      {loading ? (
        <p className="text-sm text-muted-foreground">
          {t("gallery.loading", { defaultValue: "加载中…" })}
        </p>
      ) : sorted.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {t("gallery.empty", {
            defaultValue: "还没有作品——去发一条消息，生成你的第一个作品。",
          })}
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {sorted.map((session) => (
            <button
              key={session.key}
              type="button"
              onClick={() => onSelect(session.key)}
              className="group flex flex-col items-start gap-2 rounded-2xl border bg-card p-4 text-left shadow-sm transition hover:border-ring/50 hover:bg-accent/40"
            >
              <span className="line-clamp-2 text-sm font-medium text-foreground">
                {session.title || session.preview || t("chat.newChat")}
              </span>
              <span className="line-clamp-2 text-[13px] text-muted-foreground">
                {session.preview || session.title}
              </span>
              <span className="inline-flex items-center gap-1 text-xs text-muted-foreground/80">
                <Calendar className="h-3 w-3" aria-hidden />
                {session.createdAt
                  ? fmtDateTime(session.createdAt)
                  : t("gallery.noDate", { defaultValue: "未知日期" })}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
