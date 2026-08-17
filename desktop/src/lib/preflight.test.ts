import { describe, expect, it } from "vitest";
import { computeConfigHint } from "./preflight";

describe("computeConfigHint 配置预检", () => {
  it("模型 Key 未配置 → 提示去设置→模型", () => {
    const hint = computeConfigHint({
      modelKey: "",
      searchEnabled: true,
      searchServices: [{ apiKey: "sk-x" }],
    });
    expect(hint).toContain("未配置模型 API Key");
  });

  it("模型 Key 已配置 + 搜索开启但搜索无 Key → 提示只用自身知识", () => {
    const hint = computeConfigHint({
      modelKey: "sk-abc",
      searchEnabled: true,
      searchServices: [{ apiKey: "" }],
    });
    expect(hint).toContain("搜索服务未配置 Key");
  });

  it("模型 Key 已配置 + 搜索开启 + 搜索有 Key → 无提示", () => {
    const hint = computeConfigHint({
      modelKey: "sk-abc",
      searchEnabled: true,
      searchServices: [{ apiKey: "sk-t" }],
    });
    expect(hint).toBe("");
  });

  it("搜索关闭时即使搜索服务没 Key 也不提示", () => {
    const hint = computeConfigHint({
      modelKey: "sk-abc",
      searchEnabled: false,
      searchServices: [{ apiKey: "" }],
    });
    expect(hint).toBe("");
  });
});
