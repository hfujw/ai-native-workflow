/** 预设的纯逻辑部分——applyPreset 的核心计算，与 SettingsButton 分离便于单测。 */

import type { GenParams, Skill } from "./api";

/** 预设的编排参数模板（不含 skillId——skillId 由 resolvePresetParams 从技能组合推导） */
export type PresetParams = {
  agentSteps: number;
  llmSteps: number;
  searchMax: number;
  searchEnabled: boolean;
  creativeSwarmSize: number;
};

/** 预设定义（与 SettingsButton 内部 PRESETS 同构） */
export type Preset = {
  id: string;
  name: string;
  badge?: string;
  desc: string;
  trust: "system" | "user";
  /** 推荐的 skill 组合（能力由 skill 赋予，预设只推荐） */
  skills: string[];
  /** 编排参数模板：设为默认时应用这组参数 */
  params: PresetParams;
};

/**
 * 应用预设 → 生成实际生效的 GenParams。
 * 技能组合里的第一个"风格" skill → skillId（生成风格）；工具 skill 由 LLM 自主按需用，不强制。
 */
export function resolvePresetParams(
  preset: Preset,
  allSkills: Skill[]
): GenParams {
  const style = preset.skills
    .map((name) => allSkills.find((s) => s.name === name))
    .find((s) => s && s.type === "风格");
  return { ...preset.params, skillId: style?.id ?? "" };
}
