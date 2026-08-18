/** 环回地址判断——恢复自 nanobot 原版（删功能时误删，controller 依赖） */

export function isLoopbackHost(hostname: string): boolean {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1";
}
