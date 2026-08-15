import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { createPortal } from "react-dom";

const GAP = 8;

/**
 * 自适应下拉菜单：
 * - 菜单用 Portal 渲染到 <body>，不受任何滚动容器裁剪
 * - 打开时按触发按钮位置 + 菜单自身尺寸计算 fixed 坐标，水平/垂直越界自动翻转
 * - 窗口缩放时重新定位，始终完整落在视口内
 *
 * 用法：
 *   const { open, toggle, close, triggerRef, portal } = useDropdown();
 *   <button ref={triggerRef} onClick={toggle}>…</button>
 *   {portal(<div className="menu">…</div>)}
 */
export function useDropdown() {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<CSSProperties>({ left: -9999, top: -9999, visibility: "hidden" });
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  const place = useCallback(() => {
    const t = triggerRef.current;
    const m = menuRef.current;
    if (!t || !m) return;
    const tr = t.getBoundingClientRect();
    const mr = m.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;

    // 水平：默认左对齐；右侧放不下则右对齐（向左展开）
    let left = Math.round(tr.left);
    if (left + mr.width > vw - GAP) left = Math.max(GAP, Math.round(tr.right - mr.width));

    // 垂直：默认向下；下方放不下则向上
    let top = Math.round(tr.bottom + GAP);
    if (top + mr.height > vh - GAP) top = Math.round(tr.top - mr.height - GAP);
    if (top < GAP) top = Math.max(GAP, Math.round(vh - mr.height - GAP));

    setPos({ left, top, visibility: "visible" });
  }, []);

  // 打开后、绘制前完成定位（隐藏初始态 → 无闪烁）
  useLayoutEffect(() => {
    if (open) place();
  }, [open, place]);

  // 菜单打开期间窗口缩放 → 重新定位
  useEffect(() => {
    if (!open) return;
    const onResize = () => place();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [open, place]);

  // 触发按钮所在容器有入场位移动画（如设置抽屉 drawerIn）时，
  // 动画结束后的坐标才是最终位置 → 重定位
  useEffect(() => {
    if (!open) return;
    const onAnimEnd = (e: AnimationEvent) => {
      const el = e.target instanceof Element ? e.target : null;
      if (!el) return;
      if (el.closest(".settings-drawer") || el.closest(".dropdown-portal")) place();
    };
    document.addEventListener("animationend", onAnimEnd);
    return () => document.removeEventListener("animationend", onAnimEnd);
  }, [open, place]);

  // 点击菜单 / 触发按钮之外 → 关闭
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const target = e.target as Node;
      if (triggerRef.current?.contains(target)) return; // 触发按钮的开关交给 onClick
      if (menuRef.current?.contains(target)) return;
      setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const portal = (menu: ReactNode) =>
    open
      ? createPortal(
          <div ref={menuRef} className="dropdown-portal" style={pos}>
            {menu}
          </div>,
          document.body
        )
      : null;

  return { open, toggle: () => setOpen((v) => !v), close: () => setOpen(false), triggerRef, portal };
}
