import type { SettingsPayload } from "@/lib/types";

export type SettingsSectionKey =
  | "overview"
  | "appearance"
  | "models"
  | "skills";

// 删功能（2026-08-19）：channels/automations/mcp/pairing/voice/image 等个人助理功能移除，
// PendingRestart 机制只服务于被删的 runtime/browser/image，一并移除。
export type PendingRestartSection = never;
export type PendingRestartSections = Record<PendingRestartSection, boolean>;

export type RestartAwarePayload = {
  requires_restart?: boolean;
  surface?: SettingsPayload["surface"];
  runtime_surface?: SettingsPayload["runtime_surface"];
  runtime_capabilities?: SettingsPayload["runtime_capabilities"];
};

export type ApplySettingsPayload = (
  payload: SettingsPayload,
  options?: { preserveAgentForm?: boolean },
) => void;

export type MaybeRestartHostEngine = (payload: RestartAwarePayload) => Promise<void>;
