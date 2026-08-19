/** 客户端共享类型/工具（task：清理 nanobot-client 死 WS 类后迁出）。
 * NanobotClient（WS 客户端）已被 LumenClient 取代，只剩这些类型还被引用。 */

/** 系统命令 turn 的前缀（isSystemCommandTurnId 判断用）。 */
const SYSTEM_COMMAND_TURN_PREFIX = "webui-system:";

export function isSystemCommandTurnId(value: string | null | undefined): value is string {
  return typeof value === "string" && value.startsWith(SYSTEM_COMMAND_TURN_PREFIX);
}

/** 结构化错误（传输/协议级故障）。 */
export type StreamError =
  /** Server rejected the inbound frame as too large (WS close code 1009). */
  | { kind: "message_too_big"; chatId?: string; turnId?: string }
  | {
      kind: "workspace_scope_rejected";
      reason?: string;
      chatId?: string;
      turnId?: string;
    }
  | {
      kind: "turn_rejected";
      detail?: string;
      reason?: string;
      chatId: string;
      turnId: string;
    };

/** HTTP 线程对账用的 canonical 快照。 */
export interface CanonicalRunSnapshot {
  /** User turn ids present in the canonical transcript page. */
  observedTurnIds: readonly string[];
  /** Whether the server still considers the transcript tail active. */
  hasPendingToolCalls: boolean;
  /** Exact active turn when supplied by a current gateway. */
  activeTurnId?: string | null;
}
