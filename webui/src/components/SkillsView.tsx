import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Trash2, Wrench } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useWindowDrag } from "@/lib/desktop";
import {
  deleteLumenSkill,
  fetchLumenSkills,
  installLumenSkill,
} from "@/lib/lumen-api";
import type { SkillSummary } from "@/lib/types";

/** 技能页（独立视图）：风格/工具 skill 列表 + 安装 + 删除。
 * 从设置里搬到侧边栏的"技能"入口。 */
export function SkillsView() {
  const { t } = useTranslation();
  const headerRef = useRef<HTMLElement>(null);
  useWindowDrag(headerRef);
  const [skills, setSkills] = useState<SkillSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [installOpen, setInstallOpen] = useState(false);
  const [installName, setInstallName] = useState("");
  const [installMd, setInstallMd] = useState("");
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    fetchLumenSkills()
      .then((next) => {
        setSkills(next);
        setError(null);
      })
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => {
    refresh();
  }, [refresh]);

  const doInstall = async () => {
    setError(null);
    try {
      await installLumenSkill(installName, installMd);
      setInstallName("");
      setInstallMd("");
      setInstallOpen(false);
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const doDelete = async (name: string) => {
    setError(null);
    try {
      await deleteLumenSkill(name);
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="h-full overflow-y-auto px-6 py-8 sm:px-10 lg:px-14">
      <header ref={headerRef} className="mb-6 flex items-center gap-2.5">
        <Wrench className="h-5 w-5 text-muted-foreground" aria-hidden />
        <h1 className="text-lg font-semibold tracking-[-0.01em]">
          {t("settings.nav.skills", { defaultValue: "技能" })}
        </h1>
      </header>

      <div className="mb-4 flex max-w-2xl items-center justify-between gap-3">
        <p className="text-[13px] text-muted-foreground">
          {t("lumen.skills.hint", {
            defaultValue: "风格 / 工具 skill——给 LLM 装什么手艺，它就有什么手艺。",
          })}
        </p>
        <Button size="sm" variant="outline" onClick={() => setInstallOpen((v) => !v)}>
          {t("lumen.skills.install", { defaultValue: "安装 skill" })}
        </Button>
      </div>

      {installOpen ? (
        <div className="mb-4 max-w-2xl space-y-3 rounded-2xl border bg-card p-4">
          <Input
            value={installName}
            onChange={(e) => setInstallName(e.target.value)}
            placeholder={t("lumen.skills.name", { defaultValue: "skill 名（如 信息图）" })}
          />
          <textarea
            value={installMd}
            onChange={(e) => setInstallMd(e.target.value)}
            placeholder={t("lumen.skills.markdown", {
              defaultValue: "skill 的 markdown 定义（frontmatter: name/type/description + 正文）",
            })}
            className="h-28 w-full rounded-lg border bg-background px-3 py-2 text-sm"
          />
          <div className="flex items-center gap-2">
            <Button size="sm" onClick={doInstall}>
              {t("lumen.skills.confirmInstall", { defaultValue: "确认安装" })}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setInstallOpen(false)}>
              {t("common.cancel", { defaultValue: "取消" })}
            </Button>
          </div>
        </div>
      ) : null}

      {error ? (
        <p className="mb-4 max-w-2xl text-sm text-destructive">{error}</p>
      ) : null}

      {loading ? (
        <p className="text-sm text-muted-foreground">{t("gallery.loading", { defaultValue: "加载中…" })}</p>
      ) : skills.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {t("lumen.skills.empty", { defaultValue: "还没有 skill。" })}
        </p>
      ) : (
        <div className="grid max-w-2xl grid-cols-1 gap-3 sm:grid-cols-2">
          {skills.map((skill) => (
            <div key={skill.name} className="flex items-start justify-between gap-3 rounded-2xl border bg-card p-4">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-foreground">{skill.name}</span>
                  <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
                    {skill.source}
                  </span>
                </div>
                <p className="mt-1 line-clamp-2 text-[13px] text-muted-foreground">
                  {skill.description || "—"}
                </p>
              </div>
              {skill.deletable ? (
                <Button
                  size="icon"
                  variant="ghost"
                  aria-label={t("lumen.skills.delete", { defaultValue: "删除" })}
                  onClick={() => doDelete(skill.name)}
                  className="shrink-0 text-muted-foreground hover:text-destructive"
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
