import { useEffect, useMemo, useState } from "react";
import type { ComponentType } from "react";
import { useDropdown } from "../hooks/useDropdown";
import { usePersistentState } from "../hooks/usePersistentState";
import { groupModelsByProvider, type GenParams, type ModelItem, type ProviderCreds } from "../lib/api";
import type { IconProps } from "./icons";
import {
  IconChevronDown,
  IconClose,
  IconCpu,
  IconGear,
  IconPenTool,
  IconPlus,
  IconSparkle,
} from "./icons";

type TabDef = { id: string; label: string; icon: ComponentType<IconProps> };
const SETTINGS_TABS: TabDef[] = [
  { id: "preset", label: "Agent 预设", icon: IconSparkle },
  { id: "appearance", label: "外观", icon: IconPenTool },
  { id: "models", label: "模型", icon: IconCpu },
];

type Preset = {
  id: string;
  name: string;
  badge?: string;
  desc: string;
  trust: "system" | "user";
  /** 推荐的 skill 组合（能力由 skill 赋予，预设只推荐） */
  skills: string[];
  /** 编排参数模板：设为默认时应用这组参数 */
  params: { agentSteps: number; llmSteps: number; searchMax: number; searchEnabled: boolean; budget: number };
};
const PRESETS: Preset[] = [
  {
    id: "storyteller", name: "知识探险家", badge: "官方", trust: "system",
    desc: "把故事讲成编辑级杂志长图，素材充足时尽量考证",
    skills: ["杂志", "搜索"],
    params: { agentSteps: 20, llmSteps: 10, searchMax: 8, searchEnabled: true, budget: 1.0 },
  },
  {
    id: "alchemist", name: "数据炼金师", badge: "官方", trust: "system",
    desc: "信息图优先，数字与图表一目了然",
    skills: ["信息图", "图表"],
    params: { agentSteps: 15, llmSteps: 8, searchMax: 5, searchEnabled: true, budget: 0.8 },
  },
  {
    id: "pixelist", name: "像素时光机", badge: "官方", trust: "system",
    desc: "复古像素风格，适合游戏化与怀旧题材",
    skills: ["像素", "搜索"],
    params: { agentSteps: 25, llmSteps: 12, searchMax: 4, searchEnabled: true, budget: 1.2 },
  },
  {
    id: "curator", name: "极简策展人", badge: "官方", trust: "system",
    desc: "安静留白的知识卡片，不联网，靠自身知识",
    skills: ["杂志"],
    params: { agentSteps: 10, llmSteps: 6, searchMax: 2, searchEnabled: false, budget: 0.5 },
  },
];

/** 设置行：标题 + 可选描述 + 右侧控件 */
function SettingRow({
  title,
  desc,
  children,
}: {
  title: string;
  desc?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="setting-row">
      <div className="setting-row-text">
        <span className="setting-row-title">{title}</span>
        {desc && <span className="setting-row-desc">{desc}</span>}
      </div>
      {children}
    </div>
  );
}

/** skill 名称 → id（预设推荐 → 生成时注入模板资产） */
const SKILL_ID_BY_NAME: Record<string, string> = {
  像素: "pixel",
  杂志: "magazine",
  信息图: "infographic",
  搜索: "search",
  图表: "chart",
  "3D 场景": "3d",
};

/** 侧边栏底部设置入口：DSH 式居中模态（Agent 预设 / 外观 / 模型） */
export default function SettingsButton({
  theme,
  setTheme,
  params,
  onParamsChange,
  models,
  onModelsChange,
  providerCreds,
  onProviderCredsChange,
}: {
  theme: "dark" | "light" | "system";
  setTheme: (t: "dark" | "light" | "system") => void;
  /** 生成参数（受控：由 App 持有，发送时随 WS 传给后端） */
  params: GenParams;
  onParamsChange: (p: GenParams) => void;
  /** 模型列表（受控：由 App 持有并持久化，Composer 共用） */
  models: ModelItem[];
  onModelsChange: (m: ModelItem[]) => void;
  /** 提供方凭证（受控：每个 provider 独立，App 发送时按模型 provider 取用） */
  providerCreds: Record<string, ProviderCreds>;
  onProviderCredsChange: (c: Record<string, ProviderCreds>) => void;
}) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState("preset");
  const langDrop = useDropdown();

  // 持久化：预设（刷新不丢）
  const [lang] = useState("中文"); // 界面语言切换开发中（禁用态）
  const [activePreset, setActivePreset] = usePersistentState("lumen.preset", "storyteller");
  const [customPresets, setCustomPresets] = usePersistentState<Preset[]>("lumen.customPresets", []);

  // 模型页（DSH ModelsSection：provider 行 + 一次一张编辑卡片 + 添加提供方）
  // 展开的 provider（null=收起全部；一次只展开一张）
  const [editingProvider, setEditingProvider] = useState<string | null>(null);
  // 卡片内正在编辑的模型 id（行内编辑 modelId/name）
  const [editingModel, setEditingModel] = useState<string | null>(null);
  const [editModelId, setEditModelId] = useState("");
  const [editModelName, setEditModelName] = useState("");
  // 添加提供方卡片（DSH dormant-provider select）
  const [addingProvider, setAddingProvider] = useState(false);
  // 添加表单
  const [newProvider, setNewProvider] = useState("DeepSeek");
  const [newModelId, setNewModelId] = useState("deepseek-chat");
  const [newDisplayName, setNewDisplayName] = useState("");

  // 每个 provider 的凭证编辑态（正在换 key 的 provider + 新 key 输入；绝不预填旧值）
  const [editingKeyFor, setEditingKeyFor] = useState<string | null>(null);
  const [keyInput, setKeyInput] = useState("");

  /** 取某 provider 的凭证（无则返回空） */
  const credsOf = (provider: string): ProviderCreds =>
    providerCreds[provider] ?? { apiKey: "", apiBase: "" };

  const PROVIDERS: Record<string, { base: string; defaultModel: string }> = {
    DeepSeek: { base: "https://api.deepseek.com", defaultModel: "deepseek-chat" },
    OpenAI: { base: "https://api.openai.com/v1", defaultModel: "gpt-4o" },
    Anthropic: { base: "https://api.anthropic.com", defaultModel: "claude-3-5-sonnet" },
    通义千问: { base: "https://dashscope.aliyuncs.com/compatible-mode/v1", defaultModel: "qwen-plus" },
    自定义: { base: "", defaultModel: "" },
  };

  const pickProvider = (p: string) => {
    setNewProvider(p);
    const info = PROVIDERS[p];
    // 只填模型默认值，不碰全局凭证（apiBase 由凭证区块单独管理）
    setNewModelId(info.defaultModel);
    setNewDisplayName(p);
  };

  /** 打开换 key：显示空输入框（绝不预填旧 key） */
  const startEditKey = (provider: string) => {
    setKeyInput("");
    setEditingKeyFor(provider);
  };
  /** 保存新 key：写入该 provider 的凭证后关闭编辑态 */
  const saveKey = (provider: string) => {
    const v = keyInput.trim();
    if (!v) return;
    const cur = credsOf(provider);
    onProviderCredsChange({ ...providerCreds, [provider]: { ...cur, apiKey: v } });
    setEditingKeyFor(null);
    setKeyInput("");
  };
  const cancelEditKey = () => {
    setEditingKeyFor(null);
    setKeyInput("");
  };
  /** 保存 API 地址：写入该 provider 的凭证 */
  const saveBase = (provider: string, base: string) => {
    const cur = credsOf(provider);
    onProviderCredsChange({ ...providerCreds, [provider]: { ...cur, apiBase: base } });
  };

  /** 保存编辑：模型 ID + 显示名称写回列表（受控 + 持久化），凭证独立不受影响 */
  const saveEdit = (id: string) => {
    onModelsChange(
      models.map((x) =>
        x.id === id
          ? {
              ...x,
              modelId: editModelId.trim() || x.modelId,
              name: editModelName.trim() || x.name,
            }
          : x
      )
    );
    setEditingModel(null);
  };
  const removeModel = (id: string) => onModelsChange(models.filter((m) => m.id !== id));

  /** 应用预设：设为默认 + 套用一组编排参数 + 推荐的风格 skill */
  const applyPreset = (p: Preset) => {
    setActivePreset(p.id);
    const styleName = p.skills.find((s) => s !== "搜索" && s !== "图表");
    onParamsChange({ ...p.params, skillId: styleName ? (SKILL_ID_BY_NAME[styleName] ?? "") : "" });
  };

  /** 基于当前默认预设复制一份到自定义组 */
  const duplicatePreset = () => {
    const src = PRESETS.find((p) => p.id === activePreset) ?? PRESETS[0];
    const copy: Preset = {
      ...src,
      id: `custom-${Date.now()}`,
      trust: "user",
      name: `${src.name} 副本`,
      badge: undefined,
    };
    setCustomPresets((cs) => [...cs, copy]);
    applyPreset(copy);
  };

  const removeCustomPreset = (id: string) => {
    setCustomPresets((cs) => cs.filter((c) => c.id !== id));
    if (activePreset === id) applyPreset(PRESETS[0]);
  };
  const addModel = () => {
    if (!newModelId.trim()) return;
    onModelsChange([
      ...models,
      {
        id: `m${Date.now()}`,
        name: newDisplayName.trim() || newModelId.trim(),
        modelId: newModelId.trim(),
        provider: newProvider,
        removable: true,
      },
    ]);
    setAddingProvider(false);
    setNewDisplayName("");
  };

  /** 按 provider 分组（DSH ModelDirectory：provider 行 → 卡片内模型列表） */
  const providerGroups = useMemo(() => groupModelsByProvider(models), [models]);

  /** 展开/收起 provider 编辑卡片（一次只展开一张，DSH 同款） */
  const toggleProvider = (provider: string) => {
    setEditingProvider((cur) => (cur === provider ? null : provider));
    setEditingModel(null);
    setAddingProvider(false);
  };

  /** 卡片内模型行内编辑：打开时预填当前值 */
  const toggleModelEdit = (m: ModelItem) => {
    if (editingModel === m.id) {
      setEditingModel(null);
      return;
    }
    setEditModelId(m.modelId);
    setEditModelName(m.name);
    setEditingModel(m.id);
  };

  // ESC 关闭设置模态
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const THEMES = [
    { id: "dark", label: "暗" },
    { id: "light", label: "亮" },
    { id: "system", label: "系统" },
  ];

  return (
    <>
      <button className="settings-btn" onClick={() => setOpen(true)} title="设置">
        <IconGear size={15} /> <span className="btn-label">设置</span>
      </button>

      {open && (
        <div className="drawer-overlay" onClick={() => setOpen(false)}>
          <div className="settings-drawer" onClick={(e) => e.stopPropagation()}>
            <div className="drawer-nav">
              <div className="drawer-nav-title">设置</div>
              <div className="drawer-nav-list">
                {SETTINGS_TABS.map((t) => {
                  const Icon = t.icon;
                  return (
                    <button key={t.id} className={`drawer-nav-cell ${tab === t.id ? "active" : ""}`} onClick={() => setTab(t.id)}>
                      <Icon size={15} className="drawer-nav-icon" />
                      <span className="drawer-nav-label">{t.label}</span>
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="drawer-content">
              {/* 内容区 header 行（DSH：54px，右侧关闭按钮） */}
              <div className="drawer-header">
                <div className="drawer-actions">
                  <button className="drawer-close" onClick={() => setOpen(false)} title="关闭">
                    <IconClose size={15} />
                  </button>
                </div>
              </div>

              <div className="drawer-options">
                {/* ── Agent 预设（DSH AgentPresetSection：卡片网格） ── */}
                {tab === "preset" && (
                  <>
                    <h2 className="setting-page-title">Agent 预设</h2>
                    <p className="setting-page-intro">选择一个预设作为默认 Agent——预设推荐 skill 组合并设定编排参数</p>
                    {(["system", "user"] as const).map((trust) => {
                      const group = [...PRESETS, ...customPresets].filter((p) => p.trust === trust);
                      const isCustom = trust === "user";
                      if (group.length === 0 && !isCustom) return null;
                      return (
                        <div key={trust} className="preset-group">
                          <div className="setting-section-title">{isCustom ? "自定义" : "内置"}</div>
                          {group.length > 0 && (
                            <ul className="preset-cards">
                              {group.map((p) => (
                                <li key={p.id} className={`preset-card ${activePreset === p.id ? "active" : ""}`}>
                                  <button
                                    className="preset-card-main"
                                    disabled={activePreset === p.id}
                                    onClick={() => applyPreset(p)}
                                  >
                                    <div className="preset-card-head">
                                      <span className="preset-card-name">{p.name}</span>
                                      {p.badge && <span className="preset-badge">{p.badge}</span>}
                                      {activePreset === p.id && <span className="preset-inuse">使用中</span>}
                                    </div>
                                    <span className="preset-card-desc">{p.desc}</span>
                                    <div className="preset-card-skills">
                                      {p.skills.map((s) => (
                                        <span key={s} className="preset-skill-chip">{s}</span>
                                      ))}
                                    </div>
                                    <div className="preset-card-params">
                                      <span>步数 {p.params.agentSteps}</span>
                                      <span>搜索 ×{p.params.searchMax}</span>
                                      <span>{p.params.searchEnabled ? "联网" : "离线"}</span>
                                      <span>¥{p.params.budget}</span>
                                    </div>
                                  </button>
                                  {isCustom && (
                                    <button
                                      className="preset-card-remove"
                                      title="移除预设"
                                      onClick={() => removeCustomPreset(p.id)}
                                    >
                                      <IconClose size={13} />
                                    </button>
                                  )}
                                </li>
                              ))}
                            </ul>
                          )}
                          {isCustom && (
                            <button className="preset-creator-btn" onClick={duplicatePreset}>
                              <IconPlus size={14} /> 基于内置新建
                            </button>
                          )}
                        </div>
                      );
                    })}
                  </>
                )}

                {/* ── 外观（DSH AppearanceRow：主题卡片方块 + 语言行） ── */}
                {tab === "appearance" && (
                  <>
                    <h2 className="setting-page-title">外观</h2>
                    <p className="setting-page-intro">界面主题与语言</p>
                    <div className="appearance-group">
                      <div className="appearance-title">主题</div>
                      <div className="appearance-cube-row">
                        {THEMES.map((t) => (
                          <button
                            key={t.id}
                            className={`appearance-cube ${theme === t.id ? "selected" : ""}`}
                            onClick={() => setTheme(t.id as "dark" | "light" | "system")}
                          >
                            {t.label}
                          </button>
                        ))}
                      </div>
                    </div>
                    <div className="appearance-group">
                      <div className="appearance-title">语言</div>
                      <div className="language-row">
                        <div className="language-row-text">
                          <span className="language-row-title">界面语言</span>
                        </div>
                        <button
                          ref={langDrop.triggerRef}
                          className="language-selector"
                          disabled
                          title="界面语言切换开发中"
                          onClick={langDrop.toggle}
                        >
                          {lang}
                          <IconChevronDown size={13} />
                        </button>
                      </div>
                    </div>
                  </>
                )}

                {/* ── 模型（DSH ModelsSection：一行一个 provider，卡片内管理模型 + 凭证） ── */}
                {tab === "models" && (
                  <>
                    <h2 className="model-page-title">模型</h2>
                    <p className="model-page-intro">每个提供方独立配置 Key 与模型——选哪个模型的模型，就用哪个提供方的凭证</p>

                    <ul className="model-rows">
                      {providerGroups.map((g) => {
                        const creds = credsOf(g.provider);
                        return (
                          <li key={g.provider} className={`model-row-card ${editingProvider === g.provider ? "expanded" : ""}`}>
                            <div className="model-row-head" onClick={() => toggleProvider(g.provider)}>
                              <span className="model-row-identity">
                                <span className="model-row-name">{g.provider}</span>
                                <span className="model-row-count">{g.models.length} 个模型</span>
                                <span
                                  className={`credential-dot ${creds.apiKey ? "configured" : "missing"}`}
                                  title={creds.apiKey ? "已配置该提供方的 Key" : "未配置 Key（用后端 .env 或留空）"}
                                />
                              </span>
                              <span className="model-row-actions" onClick={(e) => e.stopPropagation()}>
                                <button className="btn-secondary" onClick={() => toggleProvider(g.provider)}>
                                  {editingProvider === g.provider ? "收起" : "编辑"}
                                </button>
                              </span>
                            </div>

                            {/* 展开卡片：凭证 + 模型列表（DSH ProviderEditor 结构） */}
                            {editingProvider === g.provider && (
                              <div className="model-editor">
                                <div className="model-editor-header">
                                  <span className="model-editor-title">{g.provider}</span>
                                  <span className="model-editor-route">{g.models.length} 个模型</span>
                                </div>

                                {/* 该提供方的连接凭证（独立；已填只显示掩码，不可复制） */}
                                <div className="model-field">
                                  <label className="model-field-label">API Key</label>
                                  {editingKeyFor === g.provider ? (
                                    <div className="credential-edit-row">
                                      <input
                                        className="setting-input"
                                        type="password"
                                        placeholder="sk-...（输入新 Key）"
                                        value={keyInput}
                                        onChange={(e) => setKeyInput(e.target.value)}
                                        autoFocus
                                      />
                                      <button className="btn-secondary" onClick={cancelEditKey}>取消</button>
                                      <button className="btn-primary" onClick={() => saveKey(g.provider)} disabled={!keyInput.trim()}>保存</button>
                                    </div>
                                  ) : creds.apiKey ? (
                                    <div className="credential-edit-row">
                                      <span className="credential-mask" title="已配置，Key 不可查看">
                                        {`sk-••••••••${creds.apiKey.length > 4 ? creds.apiKey.slice(-4) : ""}`}
                                      </span>
                                      <button className="btn-secondary" onClick={() => startEditKey(g.provider)}>更换 Key</button>
                                    </div>
                                  ) : (
                                    <div className="credential-edit-row">
                                      <input
                                        className="setting-input"
                                        type="password"
                                        placeholder="sk-...（留空则用后端 .env 配置）"
                                        value={keyInput}
                                        onChange={(e) => setKeyInput(e.target.value)}
                                      />
                                      <button className="btn-primary" onClick={() => saveKey(g.provider)} disabled={!keyInput.trim()}>保存</button>
                                    </div>
                                  )}
                                </div>
                                <div className="model-field">
                                  <label className="model-field-label">API 地址</label>
                                  <input
                                    className="setting-input"
                                    placeholder={PROVIDERS[g.provider]?.base || "https://api.example.com"}
                                    value={creds.apiBase}
                                    onChange={(e) => saveBase(g.provider, e.target.value)}
                                  />
                                </div>

                                <div className="model-editor-models">
                                  {g.models.map((m) => (
                                    <div key={m.id} className="provider-model-row">
                                      {editingModel === m.id ? (
                                        <>
                                          <div className="provider-model-fields">
                                            <input
                                              className="setting-input"
                                              placeholder="显示名称"
                                              value={editModelName}
                                              onChange={(e) => setEditModelName(e.target.value)}
                                            />
                                            <input
                                              className="setting-input"
                                              placeholder="模型 ID"
                                              value={editModelId}
                                              onChange={(e) => setEditModelId(e.target.value)}
                                            />
                                          </div>
                                          <span className="provider-model-actions">
                                            <button className="btn-secondary" onClick={() => setEditingModel(null)}>取消</button>
                                            <button className="btn-primary" onClick={() => saveEdit(m.id)}>保存</button>
                                          </span>
                                        </>
                                      ) : (
                                        <>
                                          <span className="provider-model-info">
                                            <span className="provider-model-name">{m.name}</span>
                                            <span className="provider-model-id">{m.modelId}</span>
                                            {!m.removable && <span className="model-row-provider">内置</span>}
                                          </span>
                                          <span className="provider-model-actions">
                                            <button className="btn-secondary" onClick={() => toggleModelEdit(m)}>编辑</button>
                                            {m.removable && (
                                              <button className="btn-danger" onClick={() => removeModel(m.id)}>删除</button>
                                            )}
                                          </span>
                                        </>
                                      )}
                                    </div>
                                  ))}
                                </div>
                                <div className="model-editor-add-model">
                                  <button className="model-add-btn" onClick={() => { setNewProvider(g.provider); setNewModelId(""); setNewDisplayName(""); setAddingProvider(true); }}>
                                    <IconPlus size={14} /> 添加模型到 {g.provider}
                                  </button>
                                </div>
                              </div>
                            )}
                          </li>
                        );
                      })}
                    </ul>

                    {/* ── 添加提供方（DSH dormant-provider select 卡片） ── */}
                    <div className="model-add-block">
                      {addingProvider ? (
                        <div className="model-add-card">
                          <div className="model-editor-header">
                            <span className="model-editor-title">添加模型</span>
                            {editingProvider && <span className="model-editor-route">归属 {editingProvider}</span>}
                          </div>
                          {!editingProvider && (
                            <div className="model-field">
                              <label className="model-field-label">协议</label>
                              <select className="model-select-input" value={newProvider} onChange={(e) => pickProvider(e.target.value)}>
                                {Object.keys(PROVIDERS).map((p) => (
                                  <option key={p} value={p}>{p}</option>
                                ))}
                              </select>
                            </div>
                          )}
                          <div className="model-field">
                            <label className="model-field-label">模型 ID</label>
                            <input className="setting-input" placeholder="如 gpt-4o / claude-3-5-sonnet" value={newModelId} onChange={(e) => setNewModelId(e.target.value)} />
                          </div>
                          <div className="model-field">
                            <label className="model-field-label">显示名称</label>
                            <input className="setting-input" placeholder="如 OpenAI" value={newDisplayName} onChange={(e) => setNewDisplayName(e.target.value)} />
                          </div>
                          {/* 新提供方没有配过 Key → 添加时顺带配置（DSH 创建卡片同款） */}
                          {!credsOf(newProvider).apiKey && (
                            <div className="model-field">
                              <label className="model-field-label">该提供方的 API Key</label>
                              <div className="credential-edit-row">
                                <input
                                  className="setting-input"
                                  type="password"
                                  placeholder={`sk-...（${newProvider} 的 Key）`}
                                  value={keyInput}
                                  onChange={(e) => setKeyInput(e.target.value)}
                                />
                                {keyInput.trim() && (
                                  <button className="btn-primary" onClick={() => saveKey(newProvider)}>保存 Key</button>
                                )}
                              </div>
                            </div>
                          )}
                          <div className="model-editor-actions">
                            <button className="btn-secondary" onClick={() => setAddingProvider(false)}>取消</button>
                            <button className="btn-primary" onClick={addModel}>保存</button>
                          </div>
                        </div>
                      ) : (
                        <div className="model-add-actions">
                          <button
                            className="model-add-btn"
                            onClick={() => { setAddingProvider(true); setEditingProvider(null); setEditingModel(null); }}
                          >
                            <IconPlus size={14} /> 添加模型
                          </button>
                        </div>
                      )}
                    </div>

                    <div className="setting-section-title">生成参数</div>
                    <SettingRow title="Agent 步数" desc="Agent 自主决策的最大循环步数">
                      <input className="setting-input" type="number" value={params.agentSteps} onChange={(e) => onParamsChange({ ...params, agentSteps: parseInt(e.target.value) || 0 })} />
                    </SettingRow>
                    <SettingRow title="LLM 步数" desc="每类内部重试的上限：渲染自检 / 换词 / 审查回退">
                      <input className="setting-input" type="number" value={params.llmSteps} onChange={(e) => onParamsChange({ ...params, llmSteps: parseInt(e.target.value) || 0 })} />
                    </SettingRow>
                    <SettingRow title="单次预算" desc="单次生成成本上限（元）">
                      <input className="setting-input" type="number" value={params.budget} onChange={(e) => onParamsChange({ ...params, budget: parseFloat(e.target.value) || 0 })} />
                    </SettingRow>
                    <SettingRow title="搜索次数上限" desc="素材检索的最多轮数">
                      <input className="setting-input" type="number" value={params.searchMax} onChange={(e) => onParamsChange({ ...params, searchMax: parseInt(e.target.value) || 0 })} />
                    </SettingRow>
                    <SettingRow title="联网搜索" desc="允许 Lumen 联网检索素材">
                      <button className={`toggle ${params.searchEnabled ? "on" : ""}`} onClick={() => onParamsChange({ ...params, searchEnabled: !params.searchEnabled })} />
                    </SettingRow>
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
