import type {
  ConnectionStatus,
  GoalStateWsPayload,
  InboundEvent,
  SidebarStatePayload,
  WorkspaceScopePayload,
} from "./types";
import type { CanonicalRunSnapshot, StreamError } from "./nanobot-client";

/**
 * LumenClient —— 深度后端的极简客户端（task 13 方案 3）。
 *
 * nanobot 的 NanobotClient 走 WS 消息协议；深度后端不走 WS，消息流走
 * `/v1/responses` SSE（见 useNanobotStream）。但 UI 层（ThreadShell / App /
 * useSidebarState）仍会直接调用一堆 `client.*` 方法（onSessionUpdate /
 * onRunStatus / canReconcileCanonicalCompletion …），所以这里提供一个
 * **接口不变**的替代实现：
 * - 事件订阅（onStatus / onSessionUpdate / onRunStatus / onError / onChat…）
 *   用本地事件发射器实现——有订阅、可退订，只是不会有 WS 帧来触发。
 * - run 生命周期由 useNanobotStream 通过 beginRun / endRun 驱动，供
 *   ThreadShell 的 canonical 对账（getRunGeneration / hasUnsettledRun /
 *   canReconcileCanonicalCompletion）读取。
 * - WS 专属动作（sendMessage / sendSystemCommand / setWorkspaceScope /
 *   newChat / forkChat / attach / transcribeAudio …）对 Lumen 无意义，安全空转。
 */

type Unsubscribe = () => void;
type SessionUpdateScope = "metadata" | "thread" | string;
type StatusHandler = (status: ConnectionStatus) => void;
type RuntimeModelHandler = (modelName: string | null, modelPreset?: string | null) => void;
type SessionUpdateHandler = (
  chatId: string,
  scope?: SessionUpdateScope,
  workspaceScope?: WorkspaceScopePayload,
) => void;
type RunStatusHandler = (chatId: string, startedAt: number | null) => void;
type ErrorHandler = (error: StreamError) => void;
type EventHandler = (ev: InboundEvent) => void;

/** ClientProvider 提供给 UI 层的 client 契约（Lumen 版）。 */
export interface LumenClientContract {
  readonly status: ConnectionStatus;
  readonly defaultChatId: string | null;
  connect(): void;
  close(): void;
  updateUrl(url: string, socketFactory?: (url: string) => WebSocket): void;
  updateMaxFrameBytes(maxFrameBytes?: number): void;
  onStatus(handler: StatusHandler): Unsubscribe;
  onRuntimeModelUpdate(handler: RuntimeModelHandler): Unsubscribe;
  onSessionUpdate(handler: SessionUpdateHandler): Unsubscribe;
  onRunStatus(handler: RunStatusHandler): Unsubscribe;
  onError(handler: ErrorHandler): Unsubscribe;
  onChat(chatId: string, handler: EventHandler): Unsubscribe;
  emitSessionUpdate(
    chatId: string,
    scope?: SessionUpdateScope,
    workspaceScope?: WorkspaceScopePayload,
  ): void;
  getRunStartedAt(chatId: string): number | null;
  finishRunLocally(chatId: string): void;
  getRunGeneration(chatId: string): number;
  hasUnsettledRun(chatId: string): boolean;
  getGoalState(chatId: string): GoalStateWsPayload | undefined;
  canReconcileCanonicalCompletion(
    chatId: string,
    expectedRunGeneration: number,
    completedTurnIds: readonly string[],
    snapshot?: CanonicalRunSnapshot,
  ): boolean;
  reconcileCanonicalCompletion(
    chatId: string,
    expectedRunGeneration: number,
    completedTurnIds: readonly string[],
    snapshot?: CanonicalRunSnapshot,
  ): boolean;
  /** 深度后端专用（新增）：一轮 SSE 生成开始/结束，供 run 生命周期 + canonical 对账。 */
  beginRun(chatId: string, turnId: string, startedAt: number): void;
  endRun(chatId: string, turnId: string): void;
  sendSystemCommand(chatId: string, command: string, timeoutMs?: number): Promise<void>;
  setWorkspaceScope(chatId: string, workspaceScope: WorkspaceScopePayload): void;
  attach(chatId: string): void;
  setSidebarState(state: SidebarStatePayload): Promise<SidebarStatePayload>;
  newChat(timeoutMs?: number, workspaceScope?: WorkspaceScopePayload | null): Promise<string>;
  newTemporaryChat(timeoutMs?: number): Promise<string>;
  discardTemporaryChat(chatId: string): void;
  forkChat(
    sourceChatId: string,
    beforeUserIndex: number,
    title?: string,
    timeoutMs?: number,
  ): Promise<string>;
  transcribeAudio(dataUrl: string, options?: { durationMs?: number }): Promise<string>;
  /** 设置页的 WS 变更走 WebUIMutationTransport——Lumen 后端不支持，明确拒绝。 */
  requestMutation<T>(
    action: string,
    payload?: Record<string, unknown>,
    timeoutMs?: number,
  ): Promise<T>;
}

export class LumenClient implements LumenClientContract {
  private status_ = "open" as ConnectionStatus;
  private readyChatId: string | null = null;
  private statusHandlers = new Set<StatusHandler>();
  private runtimeModelHandlers = new Set<RuntimeModelHandler>();
  private sessionUpdateHandlers = new Set<SessionUpdateHandler>();
  private runStatusHandlers = new Set<RunStatusHandler>();
  private errorHandlers = new Set<ErrorHandler>();
  private chatHandlersByChatId = new Map<string, Set<EventHandler>>();

  private runStartedAtByChatId = new Map<string, number>();
  private runGenerationByChatId = new Map<string, number>();
  private latestRunTurnIdByChatId = new Map<string, string>();
  private unsettledRunTurnIdsByChatId = new Map<string, Set<string>>();
  private goalStateByChatId = new Map<string, GoalStateWsPayload>();

  get status(): ConnectionStatus {
    return this.status_;
  }

  get defaultChatId(): string | null {
    return this.readyChatId;
  }

  connect(): void {
    // 无 WS 连接——保持 open 语义，UI 的刷新/对账逻辑才能走通。
  }

  close(): void {
    this.status_ = "closed";
  }

  updateUrl(_url: string, _socketFactory?: (url: string) => WebSocket): void {
    // 深度后端不走 WS，URL 无意义。
  }

  updateMaxFrameBytes(_maxFrameBytes?: number): void {
    // 无传输帧概念。
  }

  onStatus(handler: StatusHandler): Unsubscribe {
    this.statusHandlers.add(handler);
    handler(this.status_);
    return () => {
      this.statusHandlers.delete(handler);
    };
  }

  onRuntimeModelUpdate(handler: RuntimeModelHandler): Unsubscribe {
    this.runtimeModelHandlers.add(handler);
    return () => {
      this.runtimeModelHandlers.delete(handler);
    };
  }

  onSessionUpdate(handler: SessionUpdateHandler): Unsubscribe {
    this.sessionUpdateHandlers.add(handler);
    return () => {
      this.sessionUpdateHandlers.delete(handler);
    };
  }

  onRunStatus(handler: RunStatusHandler): Unsubscribe {
    this.runStatusHandlers.add(handler);
    for (const [chatId, startedAt] of this.runStartedAtByChatId) {
      handler(chatId, startedAt);
    }
    return () => {
      this.runStatusHandlers.delete(handler);
    };
  }

  onError(handler: ErrorHandler): Unsubscribe {
    this.errorHandlers.add(handler);
    return () => {
      this.errorHandlers.delete(handler);
    };
  }

  onChat(chatId: string, handler: EventHandler): Unsubscribe {
    let handlers = this.chatHandlersByChatId.get(chatId);
    if (!handlers) {
      handlers = new Set();
      this.chatHandlersByChatId.set(chatId, handlers);
    }
    handlers.add(handler);
    return () => {
      handlers?.delete(handler);
    };
  }

  emitSessionUpdate(
    chatId: string,
    scope?: SessionUpdateScope,
    workspaceScope?: WorkspaceScopePayload,
  ): void {
    for (const handler of this.sessionUpdateHandlers) {
      handler(chatId, scope, workspaceScope);
    }
  }

  getRunStartedAt(chatId: string): number | null {
    const value = this.runStartedAtByChatId.get(chatId);
    return value === undefined ? null : value;
  }

  finishRunLocally(chatId: string): void {
    this.unsettledRunTurnIdsByChatId.delete(chatId);
    this.latestRunTurnIdByChatId.delete(chatId);
    if (this.runStartedAtByChatId.delete(chatId)) {
      this.emitRunStatus(chatId, null);
    }
  }

  getRunGeneration(chatId: string): number {
    return this.runGenerationByChatId.get(chatId) ?? 0;
  }

  hasUnsettledRun(chatId: string): boolean {
    return (this.unsettledRunTurnIdsByChatId.get(chatId)?.size ?? 0) > 0;
  }

  getGoalState(chatId: string): GoalStateWsPayload | undefined {
    return this.goalStateByChatId.get(chatId);
  }

  beginRun(chatId: string, turnId: string, startedAt: number): void {
    this.runGenerationByChatId.set(chatId, this.getRunGeneration(chatId) + 1);
    this.latestRunTurnIdByChatId.set(chatId, turnId);
    const unsettled = this.unsettledRunTurnIdsByChatId.get(chatId) ?? new Set<string>();
    unsettled.add(turnId);
    this.unsettledRunTurnIdsByChatId.set(chatId, unsettled);
    this.runStartedAtByChatId.set(chatId, startedAt);
    this.emitRunStatus(chatId, startedAt);
  }

  endRun(chatId: string, turnId: string): void {
    const unsettled = this.unsettledRunTurnIdsByChatId.get(chatId);
    if (unsettled) {
      unsettled.delete(turnId);
      if (unsettled.size === 0) this.unsettledRunTurnIdsByChatId.delete(chatId);
    }
    if (this.latestRunTurnIdByChatId.get(chatId) === turnId) {
      this.latestRunTurnIdByChatId.delete(chatId);
    }
    if (this.runStartedAtByChatId.delete(chatId)) {
      this.emitRunStatus(chatId, null);
    }
    // 生成完成 → 后端已落盘 projects.json，让 UI 刷新历史（canonical 对账）。
    this.emitSessionUpdate(chatId, "thread");
  }

  /**
   * canonical 对账预检：HTTP 历史快照能否采纳。
   *
   * 采纳条件是"没有未了结的本地 run 在飞"。一轮 SSE 进行中时
   * （beginRun 已调、endRun 未调），unsettledRunTurnIds 里有当前 turn →
   * 返回 false → ThreadShell 保留实时消息；endRun 之后全部清空 → 返回 true
   * → 采纳落盘历史。语义与 NanobotClient 对齐，只是数据源换成本地 run map。
   */
  canReconcileCanonicalCompletion(
    chatId: string,
    expectedRunGeneration: number,
    completedTurnIds: readonly string[],
    snapshot?: CanonicalRunSnapshot,
  ): boolean {
    const completed = new Set(completedTurnIds.filter((turnId): turnId is string => !!turnId));
    const observed = new Set(
      snapshot?.observedTurnIds.filter((turnId) => turnId.length > 0) ?? [],
    );
    const latestTurnId = this.latestRunTurnIdByChatId.get(chatId);
    const latestRunIsRepresented = (
      typeof latestTurnId === "string"
      && (completed.has(latestTurnId) || observed.has(latestTurnId))
    );
    const unsettledTurnIds = this.unsettledRunTurnIdsByChatId.get(chatId);
    const hasUnrepresentedTurn = (
      unsettledTurnIds !== undefined
      && Array.from(unsettledTurnIds).some(
        (turnId) => !completed.has(turnId) && !observed.has(turnId),
      )
    );
    const hasUnidentifiedActiveRun = (
      this.runStartedAtByChatId.has(chatId)
      && latestTurnId === undefined
      && (snapshot === undefined || snapshot.hasPendingToolCalls)
    );
    if (hasUnrepresentedTurn || hasUnidentifiedActiveRun) return false;
    return (
      this.getRunGeneration(chatId) === expectedRunGeneration || latestRunIsRepresented
    );
  }

  reconcileCanonicalCompletion(
    chatId: string,
    expectedRunGeneration: number,
    completedTurnIds: readonly string[],
    snapshot?: CanonicalRunSnapshot,
  ): boolean {
    const can = this.canReconcileCanonicalCompletion(
      chatId,
      expectedRunGeneration,
      completedTurnIds,
      snapshot,
    );
    if (can) this.finishRunLocally(chatId);
    return can;
  }

  sendSystemCommand(_chatId: string, _command: string, _timeoutMs = 5_000): Promise<void> {
    // 深度后端没有 /model /restart 这类 WS 系统命令——安全空转。
    return Promise.resolve();
  }

  setWorkspaceScope(_chatId: string, _workspaceScope: WorkspaceScopePayload): void {
    // 深度后端无工作区概念。
  }

  attach(_chatId: string): void {
    // 无 WS 会话可附着。
  }

  setSidebarState(state: SidebarStatePayload): Promise<SidebarStatePayload> {
    // 侧边栏状态本地持久化即可（useSidebarState 自己落 localStorage）。
    return Promise.resolve(state);
  }

  async newChat(_timeoutMs = 5_000, _workspaceScope?: WorkspaceScopePayload | null): Promise<string> {
    // useSessions 已改为本地建会话；此处兜底返回随机 id 防崩溃。
    return crypto.randomUUID();
  }

  async newTemporaryChat(_timeoutMs = 5_000): Promise<string> {
    return crypto.randomUUID();
  }

  discardTemporaryChat(_chatId: string): void {
    // 无临时会话概念。
  }

  async forkChat(
    _sourceChatId: string,
    _beforeUserIndex: number,
    _title?: string,
    _timeoutMs = 5_000,
  ): Promise<string> {
    // 深度后端不支持分叉——抛错让 UI 走失败分支。
    throw new Error("fork_chat_unsupported");
  }

  async transcribeAudio(_dataUrl: string, _options?: { durationMs?: number }): Promise<string> {
    // 深度后端无语音转写。
    throw new Error("transcribe_audio_unsupported");
  }

  async requestMutation<T>(
    _action: string,
    _payload?: Record<string, unknown>,
    _timeoutMs?: number,
  ): Promise<T> {
    // 设置类 WS 变更（skill.install / provider.update …）是 nanobot 协议，
    // Lumen 后端没有对应端点——明确拒绝，让设置页走失败分支而不是挂起。
    throw new Error("lumen_mutation_unsupported");
  }

  private emitRunStatus(chatId: string, startedAt: number | null): void {
    for (const handler of this.runStatusHandlers) {
      handler(chatId, startedAt);
    }
  }
}
