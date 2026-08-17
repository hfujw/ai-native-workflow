import { describe, expect, it } from "vitest";
import { resolvePresetParams, type Preset } from "./presets";
import type { Skill } from "./api";

const ALL_SKILLS: Skill[] = [
  { id: "magazine", name: "杂志长图", type: "风格", icon: "icon", desc: "", prompt: "", builtin: true },
  { id: "infographic", name: "信息图", type: "风格", icon: "icon", desc: "", prompt: "", builtin: true },
  { id: "search-tool", name: "搜索", type: "工具", icon: "icon", desc: "", prompt: "", builtin: true },
];

const preset: Preset = {
  id: "storyteller",
  name: "知识探险家",
  trust: "system",
  desc: "",
  skills: ["杂志长图"],
  params: { agentSteps: 20, llmSteps: 10, searchMax: 8, searchEnabled: true, creativeSwarmSize: 3 },
};

describe("resolvePresetParams 预设切换", () => {
  it("技能组合里的第一个风格 skill → skillId，编排参数透传", () => {
    const params = resolvePresetParams(preset, ALL_SKILLS);
    expect(params.skillId).toBe("magazine");
    expect(params.agentSteps).toBe(20);
    expect(params.searchMax).toBe(8);
  });

  it("技能组合里没有风格 skill → skillId 空（LLM 自由发挥）", () => {
    const noStyle: Preset = { ...preset, skills: ["搜索"] };
    const params = resolvePresetParams(noStyle, ALL_SKILLS);
    expect(params.skillId).toBe("");
  });

  it("技能组合里第一个匹配到的风格 skill 生效（工具 skill 不顶替）", () => {
    const mixed: Preset = { ...preset, skills: ["搜索", "信息图"] };
    const params = resolvePresetParams(mixed, ALL_SKILLS);
    expect(params.skillId).toBe("infographic");
  });
});
