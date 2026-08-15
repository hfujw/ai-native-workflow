import { useEffect, useState } from "react";

/**
 * localStorage 持久化 state：刷新/重启不丢。
 * 用于主题、生成参数、模型列表、预设选择等用户配置。
 */
export function usePersistentState<T>(
  key: string,
  initial: T
): [T, (v: T | ((prev: T) => T)) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key);
      if (raw != null) return JSON.parse(raw) as T;
    } catch {
      /* 损坏数据忽略，回退默认 */
    }
    return initial;
  });

  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* 存储不可用时静默 */
    }
  }, [key, value]);

  return [value, setValue];
}
