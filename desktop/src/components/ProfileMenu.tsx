import { useRef, useState } from "react";
import { useClickOutside } from "../hooks/useClickOutside";
import { useDropdown } from "../hooks/useDropdown";
import Dropdown from "./Dropdown";
import LevelSelect from "./LevelSelect";

const SETTINGS_TABS = ["通用", "生成", "风格", "模型", "数据"];
const ACCENTS = [
  { label: "绿色", value: "green", color: "#10a37f" },
  { label: "紫色", value: "purple", color: "#8b5cf6" },
  { label: "蓝色", value: "blue", color: "#3b82f6" },
  { label: "橙色", value: "orange", color: "#f59e0b" },
  { label: "粉色", value: "pink", color: "#ec4899" },
];

const THEME_OPTIONS = [
  { value: "dark", label: "暗" },
  { value: "light", label: "亮" },
  { value: "system", label: "系统" },
];
const LANG_OPTIONS = [
  { value: "中文", label: "中文" },
  { value: "English", label: "English" },
];
const MODEL_OPTIONS = [
  { value: "Flash", label: "Flash" },
  { value: "Pro", label: "Pro" },
];
const MODE_OPTIONS = [
  { value: "网页", label: "网页" },
  { value: "游戏", label: "游戏" },
];
const STYLE_OPTIONS = [
  { value: "像素", label: "像素" },
  { value: "杂志", label: "杂志" },
  { value: "信息图", label: "信息图" },
  { value: "3D", label: "3D" },
];
const TEMP_OPTIONS = [
  { id: "precise", name: "精确", desc: "更严谨，适合事实内容" },
  { id: "balanced", name: "平衡", desc: "创意与准确平衡" },
  { id: "creative", name: "创意", desc: "更天马行空，适合创意内容" },
];
const STEPS_OPTIONS = [
  { id: "fast", name: "快速", desc: "更快出结果" },
  { id: "standard", name: "标准", desc: "平衡速度与质量" },
  { id: "deep", name: "深入", desc: "更多步骤，更完善" },
];
const SEARCH_OPTIONS = [
  { id: "off", name: "关闭", desc: "不联网，只用自身知识" },
  { id: "few", name: "少量", desc: "快速搜一下" },
  { id: "standard", name: "标准", desc: "平衡" },
  { id: "many", name: "大量", desc: "搜得更全" },
];

export default function ProfileMenu({
  theme,
  setTheme,
  accent,
  setAccent,
}: {
  theme: "dark" | "light" | "system";
  setTheme: (t: "dark" | "light" | "system") => void;
  accent: string;
  setAccent: (a: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [appearanceOpen, setAppearanceOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsTab, setSettingsTab] = useState("通用");
  const accentDrop = useDropdown();

  const [lang, setLang] = useState("中文");
  const [defaultModel, setDefaultModel] = useState("Flash");
  const [temperature, setTemperature] = useState("balanced");
  const [maxSteps, setMaxSteps] = useState("standard");
  const [budget, setBudget] = useState(1.0);
  const [searchLevel, setSearchLevel] = useState("standard");
  const [searchEnabled, setSearchEnabled] = useState(true);
  const [defaultMode, setDefaultMode] = useState("网页");
  const [defaultStyle, setDefaultStyle] = useState("像素");
  const [apiKey, setApiKey] = useState("");
  const [apiBase, setApiBase] = useState("https://api.deepseek.com");
  const [historyLimit, setHistoryLimit] = useState(100);

  const menuRef = useRef<HTMLDivElement>(null);
  useClickOutside(menuRef, open, () => setOpen(false));

  return (
    <>
      <div className="profile-wrap" ref={menuRef}>
        <div className="user-menu" onClick={() => setOpen((v) => !v)}>
          <div className="avatar">朱</div>
          <div className="user-info">
            <span className="username">朱子钦</span>
          </div>
        </div>

        {open && (
          <div className="profile-menu">
            <div className="profile-header">
              <div className="avatar">朱</div>
              <div className="user-info">
                <span className="username">朱子钦</span>
              </div>
            </div>
            <div className="profile-sep" />

            <button className="profile-item" onClick={() => setAppearanceOpen((v) => !v)}>🎨 外观</button>
            {appearanceOpen && (
              <div className="appearance-sub">
                <button className={theme === "dark" ? "active" : ""} onClick={() => setTheme("dark")}>🌙 暗 {theme === "dark" && "✓"}</button>
                <button className={theme === "light" ? "active" : ""} onClick={() => setTheme("light")}>☀️ 亮 {theme === "light" && "✓"}</button>
                <button className={theme === "system" ? "active" : ""} onClick={() => setTheme("system")}>💻 系统 {theme === "system" && "✓"}</button>
              </div>
            )}

            <button className="profile-item" onClick={() => { setSettingsOpen(true); setOpen(false); }}>⚙️ 设置</button>
          </div>
        )}
      </div>

      {settingsOpen && (
        <div className="drawer-overlay" onClick={() => setSettingsOpen(false)}>
          <div className="settings-drawer" onClick={(e) => e.stopPropagation()}>
            <div className="drawer-head">
              <span>设置</span>
              <button className="tb-btn" onClick={() => setSettingsOpen(false)}>✕</button>
            </div>
            <div className="drawer-body">
              <div className="drawer-tabs">
                {SETTINGS_TABS.map((t) => (
                  <button key={t} className={settingsTab === t ? "active" : ""} onClick={() => setSettingsTab(t)}>{t}</button>
                ))}
              </div>
              <div className="drawer-content">
                {settingsTab === "通用" && (
                  <>
                    <div className="setting-row">
                      <span>主题</span>
                      <Dropdown value={theme} options={THEME_OPTIONS} onChange={(v) => setTheme(v as "dark" | "light" | "system")} />
                    </div>
                    <div className="setting-row">
                      <span>强调色</span>
                      <button ref={accentDrop.triggerRef} className="dropdown-btn" onClick={accentDrop.toggle}>{ACCENTS.find((a) => a.value === accent)?.label ?? accent} {accentDrop.open ? "▾" : "◂"}</button>
                      {accentDrop.portal(
                        <div className="dropdown-menu">
                          {ACCENTS.map((a) => (
                            <button key={a.value} className={accent === a.value ? "active" : ""} onClick={() => { setAccent(a.value); accentDrop.close(); }}>
                              <span className="accent-dot" style={{ background: a.color }} />
                              {a.label}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                    <div className="setting-row">
                      <span>语言</span>
                      <Dropdown value={lang} options={LANG_OPTIONS} onChange={setLang} />
                    </div>
                  </>
                )}

                {settingsTab === "生成" && (
                  <>
                    <div className="setting-row">
                      <span>默认模型</span>
                      <Dropdown value={defaultModel} options={MODEL_OPTIONS} onChange={setDefaultModel} />
                    </div>
                    <div className="setting-row">
                      <span>温度</span>
                      <LevelSelect value={temperature} options={TEMP_OPTIONS} onChange={setTemperature} />
                    </div>
                    <div className="setting-row">
                      <span>最大步数</span>
                      <LevelSelect value={maxSteps} options={STEPS_OPTIONS} onChange={setMaxSteps} />
                    </div>
                    <div className="setting-row">
                      <span>单次预算</span>
                      <input className="setting-input" type="number" value={budget} onChange={(e) => setBudget(parseFloat(e.target.value))} />
                    </div>
                    <div className="setting-row">
                      <span>搜索次数上限</span>
                      <LevelSelect value={searchLevel} options={SEARCH_OPTIONS} onChange={setSearchLevel} />
                    </div>
                    <div className="setting-row">
                      <span>联网搜索</span>
                      <button className={`toggle ${searchEnabled ? "on" : ""}`} onClick={() => setSearchEnabled((v) => !v)} />
                    </div>
                  </>
                )}

                {settingsTab === "风格" && (
                  <>
                    <div className="setting-row">
                      <span>默认模式</span>
                      <Dropdown value={defaultMode} options={MODE_OPTIONS} onChange={setDefaultMode} />
                    </div>
                    <div className="setting-row">
                      <span>默认视觉风格</span>
                      <Dropdown value={defaultStyle} options={STYLE_OPTIONS} onChange={setDefaultStyle} />
                    </div>
                  </>
                )}

                {settingsTab === "模型" && (
                  <>
                    <div className="setting-row">
                      <span>DeepSeek API Key</span>
                      <input className="setting-input" type="password" placeholder="sk-..." value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
                    </div>
                    <div className="setting-row">
                      <span>API 地址</span>
                      <input className="setting-input" value={apiBase} onChange={(e) => setApiBase(e.target.value)} />
                    </div>
                  </>
                )}

                {settingsTab === "数据" && (
                  <>
                    <div className="setting-row">
                      <span>历史保留条数</span>
                      <input className="setting-input" type="number" value={historyLimit} onChange={(e) => setHistoryLimit(parseInt(e.target.value))} />
                    </div>
                    <div className="setting-row">
                      <span>导出数据</span>
                      <button className="setting-action">导出</button>
                    </div>
                    <div className="setting-row">
                      <span className="danger-text">清除全部历史</span>
                      <button className="setting-action danger-btn">清除</button>
                    </div>
                  </>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
