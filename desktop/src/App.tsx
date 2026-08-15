import { useEffect, useRef, useState } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import Composer from "./components/Composer";
import SkillPage from "./components/SkillPage";
import ProfileMenu from "./components/ProfileMenu";
import { useClickOutside } from "./hooks/useClickOutside";
import "./App.css";

const appWindow = getCurrentWindow();

/** 决策步骤：AI 制作过程透明化 */
type Step = { icon: string; text: string; status: "pending" | "done" };
type Msg = {
  id: number;
  role: "user" | "assistant";
  text: string;
  html?: string;
  steps?: Step[];
  source?: string; // 触发这条回复的用户输入（重新生成用）
};
type Theme = "dark" | "light" | "system";

const SAMPLE: Msg[] = [
  { id: 1, role: "user", text: "秦始皇修长城" },
  {
    id: 2,
    role: "assistant",
    text: "秦始皇统一六国后，为抵御北方匈奴南下，征发民夫修筑长城，连接战国时期秦、赵、燕的旧长城，形成西起临洮、东至辽东的万里防线。",
  },
];

const STARTERS = ["秦始皇修长城", "Turing 破译 Enigma", "Python 装饰器", "郑和下西洋"];

/** 决策流程（占位；接后端后由真实决策日志替换） */
const DECISION_STEPS = [
  { icon: "🔍", text: "搜索素材并核对来源" },
  { icon: "🎨", text: "选定叙事形式与版式" },
  { icon: "✍️", text: "撰写文案并标注可信度" },
  { icon: "🖥️", text: "渲染生成页面" },
  { icon: "✅", text: "真机验证通过" },
];

const PLACEHOLDER_HTML = `<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><style>
  body{margin:0;height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:16px;background:linear-gradient(135deg,#1f2937,#111827);color:#fff;font-family:sans-serif}
  h1{font-size:28px} p{color:#9ca3af} button{padding:12px 24px;font-size:16px;border:none;border-radius:8px;background:#10a37f;color:#fff;cursor:pointer}
</style></head>
<body><h1>时光像素 · 示例页面</h1><p>占位 HTML，接后端后显示真实生成的页面 / 游戏</p><button onclick="this.textContent='你点了我！'">点我试试</button></body></html>`;

function demoPage(title: string, desc: string, gradient: string): string {
  return `<!DOCTYPE html>
<html><head><meta charset="UTF-8"><style>
  body{margin:0;min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;background:${gradient};color:#fff;font-family:sans-serif;padding:24px;text-align:center}
  h1{font-size:32px;margin:0} p{opacity:.85;max-width:460px;line-height:1.7} button{padding:11px 22px;border:none;border-radius:8px;background:rgba(255,255,255,.22);color:#fff;cursor:pointer;font-size:15px}
</style></head>
<body><h1>${title}</h1><p>${desc}</p><button onclick="this.textContent='已互动 ✓'">点我互动</button></body></html>`;
}

const DEMO: Record<string, { user: string; assistant: string; html: string }> = {
  "秦始皇修长城": { user: "秦始皇修长城", assistant: "已生成页面（占位）：", html: demoPage("秦始皇修长城", "前 221 年统一六国后，为抵御北方匈奴，征发民夫连接旧长城，筑成万里防线。", "linear-gradient(135deg,#7c2d12,#450a0a)") },
  "Turing 破译 Enigma": { user: "Turing 破译 Enigma", assistant: "已生成页面（占位）：", html: demoPage("Turing 破译 Enigma", "二战中阿兰·图灵领导的团队破解德军 Enigma 密码机，改变了战争进程。", "linear-gradient(135deg,#1e3a5f,#0f172a)") },
  "郑和下西洋": { user: "郑和下西洋", assistant: "已生成页面（占位）：", html: demoPage("郑和下西洋", "1405-1433 年，郑和率船队七下西洋，最远抵达东非海岸。", "linear-gradient(135deg,#14532d,#052e16)") },
};

export default function App() {
  const [view, setView] = useState<"chat" | "skill">("chat");
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [messages, setMessages] = useState<Msg[]>(SAMPLE);
  const [typing, setTyping] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editText, setEditText] = useState("");
  const [historyMenu, setHistoryMenu] = useState<string | null>(null);
  const [history, setHistory] = useState<string[]>(["秦始皇修长城", "Turing 破译 Enigma", "郑和下西洋"]);
  const [renamingItem, setRenamingItem] = useState<string | null>(null);
  const [renameText, setRenameText] = useState("");
  const [theme, setTheme] = useState<Theme>("dark");
  const [accent, setAccent] = useState("green");
  const [fullscreenHtml, setFullscreenHtml] = useState<string | null>(null);

  const historyRef = useRef<HTMLDivElement>(null);
  useClickOutside(historyRef, historyMenu !== null, () => setHistoryMenu(null));

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

  useEffect(() => {
    const ACCENTS: Record<string, string> = {
      green: "#10a37f",
      purple: "#8b5cf6",
      blue: "#3b82f6",
      orange: "#f59e0b",
      pink: "#ec4899",
    };
    document.documentElement.style.setProperty("--accent", ACCENTS[accent] ?? "#10a37f");
  }, [accent]);

  /**
   * 决策流程模拟：用户消息 → 决策步骤逐个点亮 → 正文 → 成品 HTML。
   * 接后端后，把这段 setTimeout 替换为 WebSocket 流式接收即可。
   */
  const runFlow = (text: string, opts?: { replaceId?: number }) => {
    if (opts?.replaceId == null) {
      const userMsgId = Date.now();
      setMessages((ms) => [...ms, { id: userMsgId, role: "user", text }]);
    }
    setTyping(true);
    const assistId = Date.now() + 1;
    const STEP_MS = 380;
    setTimeout(() => {
      setTyping(false);
      setMessages((ms) => [
        ...ms,
        { id: assistId, role: "assistant", text: "", source: text, steps: DECISION_STEPS.map((s) => ({ ...s, status: "pending" })) },
      ]);
      DECISION_STEPS.forEach((_, i) => {
        setTimeout(() => {
          setMessages((ms) =>
            ms.map((m) =>
              m.id === assistId
                ? { ...m, steps: m.steps?.map((x, xi) => (xi <= i ? { ...x, status: "done" } : x)) }
                : m
            )
          );
        }, STEP_MS * (i + 1));
      });
      setTimeout(() => {
        const demo = DEMO[text];
        const html = demo?.html ?? PLACEHOLDER_HTML;
        const assistantText = demo?.assistant ?? "已生成页面（占位）：";
        setMessages((ms) =>
          ms.map((m) =>
            m.id === assistId
              ? { ...m, text: assistantText, html, steps: m.steps?.map((x) => ({ ...x, status: "done" })) }
              : m
          )
        );
      }, STEP_MS * DECISION_STEPS.length + 300);
    }, 500);
  };

  const handleSend = (text: string) => runFlow(text);

  /** 重新生成：移除该条回复，用同一输入重跑 */
  const regenerate = (m: Msg) => {
    if (!m.source) return;
    setMessages((ms) => ms.filter((x) => x.id !== m.id));
    runFlow(m.source, { replaceId: m.id });
  };

  /** 重发（编辑后）：丢弃该条及其后的消息，用当前文本重跑 */
  const resend = (m: Msg) => {
    setMessages((ms) => {
      const idx = ms.findIndex((x) => x.id === m.id);
      if (idx < 0) return ms;
      return ms.slice(0, idx);
    });
    runFlow(m.text);
  };

  const loadConversation = (name: string) => {
    const demo = DEMO[name];
    if (demo) {
      setMessages([
        { id: Date.now(), role: "user", text: demo.user },
        { id: Date.now() + 1, role: "assistant", text: demo.assistant, html: demo.html },
      ]);
    }
    setView("chat");
  };

  const saveEdit = (id: number) => {
    setMessages((ms) => ms.map((m) => (m.id === id ? { ...m, text: editText } : m)));
    setEditingId(null);
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

  const renameHistory = (oldName: string) => {
    setHistory((h) => h.map((x) => (x === oldName ? renameText : x)));
    setRenamingItem(null);
  };
  const deleteHistory = (name: string) => setHistory((h) => h.filter((x) => x !== name));
  const pinHistory = (name: string) => setHistory((h) => [name, ...h.filter((x) => x !== name)]);

  const title =
    view === "skill"
      ? "Skill"
      : messages.length === 0
        ? "新对话"
        : (messages.find((m) => m.role === "user")?.text ?? "新对话");

  return (
    <div className="app">
      {sidebarOpen && (
        <aside className="sidebar">
          <button className="new-chat" onClick={() => { setView("chat"); setMessages([]); }}>
            ＋ 新对话
          </button>

          <div className="history" ref={historyRef}>
            <div className="history-group">最近</div>
            {history.map((item) => (
              <div key={item} className="history-item" onMouseLeave={() => setHistoryMenu(null)}>
                {renamingItem === item ? (
                  <input
                    className="history-rename-input"
                    value={renameText}
                    onChange={(e) => setRenameText(e.target.value)}
                    autoFocus
                    onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); renameHistory(item); } }}
                    onBlur={() => renameHistory(item)}
                  />
                ) : (
                  <span className="history-text" onClick={() => loadConversation(item)}>{item}</span>
                )}
                <button className="history-more" onClick={() => setHistoryMenu(historyMenu === item ? null : item)}>⋮</button>
                {historyMenu === item && (
                  <div className="history-menu">
                    <button onClick={() => { setRenamingItem(item); setRenameText(item); setHistoryMenu(null); }}>✏️ 重命名</button>
                    <button onClick={() => { pinHistory(item); setHistoryMenu(null); }}>📌 置顶</button>
                    <button className="danger" onClick={() => { deleteHistory(item); setHistoryMenu(null); }}>🗑️ 删除</button>
                  </div>
                )}
              </div>
            ))}
          </div>

          <button className={`explore-btn ${view === "skill" ? "active" : ""}`} onClick={() => setView("skill")}>
            🧩 探索 Skill
          </button>

          <ProfileMenu theme={theme} setTheme={setTheme} accent={accent} setAccent={setAccent} />
        </aside>
      )}

      <main className="main">
        <header className="titlebar" data-tauri-drag-region>
          <button className="tb-btn" onClick={() => setSidebarOpen((v) => !v)}>☰</button>
          <span className="titlebar-title" data-tauri-drag-region>{title}</span>
          <div className="titlebar-right">
            <div className="titlebar-controls">
              <button className="tb-btn" onClick={() => appWindow.minimize()}>─</button>
              <button className="tb-btn" onClick={() => appWindow.toggleMaximize()}>□</button>
              <button className="tb-btn close" onClick={() => appWindow.close()}>✕</button>
            </div>
          </div>
        </header>

        {view === "chat" ? (
          <>
            <div className="chat">
              <div className="thread">
                {messages.length === 0 ? (
                  <div className="empty-state">
                    <div className="empty-logo" />
                    <h1 className="empty-title">有什么能帮你的？</h1>
                    <div className="empty-grid">
                      {STARTERS.map((s) => (
                        <button key={s} className="empty-card" onClick={() => handleSend(s)}>{s}</button>
                      ))}
                    </div>
                  </div>
                ) : (
                  messages.map((m) => (
                    <div key={m.id} className={`msg ${m.role}`}>
                      {m.role === "assistant" ? (
                        <>
                          <div className="avatar ai" />
                          <div className="bubble-wrap">
                            {m.steps && m.steps.length > 0 && (
                              <div className="decision-log">
                                {m.steps.map((s, i) => (
                                  <div key={i} className={`decision-step ${s.status}`}>
                                    <span className="decision-icon">{s.status === "done" ? "✓" : s.icon}</span>
                                    <span className="decision-text">{s.text}</span>
                                  </div>
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
                                    <button onClick={() => exportHtml(m.html!)}>⬇ 导出</button>
                                    <button onClick={() => setFullscreenHtml(m.html!)}>⛶ 全屏</button>
                                  </div>
                                </div>
                                <iframe srcDoc={m.html} sandbox="allow-scripts" title="预览" />
                              </div>
                            )}
                            <div className="msg-actions">
                              <button title="复制" onClick={() => copyText(m.text)}>📋</button>
                              <button title="重新生成" onClick={() => regenerate(m)}>↻</button>
                            </div>
                          </div>
                        </>
                      ) : (
                        <div className="bubble-wrap user">
                          {editingId === m.id ? (
                            <textarea
                              className="edit-textarea"
                              value={editText}
                              onChange={(e) => setEditText(e.target.value)}
                              autoFocus
                              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); saveEdit(m.id); } }}
                              onBlur={() => saveEdit(m.id)}
                            />
                          ) : (
                            <>
                              <div className="bubble">{m.text}</div>
                              <div className="msg-actions user-actions">
                                <button title="编辑" onClick={() => { setEditingId(m.id); setEditText(m.text); }}>✏️</button>
                                <button title="重发" onClick={() => resend(m)}>↻</button>
                                <button title="复制" onClick={() => copyText(m.text)}>📋</button>
                              </div>
                            </>
                          )}
                        </div>
                      )}
                    </div>
                  ))
                )}

                {typing && (
                  <div className="msg assistant">
                    <div className="avatar ai" />
                    <div className="typing-indicator">
                      <span /><span /><span />
                    </div>
                  </div>
                )}
              </div>
            </div>

            <Composer onSend={handleSend} />
          </>
        ) : (
          <SkillPage onBack={() => setView("chat")} />
        )}
      </main>

      {/* 全屏预览 */}
      {fullscreenHtml && (
        <div className="fullscreen-overlay">
          <div className="fullscreen-bar">
            <span>全屏预览</span>
            <button className="tb-btn" onClick={() => setFullscreenHtml(null)}>✕</button>
          </div>
          <iframe srcDoc={fullscreenHtml} sandbox="allow-scripts" title="全屏预览" />
        </div>
      )}
    </div>
  );
}
