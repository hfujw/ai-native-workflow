import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    // 纯逻辑测试用 node；React 组件测试（components/**）用 jsdom 渲染 DOM
    environment: "node",
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: [],
    // 用 threads pool 替代默认 forks：forks 跨线程 clone jsdom 对象时，
    // 在 Node 20 的 undici 下触发 webidl.util.markAsUncloneable is not a function（CI 红）。
    pool: "threads",
  },
});
