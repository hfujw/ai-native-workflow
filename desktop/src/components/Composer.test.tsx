// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import Composer from "./Composer";
import type { ModelItem } from "../lib/api";

afterEach(cleanup);

const MODEL: ModelItem = { id: "flash", name: "deepseek-Flash", modelId: "deepseek-v4-flash", provider: "DeepSeek", removable: false };

const renderComposer = (over: Partial<Parameters<typeof Composer>[0]> = {}) =>
  render(
    <Composer
      onSend={() => {}}
      models={[MODEL]}
      modelId="flash"
      onModelIdChange={() => {}}
      sending={false}
      {...over}
    />
  );

describe("Composer 发送按钮", () => {
  it("有模型但输入为空 → 禁用发送", () => {
    renderComposer();
    expect((screen.getByTitle("发送") as HTMLButtonElement).disabled).toBe(true);
  });

  it("输入文字后 → 可发送；sending 时发送变停止", () => {
    const onSend = vi.fn();
    renderComposer({ onSend });

    const textarea = screen.getByPlaceholderText(/给 Lumen 提供灵感/);
    fireEvent.change(textarea, { target: { value: "恐龙为什么灭绝" } });
    const send = screen.getByTitle("发送") as HTMLButtonElement;
    expect(send.disabled).toBe(false);

    fireEvent.click(send);
    expect(onSend).toHaveBeenCalledWith("恐龙为什么灭绝");
  });

  it("模型列表为空 → 发送禁用（即使有输入）", () => {
    renderComposer({ models: [] });
    const textarea = screen.getByPlaceholderText(/给 Lumen 提供灵感/);
    fireEvent.change(textarea, { target: { value: "测试" } });
    expect((screen.getByTitle("发送") as HTMLButtonElement).disabled).toBe(true);
  });

  it("sending 时发送按钮变停止按钮，点击触发 onStop", () => {
    const onStop = vi.fn();
    renderComposer({ sending: true, onStop });
    fireEvent.click(screen.getByTitle("停止生成"));
    expect(onStop).toHaveBeenCalled();
  });

  it("配置预检提示渲染在输入区上方", () => {
    renderComposer({ configHint: "未配置模型 API Key——请到 设置→模型 填写" });
    expect(screen.getByText("未配置模型 API Key——请到 设置→模型 填写")).toBeTruthy();
  });
});
