import { LumenSettingsView } from "@/components/settings/LumenSettingsView";
import type { SettingsSectionKey } from "@/components/settings/contracts";
import type { SettingsPayload, SkillSummary } from "@/lib/types";

export type { SettingsSectionKey } from "@/components/settings/contracts";

interface SettingsViewProps {
  theme: "light" | "dark";
  initialSection?: SettingsSectionKey;
  initialSettings?: SettingsPayload | null;
  showSidebar?: boolean;
  onToggleTheme: () => void;
  onBackToChat: () => void;
  onModelNameChange: (modelName: string | null) => void;
  onSettingsChange?: (payload: SettingsPayload) => void;
  skills?: SkillSummary[];
  onSectionChange?: (section: SettingsSectionKey) => void;
  onLogout?: () => void;
  onRestart?: () => void;
  onNativeEngineRestart?: () => Promise<string>;
  isRestarting?: boolean;
  hostChromeInset?: boolean;
}

/** 设置入口（Lumen 原生版，2026-08-19）。
 * nanobot 的 SettingsPage/useSettingsController 数据层已由 LumenSettingsView 取代
 * （概览/模型/技能/外观全部接深度后端，不依赖 nanobot SettingsPayload）。 */
export function SettingsView({
  theme,
  onToggleTheme,
  onBackToChat,
}: SettingsViewProps) {
  return <LumenSettingsView theme={theme} onToggleTheme={onToggleTheme} onBackToChat={onBackToChat} />;
}
