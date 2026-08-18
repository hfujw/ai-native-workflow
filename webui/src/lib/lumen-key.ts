/** DeepSeek API Key——前端填（localStorage），/v1/responses 请求带 Authorization。
 * 会话级 key 优先于后端 .env 兜底（compat.py 收到 Bearer 就 bind 会话客户端）。 */

const KEY_STORAGE = "lumen.deepseek-key";

export function getLumenKey(): string {
  if (typeof window === "undefined") return "";
  try {
    return window.localStorage.getItem(KEY_STORAGE)?.trim() ?? "";
  } catch {
    return "";
  }
}

export function setLumenKey(key: string): void {
  try {
    const trimmed = key.trim();
    if (trimmed) {
      window.localStorage.setItem(KEY_STORAGE, trimmed);
    } else {
      window.localStorage.removeItem(KEY_STORAGE);
    }
  } catch {
    // ignore storage errors
  }
}

export function hasLumenKey(): boolean {
  return getLumenKey().length > 0;
}
