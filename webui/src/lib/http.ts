export const DEFAULT_HTTP_TIMEOUT_MS = 20_000;

/** 是否跑在 Tauri 桌面端。
 * 打包环境 origin 是 tauri://；tauri:dev 时 origin 是 5173，但 Tauri 注入了 __TAURI_INTERNALS__。 */
export function isTauri(): boolean {
  if (typeof window === "undefined") return false;
  const origin = window.location.origin;
  return (
    origin.startsWith("tauri://")
    || origin.startsWith("http://tauri.localhost")
    || "__TAURI_INTERNALS__" in window
  );
}

/** 桌面端打包环境（tauri:// origin）下 API 直连深度后端 8001；
 * dev（5173）走 vite proxy（相对路径），避免 CORS。 */
export function apiBase(): string {
  if (typeof window === "undefined") return "";
  const origin = window.location.origin;
  if (origin.startsWith("tauri://") || origin.startsWith("http://tauri.localhost")) {
    return "http://127.0.0.1:8001";
  }
  return "";
}

export async function fetchWithTimeout(
  input: RequestInfo | URL,
  init: RequestInit = {},
  timeoutMs: number = DEFAULT_HTTP_TIMEOUT_MS,
): Promise<Response> {
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
    return fetch(input, init);
  }

  const controller = typeof AbortController !== "undefined"
    ? new AbortController()
    : null;
  const externalSignal = init.signal;
  const abortFromExternal = () => controller?.abort();
  let timeoutId: ReturnType<typeof setTimeout> | undefined;

  if (controller && externalSignal) {
    if (externalSignal.aborted) {
      controller.abort();
    } else {
      externalSignal.addEventListener("abort", abortFromExternal, { once: true });
    }
  }

  try {
    const request = fetch(input, {
      ...init,
      signal: controller?.signal ?? externalSignal,
    });
    const timeout = new Promise<Response>((_, reject) => {
      timeoutId = setTimeout(() => {
        reject(new Error(`Request timed out after ${timeoutMs}ms`));
        controller?.abort();
      }, timeoutMs);
    });
    return await Promise.race([request, timeout]);
  } finally {
    if (timeoutId !== undefined) clearTimeout(timeoutId);
    externalSignal?.removeEventListener("abort", abortFromExternal);
  }
}
