import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    // 纯逻辑测试用 node；React 组件测试（components/**）用 jsdom 渲染 DOM
    environment: "node",
    environmentMatchGlobs: [["src/components/**", "jsdom"]],
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: [],
  },
});
