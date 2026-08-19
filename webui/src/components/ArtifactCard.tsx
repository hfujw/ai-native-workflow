import { useEffect, useState } from "react";
import { ExternalLink, Maximize2, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";
import { apiBase, isTauri } from "@/lib/http";
import { dragStartHandler } from "@/lib/desktop";

/** 成品卡（task 14）：assistant 消息里带 `✨ 成品已生成 [id]` 时渲染。
 * "预览"= 全屏覆盖成品大图（iframe 铺满窗口），Esc / 关闭按钮退出。
 * 桌面端没有"新窗口"（浏览器新标签）概念，隐藏；网页版保留。 */
export function ArtifactCard({
  artifactId,
  className,
}: {
  artifactId: string;
  className?: string;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const src = `${apiBase()}/works/${artifactId}`;
  const desktop = isTauri();

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <div className={cn("mt-2 overflow-hidden rounded-xl border bg-muted/25", className)}>
      <div className="flex items-center justify-between gap-3 px-3 py-2">
        <span className="truncate text-sm font-medium text-foreground">
          ✨ {t("artifact.generated", { defaultValue: "成品已生成" })}
        </span>
        <div className="flex shrink-0 items-center gap-1">
          {!desktop ? (
            <a
              href={src}
              target="_blank"
              rel="noreferrer"
              className="inline-flex h-8 items-center gap-1.5 rounded-lg px-2 text-xs text-muted-foreground transition hover:bg-muted hover:text-foreground"
            >
              <ExternalLink className="h-3.5 w-3.5" aria-hidden />
              {t("artifact.openNewTab", { defaultValue: "新窗口" })}
            </a>
          ) : null}
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg px-2 text-xs text-muted-foreground transition hover:bg-muted hover:text-foreground"
          >
            <Maximize2 className="h-3.5 w-3.5" aria-hidden />
            {t("artifact.preview", { defaultValue: "预览" })}
          </button>
        </div>
      </div>
      {open ? (
        <div className="fixed inset-0 z-[200] flex flex-col bg-background">
          <div
            onMouseDown={dragStartHandler()}
            className="flex h-10 shrink-0 items-center justify-end px-3"
          >
            <button
              type="button"
              onClick={() => setOpen(false)}
              aria-label={t("common.close", { defaultValue: "关闭" })}
              className="inline-flex h-8 items-center gap-1.5 rounded-lg px-2 text-xs text-muted-foreground transition hover:bg-muted hover:text-foreground"
            >
              <X className="h-4 w-4" aria-hidden />
              {t("common.close", { defaultValue: "关闭" })}
            </button>
          </div>
          <iframe
            src={src}
            title={`artifact-${artifactId}`}
            className="h-full w-full border-0 bg-background"
          />
        </div>
      ) : null}
    </div>
  );
}
