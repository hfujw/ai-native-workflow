export const DEFAULT_HTTP_TIMEOUT_MS = 20_000;

/** 桌面端（Tauri）下 API 请求要到深度后端 8001——打包后 webview 的 origin 是
 * tauri://localhost，相对路径到不了 8001。浏览器 dev 返回空串走 vite proxy。 */
export function apiBase(): string {
  if (typeof window !== "undefined") {
    const origin = window.location.origin;
    if (origin.startsWith("tauri://") || origin.startsWith("http://tauri.localhost")) {
      return "http://127.0.0.1:8001";
    }
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
