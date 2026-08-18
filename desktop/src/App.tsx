import { useCallback, useEffect, useRef, useState } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import Composer from "./components/Composer";
import SkillPage from "./components/SkillPage";
import SettingsButton from "./components/SettingsButton";
import ToolCard from "./components/ToolCard";
import TraceTimeline from "./components/TraceTimeline";
import { useClickOutside } from "./hooks/useClickOutside";
import { useGenerate } from "./hooks/useGenerate";
import { usePersistentState } from "./hooks/usePersistentState";
import {
  deleteProject,
  deleteWorkspaceFile,
  fetchEvents,
  fetchHistory,
  fetchProject,
  pinProject,
  renameProject,
} from "./lib/api";
import type { GenParams, ModelItem, Msg, ProviderCreds, SearchService, ToolCall, ToolId } from "./lib/api";
import { computeConfigHint } from "./lib/preflight";
import { dedupeSessions, deleteSession, loadSessions, saveSession } from "./lib/sessions";
import type { SavedSession } from "./lib/sessions";
import { confirmDialog } from "./lib/confirm";
import { toast } from "./lib/toast";
import {
  IconClose,
  IconCode,
  IconCopy,
  IconDownload,
  IconGrid,
  IconHistory,
  IconMaximize,
  IconMessageCircle,
  IconMinus,
  IconMore,
  IconPanelLeft,
  IconPencil,
  IconPin,
  IconPlus,
  IconSearch,
  IconSparkle,
  IconSquare,
  IconTrash,
} from "./components/icons";
import "./App.css";
import lumenLogo from "./assets/lumen.svg";

// Tauri 窗口句柄：只在桌面壳里可用。纯浏览器（vite dev / 部署）没有 __TAURI_INTERNALS__，
// 直接 getCurrentWindow() 会读 undefined.metadata 崩溃白屏 → 惰性守卫，点击窗口按钮时才取。
const IS_TAURI = typeof window !== "undefined" && !!(window as unknown as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__;
const getTauriWindow = () => (IS_TAURI ? getCurrentWindow() : null);

type Theme = "dark" | "light" | "system";
type View = "chat" | "works" | "skill";

/** 作品页作品（接后端后从当前对话的真实产出填充） */
type Work = {
  id: string;
  /** 对应对话里的消息 id（删除作品时移除该消息） */
  msgId: number;
  /** 工作区产物文件路径（删除作品时连带删文件） */
  filePath: string;
  title: string;
  html: string;
  time: string;
  steps: number;
  tools: string[];
};

/** 后端工具名 → 卡片标题 */
const TOOL_TITLES: Record<string, string> = {
  search: "搜索",
  design: "设计",
  brainstorm: "创意发散",
  compose: "文案",
  render: "渲染",
  verify: "验证",
  judge: "质量审查",
};

/** 按 id 更新或追加工具卡片 */
function upsertCall(calls: ToolCall[], next: ToolCall): ToolCall[] {
  const idx = calls.findIndex((c) => c.id === next.id);
  if (idx < 0) return [...calls, next];
  return calls.map((c, i) => (i === idx ? { ...c, ...next } : c));
}

/** 收尾所有仍 running 的卡片——judge 内联审查 / refine 迭代都没有 tool_result，
 *  全靠这里兜底，否则卡片"进行中"+ 光标永远闪下去。停止 / 失败 / 完成时同样清残留。 */
function settleRunningCards(ms: Msg[], summary?: string): Msg[] {
  return ms.map((m) =>
    (m.calls ?? []).some((c) => c.status === "running")
      ? {
          ...m,
          calls: (m.calls ?? []).map((c) =>
            c.status === "running"
              ? { ...c, status: "done" as const, summary: summary ?? c.summary }
              : c
          ),
        }
      : m
  );
}

/** 默认模型（首次启动；不可移除——保证输入框永远有模型可选）
 *  官方现行命名（2026）：deepseek-v4-flash / deepseek-v4-pro */
const DEFAULT_MODELS: ModelItem[] = [
  { id: "flash", name: "deepseek-Flash", modelId: "deepseek-v4-flash", provider: "DeepSeek", removable: false },
  { id: "pro", name: "deepseek-Pro", modelId: "deepseek-v4-pro", provider: "DeepSeek", removable: false },
];

/** 预设 id → 名称（Composer 联动显示用；设置页同名 localStorage key） */
const PRESET_NAMES: Record<string, string> = {
  storyteller: "知识探险家",
  alchemist: "数据炼金师",
  pixelist: "像素时光机",
  curator: "极简策展人",
};
/** 风格 skill id → 名称 */
const STYLE_NAMES: Record<string, string> = { magazine: "杂志长图", pixel: "像素风", infographic: "信息图" };

export default function App() {
  const [view, setView] = useState<View>("chat");
  // 对话消息持久化：刷新/重启恢复（防抖写入，见下方 useEffect）
  const [messages, setMessages] = useState<Msg[]>(() => {
    try {
      const raw = localStorage.getItem("lumen.messages");
      if (raw) return JSON.parse(raw) as Msg[];
    } catch {
      /* 损坏数据忽略 */
    }
    return [];
  });
  const [historyMenu, setHistoryMenu] = useState<string | null>(null);
  const [history, setHistory] = useState<{ id: string; topic: string }[]>([]);
  const [historySearch, setHistorySearch] = useState("");
  const [renamingItem, setRenamingItem] = useState<string | null>(null);
  const [renameText, setRenameText] = useState("");
  // 持久化：主题 / 生成参数 / 模型列表 / 侧边栏状态（刷新不丢）
  const [theme, setTheme] = usePersistentState<Theme>("lumen.theme", "dark");
  // 当前 Agent 预设（设置页写同一个 localStorage key）——Composer 上方联动显示
  const [activePreset] = usePersistentState<string>("lumen.preset", "storyteller");
  const [genParams, setGenParams] = usePersistentState<GenParams>("lumen.genParams", {
    agentSteps: 20,
    llmSteps: 10,
    searchMax: 8,
    searchEnabled: true,
    creativeSwarmSize: 3,
    skillId: "magazine",  // 默认预设（知识探险家）推荐的风格 skill
  });
  const [models, setModels] = usePersistentState<ModelItem[]>("lumen.models", DEFAULT_MODELS);
  // 选中的模型（持久化；发送时解析成后端模型 ID 随 WS 传递）
  const [composerModel, setComposerModel] = usePersistentState("lumen.composerModel", "flash");
  // 保证默认模型永远存在且带 provider：旧的持久化里删过/为空/缺 provider 都修；
  // 旧 modelId（deepseek / deepseek-Flash / deepseek-Chat / deepseek-Pro / deepseek-reasoner）
  // 迁移到官方新命名（v4-flash / v4-pro）——后端也有归一化兜底，这里保证 UI 显示正确
  useEffect(() => {
    setModels((ms) => {
      const missing = DEFAULT_MODELS.filter((d) => !ms.some((m) => m.id === d.id));
      const needProvider = ms
        .filter((m) => !m.provider && DEFAULT_MODELS.some((d) => d.id === m.id))
        .map((m) => ({ ...m, provider: "DeepSeek" }));
      const renameOld = ms
        .filter((m) => {
          const id = String(m.modelId ?? "").toLowerCase();
          return id.startsWith("deepseek") && !id.includes("v4-flash") && !id.includes("v4-pro");
        })
        .map((m) => ({
          ...m,
          modelId:
            String(m.modelId).toLowerCase().includes("pro") ||
            String(m.modelId).toLowerCase().includes("reasoner")
              ? "deepseek-v4-pro"
              : "deepseek-v4-flash",
        }));
      const fixed = [...needProvider, ...renameOld];
      if (!missing.length && !fixed.length) return ms;
      const fixedIds = new Set(fixed.map((f) => f.id));
      return [...fixed, ...ms.filter((m) => !fixedIds.has(m.id)), ...missing];
    });
  }, [setModels]);
  // ① 删除模型后 composerModel 悬空修复：选中的模型已不在列表 → 重置为第一个
  // （否则 Composer UI 显示 A，实际发送 model=undefined 走后端默认——UI 撒谎）
  useEffect(() => {
    setComposerModel((cur) => (models.some((m) => m.id === cur) ? cur : (models[0]?.id ?? "")));
  }, [models, setComposerModel]);
  const [sidebarOpen, setSidebarOpen] = usePersistentState("lumen.sidebar", true);
  // 提供方连接凭证（每个 provider 独立——选哪个模型的模型，就用哪个 provider 的 Key/地址；
  // 发送时随 WS 传给后端 → 后端绑定会话级客户端）
  const [providerCreds, setProviderCreds] = usePersistentState<Record<string, ProviderCreds>>(
    "lumen.providerCreds",
    {}
  );
  // 旧数据迁移：早期版本 apiKey/apiBase 是全局单值 → 归入 DeepSeek 提供方（只迁移一次）
  const [legacyApiKey] = usePersistentState("lumen.apiKey", "");
  const [legacyApiBase] = usePersistentState("lumen.apiBase", "");
  useEffect(() => {
    if (!legacyApiKey && !legacyApiBase) return;
    setProviderCreds((creds) => {
      const cur = creds["DeepSeek"] ?? { apiKey: "", apiBase: "" };
      const next = {
        ...creds,
        DeepSeek: {
          apiKey: cur.apiKey || legacyApiKey,
          apiBase: cur.apiBase || legacyApiBase || "https://api.deepseek.com",
        },
      };
      return next;
    });
    localStorage.removeItem("lumen.apiKey");
    localStorage.removeItem("lumen.apiBase");
  }, [legacyApiKey, legacyApiBase, setProviderCreds]);
  // 搜索服务列表（和模型选择一样：用户选服务 + 独立 Key/地址；默认内置 Tavily）
  // 单一来源在 App，随 WS 发送；未配置任何服务的 Key = 不联网（不回落 .env）
  const [searchServices, setSearchServices] = usePersistentState<SearchService[]>(
    "lumen.searchServices",
    [{ id: "tavily", name: "Tavily", apiKey: "", baseUrl: "https://api.tavily.com", removable: false }]
  );
  const [activeSearchService, setActiveSearchService] = usePersistentState("lumen.activeSearchService", "tavily");
  // 旧数据迁移：早期版本 tavilyKey 单值 → 归入 Tavily 服务（只迁移一次）
  const [legacyTavilyKey] = usePersistentState("lumen.tavilyKey", "");
  useEffect(() => {
    if (!legacyTavilyKey) return;
    setSearchServices((svcs) =>
      svcs.map((s) => (s.id === "tavily" ? { ...s, apiKey: s.apiKey || legacyTavilyKey } : s))
    );
    localStorage.removeItem("lumen.tavilyKey");
  }, [legacyTavilyKey, setSearchServices]);
  const [fullscreenHtml, setFullscreenHtml] = useState<string | null>(null);
  /** 源码视图：某条消息的成品卡切换到"看 HTML 代码流"（null=预览 iframe） */
  const [codeMsgId, setCodeMsgId] = useState<number | null>(null);
  /** 思考回放抽屉：打开某个历史作品的 trace（null=关闭） */
  const [traceProjectId, setTraceProjectId] = useState<string | null>(null);
  const codeRef = useRef<HTMLPreElement>(null);
  // 渲染流式：源码视图随 html 增长自动滚到底（看代码飞快上滑）
  useEffect(() => {
    if (codeMsgId != null && codeRef.current) {
      codeRef.current.scrollTop = codeRef.current.scrollHeight;
    }
  }, [messages, codeMsgId]);
  /** 空状态建议话题（来自后端知识库 /api/events） */
  const [starters, setStarters] = useState<string[]>([]);
  /** 后端连接状态（⑧：侧边栏状态点，定期 ping——正常桌面应用要有连接指示灯） */
  const [backendOnline, setBackendOnline] = useState(false);
  /** 历史对话（"新对话"时当前对话自动存档到这里，可找回） */
  const [sessions, setSessions] = useState<SavedSession[]>(() => {
    // 旧数据迁移：早期版本同一对话可能被拆成多份 → 启动时按首条用户消息合并
    const raw = loadSessions();
    const merged = dedupeSessions(raw);
    if (merged.length !== raw.length) {
      try {
        localStorage.setItem("lumen.savedSessions", JSON.stringify(merged));
      } catch {
        /* 静默 */
      }
    }
    return merged;
  });

  const historyRef = useRef<HTMLDivElement>(null);
  const chatRef = useRef<HTMLDivElement>(null);
  useClickOutside(historyRef, historyMenu !== null, () => setHistoryMenu(null));
  const { send, sendInstruction, stop, status: genStatus } = useGenerate();
  /** 成品可迭代状态：page_ready 后为 true，再输入走 instruction 改页面 */
  const [iterable, setIterable] = useState(false);

  /** 加载创作区历史（进入 / 生成完成后调用） */
  const loadHistory = useCallback(async () => {
    try {
      const data = await fetchHistory();
      setHistory((data.projects ?? []).map((p) => ({ id: p.id, topic: p.topic })));
    } catch {
      // 后端未启动时静默——创作区保持空态
    }
  }, []);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  // 对话消息持久化：防抖 800ms 写盘（流式生成期间不频繁写；超 4MB 静默放弃）
  useEffect(() => {
    const timer = setTimeout(() => {
      try {
        const raw = JSON.stringify(messages);
        if (raw.length > 4_000_000) return;
        localStorage.setItem("lumen.messages", raw);
      } catch {
        /* 存储不可用/溢出时静默 */
      }
    }, 800);
    return () => clearTimeout(timer);
  }, [messages]);

  // 空状态建议话题：知识库示例话题（最多 4 个）
  useEffect(() => {
    let cancelled = false;
    fetchEvents()
      .then((data) => {
        if (!cancelled) setStarters((data.events ?? []).slice(0, 4).map((e) => e.name));
      })
      .catch(() => {
        /* 后端未启动时静默 */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // ⑧ 后端连接状态：挂载 ping 一次 + 每 15s 探测（用轻量 /api/events，不拉全量历史）
  useEffect(() => {
    let cancelled = false;
    const ping = async () => {
      try {
        await fetchEvents();
        if (!cancelled) setBackendOnline(true);
      } catch {
        if (!cancelled) setBackendOnline(false);
      }
    };
    ping();
    const iv = window.setInterval(ping, 15000);
    return () => {
      cancelled = true;
      window.clearInterval(iv);
    };
  }, []);

  /** 回看历史作品：先存档当前对话（防丢），再拉取记录显示 */
  const openHistory = async (id: string) => {
    resetCurrentSession();
    currentProjectIdRef.current = id; // 标记主窗口正在回看这个作品
    stop();
    setIterable(false);
    try {
      const p = await fetchProject(id);
      const versions = p.versions ?? [];
      const last = versions[versions.length - 1];
      setMessages([
        { id: Date.now(), role: "user", text: p.topic },
        {
          id: Date.now() + 1,
          role: "assistant",
          text: `历史作品回看 · 生成于 ${new Date(p.created_at * 1000).toLocaleString()} · ${p.steps} 步 · 共 ${p.iterations} 版`,
          html: last?.html ?? "",
          finalized: true,
          file_path: p.file_path ?? "", // 恢复工作区路径——"复制路径"按钮才能显示
        },
      ]);
      setView("chat");
    } catch {
      // 拉取失败：提示
      setMessages([{ id: Date.now(), role: "assistant", text: "无法加载该作品（后端未启动？）" }]);
    }
  };

  // 桌面端体验：新消息时自动滚动到底部
  useEffect(() => {
    const el = chatRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  // ESC 关闭全屏预览
  useEffect(() => {
    if (!fullscreenHtml) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setFullscreenHtml(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [fullscreenHtml]);

  // 桌面端体验：双击标题栏空白处最大化/还原（按钮上不触发）
  const onTitlebarDoubleClick = (e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest(".tb-btn")) return;
    getTauriWindow()?.toggleMaximize();
  };

  useEffect(() => {
    const apply = () => {
      const isLight =
        theme === "light" ||
        (theme === "system" && window.matchMedia("(prefers-color-scheme: light)").matches);
      document.documentElement.setAttribute("data-theme", isLight ? "light" : "dark");
    };
    apply();
    if (theme === "system") {
      const mq = window.matchMedia("(prefers-color-scheme: light)");
      mq.addEventListener("change", apply);
      return () => mq.removeEventListener("change", apply);
    }
  }, [theme]);

  /** 当前对话的存档 id：稳定持有（ref）——同一对话多次存档只更新同一份，
   *  不再"每次存档都新建一条"（修复对话被拆散 + 点击列表顶部多出条目的问题） */
  const currentSessionIdRef = useRef<string | null>(null);
  /** 正在主窗口回看的后端作品 id——删除作品时若正是它，主窗口要回到新对话 */
  const currentProjectIdRef = useRef<string | null>(null);

  /** 存档当前对话（有内容才存；同一对话用同一 id，切换对话时重置）。
   *  ② ref 为空时先按"首条消息"找已存会话绑定——否则应用启动恢复的对话
   *  会被用新 id 再存一份（数据重复=侧边栏增殖） */
  const archiveCurrent = () => {
    if (messages.length === 0) return;
    if (!currentSessionIdRef.current) {
      // ref 为 null 只有两种情况：应用启动恢复的对话 / 极端异常。
      // 开新 id——绝不用"首条消息/消息数"匹配历史（那会导致同名增殖或覆盖）。
      // 正常路径 startNewChat/openSession 都分配了固定 id，archive 不靠猜。
      currentSessionIdRef.current = `s${Date.now()}`;
    }
    const title = messages.find((m) => m.role === "user")?.text ?? "对话";
    setSessions(
      saveSession({
        id: currentSessionIdRef.current,
        title,
        updatedAt: Date.now(),
        messages,
      })
    );
  };

  /** 切换对话：先停生成、再存档当前（防存半成品），清空 ref——下次存档开新条目 */
  const resetCurrentSession = () => {
    stop(); // ① 先停生成——否则 archive 会存"进行中"的半截 messages
    archiveCurrent();
    currentSessionIdRef.current = null;
  };

  /** 新对话：当前对话存档，另开一个空对话（立即分配新 id——永不复用旧 id，杜绝增殖） */
  const startNewChat = async () => {
    // 单连接模型：当前对话在生成时切走会停止它——先明确告知用户
    const isGeneratingNow = genStatus === "running" || genStatus === "connecting";
    if (isGeneratingNow) {
      const ok = await confirmDialog("当前对话正在生成，切换会停止它。确定切换？", "切换");
      if (!ok) return;
    }
    resetCurrentSession();
    currentProjectIdRef.current = null;
    currentSessionIdRef.current = `s${Date.now()}`; // 新对话从创建就有固定 id，archive 不再靠猜
    setIterable(false);
    setView("chat");
    setMessages([]);
    setHistorySearch("");
  };

  /** 打开历史对话：先停生成、再存档当前（防丢），然后加载目标会话。
   *  ⑥ 把当前会话 id 绑定到打开的会话——否则下次"新对话"存档会开新条目，同一对话重复两份 */
  const openSession = async (s: SavedSession) => {
    // 单连接模型：当前对话在生成时切走会停止它——先明确告知用户
    const isGeneratingNow = genStatus === "running" || genStatus === "connecting";
    if (isGeneratingNow) {
      const ok = await confirmDialog("当前对话正在生成，切换会停止它。确定切换？", "切换");
      if (!ok) return;
    }
    resetCurrentSession(); // 先停生成 + 存档当前（现在不会存半成品了）
    currentProjectIdRef.current = null;
    currentSessionIdRef.current = s.id;
    setIterable(false);
    setMessages(s.messages);
    setView("chat");
  };

  const removeSession = async (id: string) => {
    // ⑤ 删除零确认 → 加确认（历史对话删了不可恢复）
    const ok = await confirmDialog("确定删除这段历史对话？此操作不可恢复");
    if (!ok) return;
    const target = sessions.find((s) => s.id === id);
    // 连带删该会话的所有 workspace 产物文件（否则删了对话，作品文件残留无从查看）
    if (target) {
      const files = new Set(
        target.messages
          .map((m) => m.file_path)
          .filter((p): p is string => !!p)
          .map((p) => p.split(/[\\/]/).pop() ?? "")
          .filter((f) => !!f)
      );
      await Promise.allSettled([...files].map((f) => deleteWorkspaceFile(f)));
    }
    setSessions(deleteSession(id));
    // 删的是主窗口正在查看/编辑的对话（按 ref 或首条消息匹配）→ 主窗口回到空的新对话。
    // 覆盖两种情况：① openSession 绑定过 ref；② 应用启动从 lumen.messages 恢复、ref 为空但内容相同。
    // 不清 ref 的话，下一步"新对话"的 archiveCurrent() 会把它原样存档回来——删除等于没删。
    const targetFirst = target?.messages.find((m) => m.role === "user")?.text ?? "";
    const currentFirst = messages.find((m) => m.role === "user")?.text ?? "";
    const isDisplayed =
      currentSessionIdRef.current === id || (targetFirst !== "" && targetFirst === currentFirst);
    if (isDisplayed) {
      currentSessionIdRef.current = null;
      currentProjectIdRef.current = null;
      stop();
      setIterable(false);
      setView("chat");
      setMessages([]);
      setHistorySearch("");
    }
  };

  /** 清空当前对话（侧边栏"当前对话"条目的删除）——彻底删：视图 + 历史会话 + workspace 文件 */
  const clearCurrentChat = async () => {
    const ok = await confirmDialog("确定删除当前对话？此操作不可恢复");
    if (!ok) return;
    // 连带删当前对话的所有 workspace 产物文件
    const files = new Set(
      messages
        .map((m) => m.file_path)
        .filter((p): p is string => !!p)
        .map((p) => p.split(/[\\/]/).pop() ?? "")
        .filter((f) => !!f)
    );
    await Promise.allSettled([...files].map((f) => deleteWorkspaceFile(f)));
    // 连带删历史列表里对应的会话——否则"清空"只清视图，历史里还在，要再删一次
    const currentId = currentSessionIdRef.current;
    const firstUser = messages.find((m) => m.role === "user")?.text ?? "";
    const matchedId =
      currentId ??
      (firstUser
        ? sessions.find((s) => s.messages.find((m) => m.role === "user")?.text === firstUser)?.id
        : undefined);
    if (matchedId) setSessions(deleteSession(matchedId));
    stop();
    currentSessionIdRef.current = null;
    currentProjectIdRef.current = null;
    runningCardRef.current = null;
    setIterable(false);
    setView("chat");
    setMessages([]);
    setHistorySearch("");
  };

  // 生成/迭代消息流的卡片配对：按消息顺序配对（thinking 记当前卡片，tool_result 更新它）
  // ——不依赖后端 step 编号（迭代时 step 都是 0，会互相覆盖）
  const targetIdRef = useRef<number | null>(null);
  const seqRef = useRef(0);
  const runningCardRef = useRef<string | null>(null);
  /** 正在生成的会话 id（单连接模型：同一时间只能一个生成）。
   *  其他对话在生成时，当前对话发送要禁用——防止"切过去发又停掉别人的生成" */
  const generatingSessionRef = useRef<string | null>(null);

  /** 处理一条生成/迭代 WS 消息（更新 targetIdRef 指向的 assistant 消息） */
  const applyGenMsg = (msg: Record<string, unknown>) => {
    const type = String(msg.type ?? "");
    const targetId = targetIdRef.current;
    if (targetId == null) return;
    switch (type) {
      case "thinking": {
        const tool = String(msg.tool ?? "");
        const title = TOOL_TITLES[tool];
        if (!title) return; // system 类提示不建卡片
        const fullThought = String(msg.thought ?? "");
        const streamCid = runningCardRef.current;
        // 决策流式阶段建过"思考"卡 → 复用为真工具卡（换标题/工具名，thought 换完整版），一步一卡不重复
        if (streamCid) {
          setMessages((ms) =>
            ms.map((m) =>
              m.id === targetId
                ? {
                    ...m,
                      calls: (m.calls ?? []).map((c) =>
                      c.id === streamCid ? { ...c, tool: tool as ToolId, title, thought: fullThought } : c
                    ),
                  }
                : m
            )
          );
          break;
        }
        seqRef.current += 1;
        const cid = `c${seqRef.current}`;
        runningCardRef.current = cid;
        setMessages((ms) => {
          // 新步骤接管：先收尾旧 running 卡片（judge/迭代无 tool_result，防"进行中"滞留）
          const settled = settleRunningCards(ms);
          return settled.map((m) =>
            m.id === targetId
              ? {
                  ...m,
                  calls: upsertCall(m.calls ?? [], {
                    id: cid,
                    tool: tool as ToolId,
                    title,
                    status: "running",
                    thought: fullThought,
                  }),
                }
              : m
          );
        });
        break;
      }
      case "thinking_stream": {
        // 决策实时流：thought 边生成边长出来（后端从 JSON 渐进提取增量片段）
        const chunk = String(msg.chunk ?? "");
        if (!chunk) return;
        if (!runningCardRef.current) {
          seqRef.current += 1;
          const cid = `c${seqRef.current}`;
          runningCardRef.current = cid;
          setMessages((ms) => {
            const settled = settleRunningCards(ms);
            return settled.map((m) =>
              m.id === targetId
                ? {
                    ...m,
                      calls: upsertCall(m.calls ?? [], {
                      id: cid,
                      tool: "think" as ToolId,
                      title: "思考",
                      status: "running",
                      thought: chunk,
                    }),
                  }
                : m
            );
          });
        } else {
          const cid = runningCardRef.current;
          setMessages((ms) =>
            ms.map((m) =>
              m.id === targetId
                ? {
                    ...m,
                      calls: (m.calls ?? []).map((c) =>
                      c.id === cid ? { ...c, thought: (c.thought ?? "") + chunk } : c
                    ),
                  }
                : m
            )
          );
        }
        break;
      }
      case "tool_result": {
        const tool = String(msg.tool ?? "");
        const title = TOOL_TITLES[tool] ?? tool;
        const cid = runningCardRef.current ?? `c${++seqRef.current}`;
        runningCardRef.current = null;
        setMessages((ms) => {
          // 先清掉所有残留 running（同消息一次只该有一张），再标记本次结果
          const settled = settleRunningCards(ms);
          return settled.map((m) =>
            m.id === targetId
              ? {
                  ...m,
                  calls: upsertCall(m.calls ?? [], {
                    id: cid,
                    tool: (TOOL_TITLES[tool] ? tool : "think") as ToolId,
                    title,
                    status: "done",
                    summary: String(msg.summary ?? ""),
                    detail: String(msg.detail ?? ""),
                  }),
                }
              : m
          );
        });
        break;
      }
      case "html_chunk": {
        // 流式渲染：HTML 作为普通文本流显示（像聊天消息长出来，不是代码窗口）
        // 生成物（iframe 预览）等 verify 通过（page_ready）后才出现
        const chunkHtml = String(msg.html ?? "");
        setMessages((ms) =>
          ms.map((m) => {
            if (m.id !== targetId) return m;
            // 只更新 html（供后续预览用）；text 里放个轻提示，不显示代码框
            return { ...m, html: chunkHtml, text: chunkHtml ? "正在生成页面…" : m.text };
          })
        );
        break;
      }
      case "page_ready": {
        setMessages((ms) =>
          settleRunningCards(ms).map((m) =>
            m.id === targetId
              ? {
                  ...m,
                  html: String(msg.page_html ?? ""),
                  text: "生成完成。",
                  file_path: String(msg.file_path ?? m.file_path ?? ""),
                  finalized: true, // 生成完成：主预览 iframe 此刻才渲染
                }
              : m
          )
        );
        setIterable(true); // 进入可迭代状态：下次输入走 instruction 改页面
        generatingSessionRef.current = null; // 生成完成，解锁其他对话发送
        // verify 通过 → 切回预览（展示验证过的成品），不再显示源码
        setCodeMsgId((cur) => (cur === targetId ? null : cur));
        // 当前对话生成完 → 绑定 session_id 到 currentProjectIdRef，
        // 让"思考过程"按钮显示（trace 按 session_id 命名，回放 AI 怎么想到这些的）
        const newProjectId = String(msg.session_id ?? "");
        if (newProjectId) currentProjectIdRef.current = newProjectId;
        loadHistory(); // 新作品入库 → 刷新创作区
        break;
      }
      case "generation_failed": {
        setMessages((ms) =>
          settleRunningCards(ms).map((m) =>
            m.id === targetId
              ? { ...m, text: `生成失败：${String(msg.reason ?? "未知原因")}` }
              : m
          )
        );
        setIterable(false);
        generatingSessionRef.current = null; // 生成失败，解锁其他对话发送
        break;
      }
    }
  };

  /** 新开一次生成（或迭代连接断开时的回退） */
  const startGeneration = (text: string) => {
    setIterable(false);
    // 记录这个生成属于哪个会话（单连接：生成期间其他会话发送要禁用）
    generatingSessionRef.current = currentSessionIdRef.current;
    const userMsgId = Date.now();
    const assistId = Date.now() + 1;
    targetIdRef.current = assistId;
    runningCardRef.current = null; // 上一轮生成残留的流式卡引用清掉，避免串到本轮
    setMessages((ms) => [
      ...ms,
      { id: userMsgId, role: "user", text },
      { id: assistId, role: "assistant", text: "", calls: [] },
    ]);
    setView("chat");

    const currentModel = models.find((m) => m.id === composerModel);
    const creds = currentModel ? providerCreds[currentModel.provider] : undefined;
    // 搜索服务：优先用户选中的；选中项没配 Key → 自动用第一个有 Key 的服务
    // （都没有 = 不联网——绝不回落任何隐藏配置）
    let searchSvc = searchServices.find((s) => s.id === activeSearchService);
    if (!searchSvc?.apiKey) {
      const picked = searchServices.find((s) => s.apiKey) ?? undefined;
      // ② 搜索服务静默回退 → 明示：用户以为用选中的服务，实际可能换了别的
      if (searchSvc && picked && picked.id !== searchSvc.id) {
        toast(`「${searchSvc.name}」未配置 Key，已自动使用「${picked.name}」联网搜索`, "info");
      }
      searchSvc = picked;
    }
    send(text, {
      params: genParams,
      model: currentModel?.modelId,
      apiKey: creds?.apiKey || undefined,
      apiBase: creds?.apiBase || undefined,
      searchService:
        searchSvc && searchSvc.apiKey
          ? { name: searchSvc.name, apiKey: searchSvc.apiKey, baseUrl: searchSvc.baseUrl }
          : undefined,
      onMessage: applyGenMsg,
      onError: (reason) => {
        const t = targetIdRef.current;
        if (t != null) setMessages((ms) => ms.map((m) => (m.id === t ? { ...m, text: reason } : m)));
        setIterable(false);
      },
    });
  };

  /** 发送：成品可迭代时走 instruction 协议改页面；否则新开生成 */
  const handleSend = (text: string) => {
    if (iterable) {
      const userMsgId = Date.now();
      const newId = Date.now() + 1;
      targetIdRef.current = newId;
      setMessages((ms) => [
        ...ms,
        { id: userMsgId, role: "user", text },
        { id: newId, role: "assistant", text: "", calls: [] },
      ]);
      const ok = sendInstruction(text);
      if (!ok) {
        // 连接已断开（后端超时等）→ 移除占位消息，回退为新生成
        setMessages((ms) => ms.filter((m) => m.id !== newId && m.id !== userMsgId));
        startGeneration(text);
      }
      return;
    }
    startGeneration(text);
  };

  /** 停止生成：关掉 WS 连接 + 清掉残留的"进行中"卡片 + 标"已停止"（stop 只关连接，不清理 UI） */
  const handleStop = () => {
    stop();
    generatingSessionRef.current = null;
    runningCardRef.current = null;
    const t = targetIdRef.current;
    setMessages((ms) => {
      const settled = settleRunningCards(ms);
      // ⑪ 停止后要有明确"已停止"状态——用户分得清是完成还是被自己打断
      return t == null
        ? settled
        : settled.map((m) => (m.id === t ? { ...m, text: m.text ? `${m.text} 已停止。` : "已停止。" } : m));
    });
  };

  const copyText = (text: string) => {
    navigator.clipboard?.writeText(text);
    toast("已复制"); // ⑩ 复制要有反馈，不然用户不知道成没成
  };

  const exportHtml = (html: string) => {
    const blob = new Blob([html], { type: "text/html" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "page.html";
    a.click();
    URL.revokeObjectURL(url);
    toast("已导出 page.html"); // ⑩ 导出同样要有反馈
  };

  /** 重命名 / 置顶 / 删除历史作品（真实调用后端） */
  const renameHistoryItem = async (id: string) => {
    const topic = renameText.trim();
    if (!topic) return;
    try {
      await renameProject(id, topic);
      setHistory((h) => h.map((x) => (x.id === id ? { ...x, topic } : x)));
    } catch {
      // 失败静默（下次刷新恢复）
    }
    setRenamingItem(null);
  };

  /** 删除作品卡：连带删工作区产物文件 + 移除对话里的该产物消息。 */
  const deleteWork = async (w: Work) => {
    const ok = await confirmDialog("确定删除这个作品？对应的工作区文件会一起删掉");
    if (!ok) return;
    const filename = w.filePath.split(/[\\/]/).pop() ?? "";
    if (filename) {
      try {
        await deleteWorkspaceFile(filename);
      } catch {
        /* 文件删除失败不阻断（历史作品可能没有落盘文件） */
      }
    }
    setMessages((ms) => ms.filter((m) => m.id !== w.msgId));
  };

  const pinHistoryItem = async (id: string) => {
    try {
      await pinProject(id);
      setHistory((h) => {
        const item = h.find((x) => x.id === id);
        return item ? [item, ...h.filter((x) => x.id !== id)] : h;
      });
    } catch {
      // 静默
    }
    setHistoryMenu(null);
  };

  const deleteHistoryItem = async (id: string) => {
    // ⑤ 删除零确认 → 加确认（作品删了不可恢复）
    const ok = await confirmDialog("确定删除这个作品？此操作不可恢复");
    if (!ok) {
      setHistoryMenu(null);
      return;
    }
    try {
      await deleteProject(id);
      setHistory((h) => h.filter((x) => x.id !== id));
      toast("作品已删除");
    } catch {
      toast("删除失败，请稍后重试", "error");
    }
    // 删的是主窗口正在回看的作品 → 主窗口回到空的新对话
    if (currentProjectIdRef.current === id) {
      currentProjectIdRef.current = null;
      currentSessionIdRef.current = null;
      stop();
      setIterable(false);
      setView("chat");
      setMessages([]);
      setHistorySearch("");
    }
    setHistoryMenu(null);
  };

  const title =
    view === "skill"
      ? "Skill"
      : messages.length === 0
        ? "新对话"
        : (messages.find((m) => m.role === "user")?.text ?? "新对话");

  const filteredHistory = history.filter((h) => h.topic.includes(historySearch.trim()));
  // ⑮ 搜索框同时过滤历史对话——否则搜索词对上面那排对话列表完全无效（误导）
  // ① 排除当前对话的内容（首条消息一致）——它已在"当前对话"条目显示，历史里不重复
  //   （用内容而非仅 id，覆盖"应用启动恢复的会话 ref 为空"的场景，修"点击就增殖"）
  const currentFirst = messages.find((m) => m.role === "user")?.text ?? "";
  const filteredSessions = sessions.filter(
    (s) =>
      s.title.includes(historySearch.trim()) &&
      (currentFirst === "" || s.messages.find((m) => m.role === "user")?.text !== currentFirst)
  );
  // ⑨ 首次引导：没有任何 provider 配置过 Key → 空状态提示去设置
  const hasAnyApiKey = Object.values(providerCreds).some((c) => c.apiKey);
  // 配置预检：发送前就提示，不等生成才报"未配置 Key"
  const selectedModel = models.find((m) => m.id === composerModel);
  const modelKey = selectedModel ? providerCreds[selectedModel.provider]?.apiKey : "";
  const configHint = computeConfigHint({
    modelKey,
    searchEnabled: genParams.searchEnabled,
    searchServices,
  });
  // 单连接模型：有其他对话正在生成时，当前对话发送要禁用（防止切过来发又停掉别人的生成）
  const isGenerating = genStatus === "running" || genStatus === "connecting";
  const otherGenerating = isGenerating && generatingSessionRef.current !== currentSessionIdRef.current;
  // 当前对话（侧边栏"当前对话"条目）：聊天时左侧创作区也能看到它，受搜索过滤
  const currentTitle = messages.find((m) => m.role === "user")?.text ?? "新对话";
  const showCurrent = messages.length > 0 && currentTitle.includes(historySearch.trim());

  // 作品页：当前对话的真实产出
  // 标题取该作品前最近一条用户消息
  const works: Work[] = messages
    .filter((m) => m.role === "assistant" && m.html)
    .map((m) => {
      const prevUser = [...messages.slice(0, messages.indexOf(m))]
        .reverse()
        .find((x) => x.role === "user");
      return {
        id: `live-${m.id}`,
        msgId: m.id,
        filePath: m.file_path ?? "",
        title: prevUser?.text?.slice(0, 30) ?? "未命名作品",
        html: m.html!,
        time: "刚刚",
        steps: m.calls?.length ?? 0,
        tools: (m.calls ?? []).map((c) => c.title).filter((t) => t !== "Think"),
      };
    });

  return (
    <div className="app">
      <aside className={`sidebar ${sidebarOpen ? "" : "collapsed"}`}>
        {/* 品牌区 + 折叠按钮（侧边栏内，名字右边；折叠后 logo 即展开按钮） */}
        <div className="sidebar-brand">
          {sidebarOpen ? (
            <>
              <div className="brand-logo" />
              <div className="brand-text">
                <div className="brand-name">Lumen</div>
                <div className="brand-sub">知识 → 体验</div>
              </div>
              <button
                className="collapse-btn"
                onClick={() => setSidebarOpen(false)}
                title="收起侧边栏"
              >
                <IconPanelLeft size={15} />
              </button>
            </>
          ) : (
            <button className="brand-logo-btn" onClick={() => setSidebarOpen(true)} title="展开侧边栏">
              <div className="brand-logo" />
            </button>
          )}
        </div>

        <button className="new-chat" onClick={startNewChat}>
          <IconPlus size={15} /> <span className="btn-label">新对话</span>
        </button>

        {/* 创作区：搜索 + 历史对话 + 作品列表 */}
        <div className="history">
          <div className="history-head">创作区</div>
          {/* 搜索框固定在顶部——同时过滤历史对话和作品 */}
          <div className="history-search">
            <IconSearch size={13} />
            <input
              value={historySearch}
              onChange={(e) => setHistorySearch(e.target.value)}
              placeholder="搜索对话 / 作品..."
            />
            {historySearch && (
              <button className="history-search-clear" onClick={() => setHistorySearch("")}>
                <IconClose size={12} />
              </button>
            )}
          </div>
          {(sessions.length > 0 || messages.length > 0) && (
            <>
              <div className="history-subhead">历史对话</div>
              {/* 当前对话：聊天时左侧也能看到，标记为"当前"，可清空 */}
              {showCurrent && (
                <div className="history-item current">
                  <IconMessageCircle size={12} className="history-item-icon" />
                  <span className="history-text current-label" title="当前对话">{currentTitle}</span>
                  <button className="history-more" onClick={clearCurrentChat} title="清空当前对话">
                    <IconTrash size={13} />
                  </button>
                </div>
              )}
              {filteredSessions.map((s) => (
                <div key={s.id} className="history-item" onMouseLeave={() => setHistoryMenu(null)}>
                  <IconHistory size={12} className="history-item-icon" />
                  <span className="history-text" onClick={() => openSession(s)}>{s.title}</span>
                  <button className="history-more" onClick={() => removeSession(s.id)} title="删除对话">
                    <IconTrash size={13} />
                  </button>
                </div>
              ))}
            </>
          )}

          <div className="history-list" ref={historyRef}>
            {filteredHistory.length === 0 ? (
              <div className="history-empty">
                {history.length === 0
                  ? sessions.length === 0
                    ? "还没有作品，开始第一个创作吧"
                    : "历史对话里还没有生成的作品"
                  : "没有匹配的作品"}
              </div>
            ) : (
              filteredHistory.map((item) => (
                <div key={item.id} className="history-item" onMouseLeave={() => setHistoryMenu(null)}>
                  {renamingItem === item.id ? (
                    <input
                      className="history-rename-input"
                      placeholder="重命名作品"
                      value={renameText}
                      onChange={(e) => setRenameText(e.target.value)}
                      autoFocus
                      onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); renameHistoryItem(item.id); } }}
                      onBlur={() => renameHistoryItem(item.id)}
                    />
                  ) : (
                    <>
                      <IconSparkle size={12} className="history-item-icon" />
                      <span className="history-text" onClick={() => openHistory(item.id)}>{item.topic}</span>
                    </>
                  )}
                  <button className="history-more" onClick={() => setHistoryMenu(historyMenu === item.id ? null : item.id)}>
                    <IconMore size={15} />
                  </button>
                  {historyMenu === item.id && (
                    <div className="history-menu">
                      <button onClick={() => { setRenamingItem(item.id); setRenameText(item.topic); setHistoryMenu(null); }}>
                        <IconPencil size={14} /> 重命名
                      </button>
                      <button onClick={() => pinHistoryItem(item.id)}>
                        <IconPin size={14} /> 置顶
                      </button>
                      <button className="danger" onClick={() => deleteHistoryItem(item.id)}>
                        <IconTrash size={14} /> 删除
                      </button>
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>

        <button className={`explore-btn ${view === "skill" ? "active" : ""}`} onClick={() => setView("skill")}>
          <IconGrid size={15} /> <span className="btn-label">探索 Skill</span>
        </button>

        {/* 底部：后端状态 + 设置 */}
        <div className="sidebar-footer">
          <div
            className="backend-status"
            title={backendOnline ? "后端已连接" : "后端未启动——请运行 uvicorn app.main:app --port 8001"}
          >
            <span className={`backend-dot ${backendOnline ? "online" : ""}`} />
            <span>{backendOnline ? "后端已连接" : "后端未启动"}</span>
          </div>
          <SettingsButton
            theme={theme}
            setTheme={setTheme}
            params={genParams}
            onParamsChange={setGenParams}
            models={models}
            onModelsChange={setModels}
            providerCreds={providerCreds}
            onProviderCredsChange={setProviderCreds}
            searchServices={searchServices}
            onSearchServicesChange={setSearchServices}
            activeSearchService={activeSearchService}
            onActiveSearchServiceChange={setActiveSearchService}
          />
        </div>
      </aside>

      <main className="main">
        {/* 顶栏：左会话名 · 右窗口控制 */}
        <header className="titlebar" data-tauri-drag-region onDoubleClick={onTitlebarDoubleClick}>
          <div className="titlebar-brand" data-tauri-drag-region>
            <span className="tb-name" title={title}>{title}</span>
          </div>
          <div className="titlebar-right">
            <div className="titlebar-controls">
              <button className="tb-btn" onClick={() => getTauriWindow()?.minimize()}>
                <IconMinus size={14} />
              </button>
              <button className="tb-btn" onClick={() => getTauriWindow()?.toggleMaximize()}>
                <IconSquare size={13} />
              </button>
              <button className="tb-btn close" onClick={() => getTauriWindow()?.close()}>
                <IconClose size={14} />
              </button>
            </div>
          </div>
        </header>

        {/* 视图切换：对话 / 作品（Skill 页隐藏） */}
        {view !== "skill" && (
          <div className="view-tabs">
            <button className={`view-tab ${view === "chat" ? "active" : ""}`} onClick={() => setView("chat")}>
              <IconMessageCircle size={14} /> 对话
            </button>
            <button className={`view-tab ${view === "works" ? "active" : ""}`} onClick={() => setView("works")}>
              <IconHistory size={14} /> 作品
            </button>
          </div>
        )}

        {view === "chat" && (
          <>
            <div className="chat" ref={chatRef}>
              <div className="thread">
                {messages.length === 0 ? (
                  <div className="empty-state">
                    <div className="empty-logo" />
                    <h1 className="empty-title">想了解什么？</h1>
                    {starters.length > 0 && (
                      <div className="empty-grid">
                        {starters.map((s) => (
                          <button key={s} className="empty-card" onClick={() => handleSend(s)}>{s}</button>
                        ))}
                      </div>
                    )}
                    {/* ⑨ 首次使用/后端未启动引导——正常桌面应用空状态要给明确下一步 */}
                    {backendOnline && !hasAnyApiKey && (
                      <p className="empty-setup-hint">
                        首次使用？先在左下角 <b>设置 → 模型</b> 里填写所用模型的 API Key，Lumen 才能开始生成。
                      </p>
                    )}
                    {!backendOnline && (
                      <p className="empty-setup-hint">
                        后端未启动——请运行 <code>uvicorn app.main:app --port 8001</code> 后再试。
                      </p>
                    )}
                  </div>
                ) : (
                  messages.map((m) => (
                    <div key={m.id} className={`msg ${m.role}`}>
                      {m.role === "assistant" ? (
                        <>
                          <div className="avatar ai"><img src={lumenLogo} alt="Lumen" /></div>
                          <div className="bubble-wrap">
                            {/* 工具卡片流：思考与执行过程毫无保留 */}
                            {m.calls && m.calls.length > 0 && (
                              <div className="tool-cards">
                                {m.calls.map((c) => (
                                  <ToolCard key={c.id} call={c} />
                                ))}
                              </div>
                            )}
                            {m.text && (
                              <div className="bubble">{m.text}</div>
                            )}
                            {m.html && (
                              <div className="preview-card">
                                <div className="preview-bar">
                                  <span>成品</span>
                                  <div>
                                    {/* 思考回放：回看历史作品时能看"AI 是怎么想到这些的" */}
                                    {currentProjectIdRef.current && (
                                      <button
                                        onClick={() => setTraceProjectId(currentProjectIdRef.current)}
                                        title="查看 AI 的思考过程"
                                      >
                                        <IconSparkle size={13} /> 思考过程
                                      </button>
                                    )}
                                    <button
                                      className={codeMsgId === m.id ? "active" : ""}
                                      onClick={() => setCodeMsgId(codeMsgId === m.id ? null : m.id)}
                                      title={codeMsgId === m.id ? "切回渲染预览" : "查看 HTML 源码（渲染时实时滚动）"}
                                    >
                                      <IconCode size={13} /> {codeMsgId === m.id ? "预览" : "源码"}
                                    </button>
                                    {m.file_path && (
                                      <button
                                        title={m.file_path}
                                        onClick={() => {
                                          navigator.clipboard?.writeText(m.file_path!);
                                          toast("已复制工作区路径");
                                        }}
                                      >
                                        <IconCopy size={13} /> 复制路径
                                      </button>
                                    )}
                                    <button onClick={() => exportHtml(m.html!)}>
                                      <IconDownload size={13} /> 导出
                                    </button>
                                    <button onClick={() => setFullscreenHtml(m.html!)}>
                                      <IconMaximize size={13} /> 全屏
                                    </button>
                                  </div>
                                </div>
                                {codeMsgId === m.id ? (
                                  <pre className="preview-code" ref={codeRef}>{m.html}</pre>
                                ) : m.finalized ? (
                                  <iframe srcDoc={m.html} sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox" title="预览" />
                                ) : (
                                  <div className="preview-pending">正在渲染…（切"源码"可看 HTML 实时生成）</div>
                                )}
                              </div>
                            )}
                            <div className="msg-actions">
                              <button title="复制" onClick={() => copyText(m.text)}><IconCopy size={14} /></button>
                            </div>
                          </div>
                        </>
                      ) : (
                        <div className="bubble-wrap user">
                          <div className="bubble">{m.text}</div>
                          <div className="msg-actions user-actions">
                            <button title="复制" onClick={() => copyText(m.text)}><IconCopy size={14} /></button>
                          </div>
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* 当前 Agent 预设联动显示——设置改了预设，这里实时反映 */}
            <div className="preset-chip-bar">
              <span className="preset-chip accent">{PRESET_NAMES[activePreset] ?? "自定义"}</span>
              {genParams.skillId && (
                <span className="preset-chip">{STYLE_NAMES[genParams.skillId] ?? genParams.skillId}</span>
              )}
              <span className="preset-chip">步数 {genParams.agentSteps}</span>
              <span className="preset-chip">搜索×{genParams.searchMax}</span>
              <span className="preset-chip">{genParams.creativeSwarmSize}脑</span>
              <span className="preset-chip">{genParams.searchEnabled ? "联网" : "离线"}</span>
            </div>

            <Composer
              onSend={handleSend}
              onStop={handleStop}
              models={models}
              modelId={composerModel}
              onModelIdChange={setComposerModel}
              iterable={iterable}
              sending={isGenerating}
              otherGenerating={otherGenerating}
              configHint={configHint}
            />
          </>
        )}

        {view === "works" && (
          <div className="trajectory">
            <div className="trajectory-head">
              <span className="trajectory-title">本对话作品</span>
              <span className="trajectory-count">{works.length} 个作品</span>
            </div>
            <div className="trajectory-list">
              {works.length === 0 && (
                <div className="trajectory-empty">还没有作品，先去对话里创作一个吧</div>
              )}
              {works.map((w) => (
                <div key={w.id} className="work-card" onClick={() => setFullscreenHtml(w.html)} title="点击全屏预览">
                  <div className="work-preview">
                    <iframe srcDoc={w.html} sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox" title={w.title} loading="lazy" />
                  </div>
                  <div className="work-info">
                    <div className="work-title">{w.title}</div>
                    <div className="work-meta">
                      <span>{w.time}</span>
                      <span>{w.steps} 步</span>
                    </div>
                    {w.tools.length > 0 && (
                      <div className="work-tools">
                        {w.tools.map((t) => (
                          <span key={t} className="work-tool-chip">{t}</span>
                        ))}
                      </div>
                    )}
                  </div>
                  <div className="work-actions" onClick={(e) => e.stopPropagation()}>
                    <button className="work-delete" onClick={() => deleteWork(w)} title="删除作品">
                      <IconTrash size={13} />
                    </button>
                    <button className="work-open" onClick={() => setFullscreenHtml(w.html)} title="全屏预览">
                      <IconMaximize size={14} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {view === "skill" && (
          <SkillPage onBack={() => setView("chat")} />
        )}
      </main>

      {/* 全屏预览 */}
      {fullscreenHtml && (
        <div className="fullscreen-overlay">
          <div className="fullscreen-bar">
            <span>全屏预览</span>
            <button className="tb-btn" onClick={() => setFullscreenHtml(null)}>
              <IconClose size={15} />
            </button>
          </div>
          <iframe srcDoc={fullscreenHtml} sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox" title="全屏预览" />
        </div>
      )}

      {/* 思考回放抽屉："AI 是怎么想到这些的？" */}
      <TraceTimeline projectId={traceProjectId} onClose={() => setTraceProjectId(null)} />
    </div>
  );
}
