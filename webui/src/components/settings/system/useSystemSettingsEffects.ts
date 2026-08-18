import { useCallback, useEffect } from "react";

import type { SettingsSectionKey } from "@/components/settings/contracts";
import type { SystemSettingsState } from "@/components/settings/system/useSystemSettingsState";
import { fetchAutomations, fetchNanobotFeatures } from "@/lib/api";

interface SystemSettingsEffectsOptions {
  state: SystemSettingsState;
  activeSection: SettingsSectionKey;
  getToken: () => string;
  pageVisible: boolean;
}

export function useSystemSettingsEffects({
  state,
  activeSection,
  getToken,
  pageVisible,
}: SystemSettingsEffectsOptions) {
  const {
    setAutomations,
    setAutomationsError,
    setAutomationsLoading,
    setNanobotFeatures,
    setNanobotFeaturesError,
    setNanobotFeaturesLoading,
  } = state;

  // 能力目录刷新（models 时——Skills / 市场依赖 nanobotFeatures）。
  // 删功能（2026-08-19）：channels/apps/runtime/automations 的刷新 effect 移除，
  // 只保留 nanobotFeatures（skills 生态用）。
  useEffect(() => {
    if (!pageVisible || activeSection !== "models") return;
    let cancelled = false;
    let refreshing = false;
    const refresh = async (showLoading = false): Promise<void> => {
      if (refreshing) return;
      refreshing = true;
      if (showLoading) setNanobotFeaturesLoading(true);
      try {
        const payload = await fetchNanobotFeatures(getToken());
        if (!cancelled) {
          setNanobotFeatures(payload);
          setNanobotFeaturesError(null);
        }
      } catch (err) {
        const message = (err as Error).message;
        if (!cancelled && message !== "HTTP 404") setNanobotFeaturesError(message);
      } finally {
        refreshing = false;
        if (!cancelled && showLoading) setNanobotFeaturesLoading(false);
      }
    };
    void refresh(true);
    const refreshOnFocus = () => void refresh(false);
    window.addEventListener("focus", refreshOnFocus);
    return () => {
      cancelled = true;
      window.removeEventListener("focus", refreshOnFocus);
    };
  }, [activeSection, getToken, pageVisible]);

  // systemActions 仍依赖（createSystemSettingsActions 的签名要求）——保留实现，无 UI 触发
  const refreshAutomations = useCallback(
    async (showLoading = false) => {
      if (showLoading) setAutomationsLoading(true);
      try {
        const payload = await fetchAutomations(getToken());
        setAutomations(payload);
        setAutomationsError(null);
      } catch (err) {
        setAutomationsError((err as Error).message);
      } finally {
        if (showLoading) setAutomationsLoading(false);
      }
    },
    [getToken],
  );

  return { refreshAutomations };
}
