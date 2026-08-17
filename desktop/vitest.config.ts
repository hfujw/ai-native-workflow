import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "node", // 纯逻辑测试，不需要 DOM
    include: ["src/**/*.test.ts"],
  },
});
