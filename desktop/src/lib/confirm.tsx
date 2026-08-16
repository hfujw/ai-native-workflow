import { createRoot } from "react-dom/client";

/**
 * 全局确认弹窗（单例）：任何组件都能 `await confirmDialog("…")`，
 * 不依赖 React 树、不受组件层级约束——渲染到 <body>，用完即拆。
 * 返回 true=确认 / false=取消。
 */
export function confirmDialog(message: string, confirmLabel = "删除"): Promise<boolean> {
  return new Promise((resolve) => {
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);

    const close = (val: boolean) => {
      root.unmount();
      host.remove();
      resolve(val);
    };

    root.render(
      <div
        className="confirm-overlay"
        onMouseDown={(e) => {
          if (e.target === e.currentTarget) close(false); // 点遮罩 = 取消
        }}
      >
        <div className="confirm-box">
          <p className="confirm-msg">{message}</p>
          <div className="confirm-actions">
            <button className="btn-secondary" onClick={() => close(false)} autoFocus>
              取消
            </button>
            <button className="btn-danger" onClick={() => close(true)}>
              {confirmLabel}
            </button>
          </div>
        </div>
      </div>
    );
  });
}
