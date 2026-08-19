import { useEffect, type RefObject } from "react";

import { getCurrentWindow } from "@tauri-apps/api/window";

import { isTauri } from "./http";

/** 桌面端（Tauri）无边框窗口：mousedown 显式调用 startDragging 拖窗口。
 * 用 JS API 而非 data-tauri-drag-region 属性——属性方案在打包环境可能不生效。
 * 按钮/输入框等交互元素上不启动拖拽（保持可点击）。 */
export function useWindowDrag(ref: RefObject<HTMLElement | null>): void {
  useEffect(() => {
    const el = ref.current;
    if (!el || !isTauri()) return;
    const onMouseDown = (event: MouseEvent) => {
      if (event.button !== 0) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest("button, input, select, textarea, a, [data-no-drag]")) return;
      void getCurrentWindow().startDragging();
    };
    el.addEventListener("mousedown", onMouseDown);
    return () => el.removeEventListener("mousedown", onMouseDown);
  }, [ref]);
}
