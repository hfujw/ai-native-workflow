/** 环回地址判断——恢复自 nanobot 原版（删功能时误删，controller 依赖）。
 *
 * 归一化后判断：小写、去 IPv6 方括号、去尾部点；127.0.0.0/8 整段都算环回。
 * （原版只认 localhost/127.0.0.1/::1 精确串，测试比实现严——一并修掉）
 */

export function isLoopbackHost(hostname: string): boolean {
  const host = String(hostname || "")
    .toLowerCase()
    .replace(/^\[|\]$/g, "") // 去掉 IPv6 方括号 [::1] → ::1
    .replace(/\.$/, ""); // 去掉尾部点 localhost. → localhost
  if (host === "localhost" || host === "::1") return true;
  // 127.0.0.0/8 都算环回
  return /^127(?:\.\d{1,3}){3}$/.test(host);
}
