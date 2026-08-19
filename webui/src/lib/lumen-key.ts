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

/** 网页搜索服务 {name, api_key, base_url}——前端填了优先，没填 = 不联网（只走本地 KB）。
 * 现在固定 Tavily；后续扩展任意搜索服务（用户自选 provider）只需改存的 name/base_url。 */
const SEARCH_SERVICE_STORAGE = "lumen.search-service";

export interface LumenSearchService {
  name: string;
  api_key: string;
  base_url: string;
}

export const TAVILY_DEFAULT: LumenSearchService = {
  name: "Tavily",
  api_key: "",
  base_url: "https://api.tavily.com",
};

export function getLumenSearchService(): LumenSearchService | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(SEARCH_SERVICE_STORAGE);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<LumenSearchService>;
    if (!parsed || !(parsed.api_key ?? "").trim()) return null;
    return {
      name: parsed.name || "Tavily",
      api_key: parsed.api_key!.trim(),
      base_url: parsed.base_url || TAVILY_DEFAULT.base_url,
    };
  } catch {
    return null;
  }
}

export function setLumenSearchService(service: Partial<LumenSearchService>): void {
  try {
    const apiKey = (service.api_key ?? "").trim();
    if (apiKey) {
      window.localStorage.setItem(
        SEARCH_SERVICE_STORAGE,
        JSON.stringify({
          name: service.name || TAVILY_DEFAULT.name,
          api_key: apiKey,
          base_url: service.base_url || TAVILY_DEFAULT.base_url,
        }),
      );
    } else {
      window.localStorage.removeItem(SEARCH_SERVICE_STORAGE);
    }
  } catch {
    // ignore storage errors
  }
}
