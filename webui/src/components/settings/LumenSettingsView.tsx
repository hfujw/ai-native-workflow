import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { useWindowDrag } from "@/lib/desktop";
import {
  ArrowLeft,
  KeyRound,
  Moon,
  Sun,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { listSessions } from "@/lib/lumen-api";
import {
  getLumenKey,
  getLumenSearchService,
  setLumenKey,
  setLumenSearchService,
  TAVILY_DEFAULT,
  type LumenSearchService,
} from "@/lib/lumen-key";
const MODEL = "deepseek-v4-flash";

type Section = "overview" | "models" | "appearance";

const SECTIONS: { key: Section; label: string }[] = [
  { key: "overview", label: "概览" },
  { key: "models", label: "模型" },
  { key: "appearance", label: "外观" },
];

/** Lumen 原生设置视图（task：前端都接上后端）。
 * 不依赖 nanobot SettingsPayload——只接深度后端真实能力：
 * 概览（项目数/模型/key）、模型（前端填 DeepSeek key）、外观（主题）。
 * 技能已搬到独立 SkillsView（侧边栏"技能"入口），不在这里。 */
export function LumenSettingsView({
  theme,
  onToggleTheme,
  onBackToChat,
}: {
  theme: "light" | "dark";
  onToggleTheme: () => void;
  onBackToChat: () => void;
}) {
  const { t } = useTranslation();
  const [section, setSection] = useState<Section>("overview");
  const asideRef = useRef<HTMLElement>(null);
  useWindowDrag(asideRef);

  return (
    <div className="flex h-full min-h-0">
      <aside
        ref={asideRef}
        data-tauri-drag-region
        className="flex w-56 shrink-0 flex-col gap-1 border-r bg-sidebar p-3"
      >
        <Button
          variant="ghost"
          size="sm"
          onClick={onBackToChat}
          className="mb-2 justify-start gap-2 text-muted-foreground"
        >
          <ArrowLeft className="h-4 w-4" />
          {t("settings.backToChat", { defaultValue: "返回对话" })}
        </Button>
        {SECTIONS.map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => setSection(item.key)}
            className={cn(
              "flex items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition",
              section === item.key
                ? "bg-accent font-medium text-foreground"
                : "text-muted-foreground hover:bg-accent/40 hover:text-foreground",
            )}
          >
            {item.label}
          </button>
        ))}
      </aside>
      <main className="min-w-0 flex-1 overflow-y-auto px-8 py-8">
        <div className="max-w-2xl">
          {section === "overview" ? <OverviewSection /> : null}
          {section === "models" ? <ModelsSection /> : null}
          {section === "appearance" ? (
            <AppearanceSection theme={theme} onToggleTheme={onToggleTheme} />
          ) : null}
        </div>
      </main>
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="mb-5 text-lg font-semibold tracking-[-0.01em]">{children}</h2>
  );
}

function Card({ label, value, caption }: { label: string; value: React.ReactNode; caption?: string }) {
  return (
    <div className="rounded-2xl border bg-card p-4">
      <div className="text-[13px] text-muted-foreground">{label}</div>
      <div className="mt-1 text-[15px] font-medium text-foreground">{value}</div>
      {caption ? <div className="mt-1 text-xs text-muted-foreground/80">{caption}</div> : null}
    </div>
  );
}

function OverviewSection() {
  const { t } = useTranslation();
  const [projectCount, setProjectCount] = useState<number | null>(null);
  useEffect(() => {
    let cancelled = false;
    listSessions("")
      .then((rows) => {
        if (!cancelled) setProjectCount(rows.length);
      })
      .catch(() => {
        if (!cancelled) setProjectCount(0);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  const keyConfigured = useMemo(() => getLumenKey().length > 0, []);
  return (
    <>
      <SectionTitle>{t("settings.nav.overview", { defaultValue: "概览" })}</SectionTitle>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Card
          label={t("lumen.overview.projects", { defaultValue: "已生成作品" })}
          value={projectCount === null ? "…" : String(projectCount)}
        />
        <Card label={t("lumen.overview.model", { defaultValue: "当前模型" })} value={MODEL} />
        <Card
          label={t("lumen.overview.key", { defaultValue: "API Key" })}
          value={
            keyConfigured
              ? t("lumen.key.configured", { defaultValue: "已配置" })
              : t("lumen.key.notConfigured", { defaultValue: "未配置（后端 .env 兜底）" })
          }
        />
      </div>
      <p className="mt-5 text-[13px] leading-6 text-muted-foreground">
        {t("lumen.overview.hint", {
          defaultValue: "Lumen 是给 LLM 装可插拔 skill 的 AI 原生工作台——你定风格与工具，LLM 自主编排生成交互式 HTML 页面。",
        })}
      </p>
    </>
  );
}

function ModelsSection() {
  const { t } = useTranslation();
  const [key, setKey] = useState(() => getLumenKey());
  const [searchService, setSearchService] = useState<LumenSearchService | null>(
    () => getLumenSearchService(),
  );
  const [searchProvider, setSearchProvider] = useState(
    () => getLumenSearchService()?.name ?? TAVILY_DEFAULT.name,
  );
  const [searchKey, setSearchKey] = useState(() => getLumenSearchService()?.api_key ?? "");
  const [searchBaseUrl, setSearchBaseUrl] = useState(
    () => getLumenSearchService()?.base_url ?? TAVILY_DEFAULT.base_url,
  );
  const [saved, setSaved] = useState(false);
  const save = () => {
    setLumenKey(key);
    const isCustom = searchProvider === "自定义";
    setLumenSearchService({
      name: isCustom ? "自定义" : TAVILY_DEFAULT.name,
      api_key: searchKey,
      base_url: isCustom ? searchBaseUrl : TAVILY_DEFAULT.base_url,
    });
    setSearchService(getLumenSearchService());
    setSaved(true);
    window.setTimeout(() => setSaved(false), 2000);
  };
  const clear = () => {
    setKey("");
    setLumenKey("");
    setSearchKey("");
    setSearchBaseUrl(TAVILY_DEFAULT.base_url);
    setSearchProvider(TAVILY_DEFAULT.name);
    setLumenSearchService({ ...TAVILY_DEFAULT, api_key: "" });
    setSearchService(null);
  };
  return (
    <>
      <SectionTitle>{t("settings.nav.models", { defaultValue: "模型" })}</SectionTitle>
      <div className="space-y-4">
        <div className="rounded-2xl border bg-card p-4">
          <label className="block text-sm font-medium text-foreground">
            {t("lumen.models.deepseekKey", { defaultValue: "DeepSeek API Key" })}
          </label>
          <Input
            type="password"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="sk-..."
            autoComplete="off"
            className="mt-2"
          />

          <label className="mt-5 block text-sm font-medium text-foreground">
            {t("lumen.models.searchService", { defaultValue: "网页搜索服务" })}
          </label>
          <select
            value={searchProvider}
            onChange={(e) => setSearchProvider(e.target.value)}
            className="mt-2 h-9 w-full rounded-lg border bg-background px-3 text-sm"
          >
            <option value={TAVILY_DEFAULT.name}>Tavily</option>
            <option value="自定义">{t("lumen.models.customSearch", { defaultValue: "自定义（自填地址）" })}</option>
          </select>
          {searchProvider === "自定义" ? (
            <Input
              type="text"
              value={searchBaseUrl}
              onChange={(e) => setSearchBaseUrl(e.target.value)}
              placeholder="https://api.search.example.com"
              autoComplete="off"
              className="mt-2"
            />
          ) : null}
          <Input
            type="password"
            value={searchKey}
            onChange={(e) => setSearchKey(e.target.value)}
            placeholder={searchProvider === TAVILY_DEFAULT.name ? "tvly-..." : "搜索服务 API Key"}
            autoComplete="off"
            className="mt-2"
          />

          <p className="mt-2 text-xs text-muted-foreground">
            {t("lumen.models.searchHint", {
              defaultValue: "前端填了优先（搜真实网页）；不填 = 不联网，只搜本地知识库，素材较少。",
            })}
          </p>

          <div className="mt-4 flex items-center gap-2">
            <Button size="sm" onClick={save}>
              <KeyRound className="mr-1.5 h-3.5 w-3.5" />
              {t("lumen.models.save", { defaultValue: "保存" })}
            </Button>
            {(key || searchKey) ? (
              <Button size="sm" variant="ghost" onClick={clear}>
                {t("lumen.models.clear", { defaultValue: "清除" })}
              </Button>
            ) : null}
            {saved ? (
              <span className="text-sm text-emerald-600 dark:text-emerald-400">
                {t("lumen.models.saved", { defaultValue: "已保存" })}
              </span>
            ) : null}
          </div>
        </div>
        <div className="rounded-2xl border bg-card p-4 text-sm text-muted-foreground">
          {t("lumen.models.modelInfo", {
            defaultValue: `LLM 固定 ${MODEL}；搜索服务 ${searchService ? searchService.name : "未配置（只搜本地知识库）"}。`,
          })}
        </div>
      </div>
    </>
  );
}

function AppearanceSection({
  theme,
  onToggleTheme,
}: {
  theme: "light" | "dark";
  onToggleTheme: () => void;
}) {
  const { t } = useTranslation();
  return (
    <>
      <SectionTitle>{t("settings.nav.appearance", { defaultValue: "外观" })}</SectionTitle>
      <div className="rounded-2xl border bg-card p-4">
        <label className="block text-sm font-medium text-foreground">
          {t("settings.appearance.theme", { defaultValue: "主题" })}
        </label>
        <div className="mt-3 flex gap-2">
          <Button
            variant={theme === "light" ? "default" : "outline"}
            size="sm"
            onClick={theme === "light" ? undefined : onToggleTheme}
          >
            <Sun className="mr-1.5 h-3.5 w-3.5" />
            {t("settings.appearance.light", { defaultValue: "浅色" })}
          </Button>
          <Button
            variant={theme === "dark" ? "default" : "outline"}
            size="sm"
            onClick={theme === "dark" ? undefined : onToggleTheme}
          >
            <Moon className="mr-1.5 h-3.5 w-3.5" />
            {t("settings.appearance.dark", { defaultValue: "深色" })}
          </Button>
        </div>
      </div>
    </>
  );
}
