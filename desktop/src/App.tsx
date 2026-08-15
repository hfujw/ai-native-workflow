import { useCallback, useEffect, useRef, useState } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import Composer from "./components/Composer";
import SkillPage from "./components/SkillPage";
import SettingsButton from "./components/SettingsButton";
import ToolCard from "./components/ToolCard";
import { useClickOutside } from "./hooks/useClickOutside";
import { useGenerate } from "./hooks/useGenerate";
import { usePersistentState } from "./hooks/usePersistentState";
import {
  deleteProject,
  fetchEvents,
  fetchHistory,
  fetchProject,
  pinProject,
  renameProject,
} from "./lib/api";
import type { GenParams, ModelItem, Msg, ProviderCreds, ToolCall, ToolId } from "./lib/api";
import { deleteSession, loadSessions, saveSession } from "./lib/sessions";
import type { SavedSession } from "./lib/sessions";
import {
  IconClose,
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

const appWindow = getCurrentWindow();

type Theme = "dark" | "light" | "system";
type View = "chat" | "works" | "skill";

/** 作品页作品（接后端后从当前对话的真实产出填充） */
type Work = {
  id: string;
  title: string;
  html: string;
  time: string;
  cost: string;
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

/** 默认模型（首次启动；不可移除——保证输入框永远有模型可选） */
const DEFAULT_MODELS: ModelItem[] = [
  { id: "flash", name: "deepseek-Flash", modelId: "deepseek-chat", provider: "DeepSeek", removable: false },
  { id: "pro", name: "deepseek-Pro", modelId: "deepseek-reasoner", provider: "DeepSeek", removable: false },
];

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
  const [genParams, setGenParams] = usePersistentState<GenParams>("lumen.genParams", {
    agentSteps: 20,
    llmSteps: 10,
    budget: 1.0,
    searchMax: 8,
    searchEnabled: true,
    skillId: "magazine",  // 默认预设（知识探险家）推荐的风格 skill
  });
  const [models, setModels] = usePersistentState<ModelItem[]>("lumen.models", DEFAULT_MODELS);
  // 选中的模型（持久化；发送时解析成后端模型 ID 随 WS 传递）
  const [composerModel, setComposerModel] = usePersistentState("lumen.composerModel", "flash");
  // 保证默认模型永远存在且带 provider：旧的持久化里删过/为空/缺 provider 都修
  useEffect(() => {
    setModels((ms) => {
      const missing = DEFAULT_MODELS.filter((d) => !ms.some((m) => m.id === d.id));
      const needProvider = ms
        .filter((m) => !m.provider && DEFAULT_MODELS.some((d) => d.id === m.id))
        .map((m) => ({ ...m, provider: "DeepSeek" }));
      if (!missing.length && !needProvider.length) return ms;
      return [...needProvider, ...ms.filter((m) => !needProvider.some((n) => n.id === m.id)), ...missing];
    });
  }, [setModels]);
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
  // 搜索凭证（Tavily Key）——与 LLM 凭证独立管理；单一来源在 App，随 WS 发送
  const [tavilyKey, setTavilyKey] = usePersistentState("lumen.tavilyKey", "");
  const [fullscreenHtml, setFullscreenHtml] = useState<string | null>(null);
  /** 空状态建议话题（来自后端知识库 /api/events） */
  const [starters, setStarters] = useState<string[]>([]);
  /** 历史对话（"新对话"时当前对话自动存档到这里，可找回） */
  const [sessions, setSessions] = useState<SavedSession[]>(() => loadSessions());

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

  /** 回看历史作品：先存档当前对话（防丢），再拉取记录显示 */
  const openHistory = async (id: string) => {
    archiveCurrent();
    stop();
    setIterable(false);
    try {
      const p = await fetchProject(id);
      const versions = p.versions ?? [];
      const last = versions[versions.length - 1];
      const cost = p.cost ?? 0;
      setMessages([
        { id: Date.now(), role: "user", text: p.topic },
        {
          id: Date.now() + 1,
          role: "assistant",
          text: `历史作品回看 · 生成于 ${new Date(p.created_at * 1000).toLocaleString()} · ${p.steps} 步 · ¥${cost.toFixed(4)} · 共 ${p.iterations} 版`,
          html: last?.html ?? "",
          cost,
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
    appWindow.toggleMaximize();
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

  /** 存档当前对话（有内容才存） */
  const archiveCurrent = () => {
    if (messages.length === 0) return;
    const title = messages.find((m) => m.role === "user")?.text ?? "对话";
    setSessions(
      saveSession({
        id: `s${Date.now()}`,
        title,
        updatedAt: Date.now(),
        messages,
      })
    );
  };

  /** 新对话：当前对话存档，另开一个空对话 */
  const startNewChat = () => {
    archiveCurrent();
    stop(); // 关掉进行中的生成连接
    setIterable(false);
    setView("chat");
    setMessages([]);
    setHistorySearch("");
  };

  /** 打开历史对话：先存档当前（防丢），再加载目标会话 */
  const openSession = (s: SavedSession) => {
    archiveCurrent();
    stop();
    setIterable(false);
    setMessages(s.messages);
    setView("chat");
  };

  const removeSession = (id: string) => setSessions(deleteSession(id));

  // 生成/迭代消息流的卡片配对：按消息顺序配对（thinking 记当前卡片，tool_result 更新它）
  // ——不依赖后端 step 编号（迭代时 step 都是 0，会互相覆盖）
  const targetIdRef = useRef<number | null>(null);
  const seqRef = useRef(0);
  const runningCardRef = useRef<string | null>(null);

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
        seqRef.current += 1;
        const cid = `c${seqRef.current}`;
        runningCardRef.current = cid;
        setMessages((ms) =>
          ms.map((m) =>
            m.id === targetId
              ? {
                  ...m,
                  cost: Number(msg.budget ?? m.cost ?? 0),
                  calls: upsertCall(m.calls ?? [], {
                    id: cid,
                    tool: tool as ToolId,
                    title,
                    status: "running",
                    thought: String(msg.thought ?? ""),
                  }),
                }
              : m
          )
        );
        break;
      }
      case "tool_result": {
        const tool = String(msg.tool ?? "");
        const title = TOOL_TITLES[tool] ?? tool;
        const cid = runningCardRef.current ?? `c${++seqRef.current}`;
        runningCardRef.current = null;
        setMessages((ms) =>
          ms.map((m) =>
            m.id === targetId
              ? {
                  ...m,
                  cost: Number(msg.budget ?? m.cost ?? 0),
                  calls: upsertCall(m.calls ?? [], {
                    id: cid,
                    tool: (TOOL_TITLES[tool] ? tool : "think") as ToolId,
                    title,
                    status: "done",
                    summary: String(msg.summary ?? ""),
                  }),
                }
              : m
          )
        );
        break;
      }
      case "html_chunk": {
        // 流式渲染：页面逐步"长出来"
        setMessages((ms) =>
          ms.map((m) => (m.id === targetId ? { ...m, html: String(msg.html ?? "") } : m))
        );
        break;
      }
      case "page_ready": {
        setMessages((ms) =>
          ms.map((m) =>
            m.id === targetId
              ? { ...m, html: String(msg.page_html ?? ""), text: "生成完成。" }
              : m
          )
        );
        setIterable(true); // 进入可迭代状态：下次输入走 instruction 改页面
        loadHistory(); // 新作品入库 → 刷新创作区
        break;
      }
      case "generation_failed": {
        setMessages((ms) =>
          ms.map((m) =>
            m.id === targetId ? { ...m, text: `生成失败：${String(msg.reason ?? "未知原因")}` } : m
          )
        );
        setIterable(false);
        break;
      }
    }
  };

  /** 新开一次生成（或迭代连接断开时的回退） */
  const startGeneration = (text: string) => {
    setIterable(false);
    const userMsgId = Date.now();
    const assistId = Date.now() + 1;
    targetIdRef.current = assistId;
    setMessages((ms) => [
      ...ms,
      { id: userMsgId, role: "user", text },
      { id: assistId, role: "assistant", text: "", calls: [] },
    ]);
    setView("chat");

    const currentModel = models.find((m) => m.id === composerModel);
    const creds = currentModel ? providerCreds[currentModel.provider] : undefined;
    send(text, {
      params: genParams,
      model: currentModel?.modelId,
      apiKey: creds?.apiKey || undefined,
      apiBase: creds?.apiBase || undefined,
      tavilyKey: tavilyKey || undefined,
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

  const copyText = (text: string) => {
    navigator.clipboard?.writeText(text);
  };

  const exportHtml = (html: string) => {
    const blob = new Blob([html], { type: "text/html" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "page.html";
    a.click();
    URL.revokeObjectURL(url);
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
    try {
      await deleteProject(id);
      setHistory((h) => h.filter((x) => x.id !== id));
    } catch {
      // 静默
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

  // 作品页：当前对话的真实产出
  const works: Work[] = messages
    .filter((m) => m.role === "assistant" && m.html)
    .map((m) => ({
      id: `live-${m.id}`,
      title: m.source ?? "未命名作品",
      html: m.html!,
      time: "刚刚",
      cost: `¥${(m.cost ?? 0).toFixed(4)}`,
      steps: m.calls?.length ?? 0,
      tools: (m.calls ?? []).map((c) => c.title).filter((t) => t !== "Think"),
    }));

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

        {/* 创作区：历史对话 + 搜索 + 作品列表 */}
        <div className="history">
          <div className="history-head">创作区</div>
          {sessions.length > 0 && (
            <>
              <div className="history-subhead">历史对话</div>
              {sessions.map((s) => (
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
          <div className="history-search">
            <IconSearch size={13} />
            <input
              value={historySearch}
              onChange={(e) => setHistorySearch(e.target.value)}
              placeholder="搜索作品..."
            />
            {historySearch && (
              <button className="history-search-clear" onClick={() => setHistorySearch("")}>
                <IconClose size={12} />
              </button>
            )}
          </div>

          <div className="history-list" ref={historyRef}>
            {filteredHistory.length === 0 ? (
              <div className="history-empty">
                {history.length === 0 ? "还没有作品，开始第一个创作吧" : "没有匹配的作品"}
              </div>
            ) : (
              filteredHistory.map((item) => (
                <div key={item.id} className="history-item" onMouseLeave={() => setHistoryMenu(null)}>
                  {renamingItem === item.id ? (
                    <input
                      className="history-rename-input"
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

        {/* 底部：设置 */}
        <div className="sidebar-footer">
          <SettingsButton
            theme={theme}
            setTheme={setTheme}
            params={genParams}
            onParamsChange={setGenParams}
            models={models}
            onModelsChange={setModels}
            providerCreds={providerCreds}
            onProviderCredsChange={setProviderCreds}
            tavilyKey={tavilyKey}
            onTavilyKeyChange={setTavilyKey}
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
              <button className="tb-btn" onClick={() => appWindow.minimize()}>
                <IconMinus size={14} />
              </button>
              <button className="tb-btn" onClick={() => appWindow.toggleMaximize()}>
                <IconSquare size={13} />
              </button>
              <button className="tb-btn close" onClick={() => appWindow.close()}>
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
                  </div>
                ) : (
                  messages.map((m) => (
                    <div key={m.id} className={`msg ${m.role}`}>
                      {m.role === "assistant" ? (
                        <>
                          <div className="avatar ai" />
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
                                  <span>预览</span>
                                  <div>
                                    <button onClick={() => exportHtml(m.html!)}>
                                      <IconDownload size={13} /> 导出
                                    </button>
                                    <button onClick={() => setFullscreenHtml(m.html!)}>
                                      <IconMaximize size={13} /> 全屏
                                    </button>
                                  </div>
                                </div>
                                <iframe srcDoc={m.html} sandbox="allow-scripts" title="预览" />
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

            <Composer
              onSend={handleSend}
              models={models}
              modelId={composerModel}
              onModelIdChange={setComposerModel}
              iterable={iterable}
              sending={genStatus === "running" || genStatus === "connecting"}
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
                    <iframe srcDoc={w.html} sandbox="allow-scripts" title={w.title} loading="lazy" />
                  </div>
                  <div className="work-info">
                    <div className="work-title">{w.title}</div>
                    <div className="work-meta">
                      <span>{w.time}</span>
                      <span>{w.cost}</span>
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
                  <div className="work-open">
                    <IconMaximize size={14} />
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
          <iframe srcDoc={fullscreenHtml} sandbox="allow-scripts" title="全屏预览" />
        </div>
      )}
    </div>
  );
}
