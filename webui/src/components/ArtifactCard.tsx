import { useState } from "react";
import { ExternalLink, Eye, EyeOff } from "lucide-react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";
import { apiBase } from "@/lib/http";

/** 成品卡（task 14）：assistant 消息里带 `✨ 成品已生成 [id]` 时渲染。
 * 展开 = 应用内 iframe 预览 /works/{id}（vite 代理到 8001），也可新窗口打开。 */
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
  return (
    <div className={cn("mt-2 overflow-hidden rounded-xl border bg-muted/25", className)}>
      <div className="flex items-center justify-between gap-3 px-3 py-2">
        <span className="truncate text-sm font-medium text-foreground">
          ✨ {t("artifact.generated", { defaultValue: "成品已生成" })}
        </span>
        <div className="flex shrink-0 items-center gap-1">
          <a
            href={src}
            target="_blank"
            rel="noreferrer"
            className="inline-flex h-8 items-center gap-1.5 rounded-lg px-2 text-xs text-muted-foreground transition hover:bg-muted hover:text-foreground"
          >
            <ExternalLink className="h-3.5 w-3.5" aria-hidden />
            {t("artifact.openNewTab", { defaultValue: "新窗口" })}
          </a>
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg px-2 text-xs text-muted-foreground transition hover:bg-muted hover:text-foreground"
          >
            {open ? (
              <EyeOff className="h-3.5 w-3.5" aria-hidden />
            ) : (
              <Eye className="h-3.5 w-3.5" aria-hidden />
            )}
            {open
              ? t("artifact.collapse", { defaultValue: "收起" })
              : t("artifact.preview", { defaultValue: "预览" })}
          </button>
        </div>
      </div>
      {open ? (
        <iframe
          src={src}
          title={`artifact-${artifactId}`}
          className="h-[420px] w-full border-t bg-background"
        />
      ) : null}
    </div>
  );
}
