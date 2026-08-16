/**
 * 全局轻量 toast（单例）：复制/导出/提示等需要"给个反馈"的场合。
 * 渲染到 <body>，2 秒后自动消失，多条可堆叠。
 */
export function toast(message: string, type: "success" | "info" | "error" = "success", duration = 2200): void {
  const host = document.createElement("div");
  host.className = `toast-item ${type}`;
  host.textContent = message;
  document.body.appendChild(host);
  // 下一帧再上 show，确保入场动画生效
  requestAnimationFrame(() => host.classList.add("show"));
  window.setTimeout(() => {
    host.classList.remove("show");
    window.setTimeout(() => host.remove(), 250);
  }, duration);
}
