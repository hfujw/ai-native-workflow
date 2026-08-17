import { useEffect, useMemo, useState } from "react";
import type { ComponentType } from "react";
import { useDropdown } from "../hooks/useDropdown";
import { usePersistentState } from "../hooks/usePersistentState";
import { confirmDialog } from "../lib/confirm";
import { resolvePresetParams, type Preset } from "../lib/presets";
import {
  fetchSkills,
  groupModelsByProvider,
  type GenParams,
  type ModelItem,
  type ProviderCreds,
  type SearchService,
  type Skill as ApiSkill,
} from "../lib/api";
import type { IconProps } from "./icons";
import {
  IconChevronDown,
  IconClose,
  IconCpu,
  IconGear,
  IconPen,
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

const PRESETS: Preset[] = [
  {
    id: "storyteller", name: "知识探险家", badge: "官方", trust: "system",
    desc: "为故事型主题打造编辑级杂志长页：先搜索素材，再用多角度创意脑发散，最后杂志排版。适合历史、人物、深度话题——素材充足时尽量考证，讲得生动",
    skills: ["杂志长图"],
    params: { agentSteps: 20, llmSteps: 10, searchMax: 8, searchEnabled: true, creativeSwarmSize: 3 },
  },
  {
    id: "alchemist", name: "数据炼金师", badge: "官方", trust: "system",
    desc: "把数据变成视觉叙事：多搜数字素材，数据型创意脑打头，图表信息图呈现。适合年度报告、产品对比、数据话题——数字一目了然",
    skills: ["信息图"],
    params: { agentSteps: 15, llmSteps: 8, searchMax: 5, searchEnabled: true, creativeSwarmSize: 4 },
  },
  {
    id: "pixelist", name: "像素时光机", badge: "官方", trust: "system",
    desc: "游戏化怀旧呈现：像素风 + 最多创意脑发散（人海战术），做出有『游戏感』的页面。适合游戏、复古、趣味话题——效果最花哨但也最烧 token",
    skills: ["像素风"],
    params: { agentSteps: 25, llmSteps: 12, searchMax: 4, searchEnabled: true, creativeSwarmSize: 5 },
  },
  {
    id: "curator", name: "极简策展人", badge: "官方", trust: "system",
    desc: "不联网，靠自身知识做安静的知识卡片——极简克制、留白呼吸。适合快问快答、概念解释——最省 token 的预设",
    skills: ["杂志长图"],
    params: { agentSteps: 10, llmSteps: 6, searchMax: 2, searchEnabled: false, creativeSwarmSize: 3 },
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
  searchServices,
  onSearchServicesChange,
  activeSearchService,
  onActiveSearchServiceChange,
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
  /** 搜索服务（受控：和模型选择一样——用户选服务 + 独立 Key/地址） */
  searchServices: SearchService[];
  onSearchServicesChange: (s: SearchService[]) => void;
  activeSearchService: string;
  onActiveSearchServiceChange: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState("preset");
  const langDrop = useDropdown();

  // 持久化：预设（刷新不丢）
  const [lang] = useState("中文"); // 界面语言切换开发中（禁用态）
  const [activePreset, setActivePreset] = usePersistentState("lumen.preset", "storyteller");
  const [customPresets, setCustomPresets] = usePersistentState<Preset[]>("lumen.customPresets", []);
  // 正在编辑的自定义预设 id（null=无；展开行内编辑表单）
  const [editingPreset, setEditingPreset] = useState<string | null>(null);
  // 编辑草稿（打开时从预设拷贝，保存时写回）
  const [editPresetDraft, setEditPresetDraft] = useState<Preset | null>(null);
  // 预设详情弹窗（内置/自定义都能看——"我没法查看详情我咋用"）
  const [presetDetail, setPresetDetail] = useState<Preset | null>(null);
  // 全部可用 skill + tool（自建预设技能组合的下拉数据源——和后端技能系统对齐）
  const [allSkills, setAllSkills] = useState<ApiSkill[]>([]);
  useEffect(() => {
    fetchSkills()
      .then((data) => setAllSkills(data.skills ?? []))
      .catch(() => setAllSkills([])); // 后端未启动时留空，不影响其他功能
  }, []);

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
  const [newModelId, setNewModelId] = useState("deepseek-v4-flash");
  const [newDisplayName, setNewDisplayName] = useState("");

  // 每个 provider 的凭证编辑态（正在换 key 的 provider + 新 key 输入；绝不预填旧值）
  const [editingKeyFor, setEditingKeyFor] = useState<string | null>(null);
  const [keyInput, setKeyInput] = useState("");
  // 搜索服务编辑态（和模型行一样：展开卡片管理 Key/地址；添加自定义服务）
  const [editingSearch, setEditingSearch] = useState<string | null>(null);
  const [editingSearchKey, setEditingSearchKey] = useState<string | null>(null);
  const [searchKeyInput, setSearchKeyInput] = useState("");
  const [addingSearch, setAddingSearch] = useState(false);
  const [newSearchName, setNewSearchName] = useState("");
  const [newSearchBase, setNewSearchBase] = useState("https://api.tavily.com");
  const [newSearchKey, setNewSearchKey] = useState("");

  const saveSearchKey = (id: string) => {
    const v = searchKeyInput.trim();
    if (!v) return;
    onSearchServicesChange(
      searchServices.map((s) => (s.id === id ? { ...s, apiKey: v } : s))
    );
    setEditingSearchKey(null);
    setSearchKeyInput("");
  };
  const saveSearchBase = (id: string, base: string) => {
    onSearchServicesChange(
      searchServices.map((s) => (s.id === id ? { ...s, baseUrl: base } : s))
    );
  };
  const removeSearchService = async (id: string) => {
    // ⑤ 删除零确认 → 加确认
    const ok = await confirmDialog("确定删除这个搜索服务？");
    if (!ok) return;
    const next = searchServices.filter((s) => s.id !== id);
    onSearchServicesChange(next);
    if (activeSearchService === id) {
      onActiveSearchServiceChange(next[0]?.id ?? "");
    }
  };
  const addSearchService = () => {
    if (!newSearchName.trim()) return;
    const id = `search-${Date.now()}`;
    onSearchServicesChange([
      ...searchServices,
      { id, name: newSearchName.trim(), apiKey: newSearchKey.trim(), baseUrl: newSearchBase.trim() || "https://api.tavily.com", removable: true },
    ]);
    setAddingSearch(false);
    setNewSearchName("");
    setNewSearchBase("https://api.tavily.com");
    setNewSearchKey("");
  };

  /** 取某 provider 的凭证（无则返回空） */
  const credsOf = (provider: string): ProviderCreds =>
    providerCreds[provider] ?? { apiKey: "", apiBase: "" };

  const PROVIDERS: Record<string, { base: string; defaultModel: string }> = {
    DeepSeek: { base: "https://api.deepseek.com", defaultModel: "deepseek-v4-flash" },
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
  const removeModel = async (id: string) => {
    // ⑤ 删除零确认 → 加确认
    const ok = await confirmDialog("确定删除这个模型？");
    if (!ok) return;
    onModelsChange(models.filter((m) => m.id !== id));
  };

  /** 应用预设：设为默认 + 套用一组编排参数 + 推荐的风格 skill（核心计算抽到 lib/presets）。 */
  const applyPreset = (p: Preset) => {
    setActivePreset(p.id);
    onParamsChange(resolvePresetParams(p, allSkills));
  };

  /** 自建预设：从空白开始（不是复制内置）——自己起名、选技能、定参数 */
  const createPreset = () => {
    const draft: Preset = {
      id: `custom-${Date.now()}`,
      name: "",
      trust: "user",
      desc: "",
      skills: [],
      params: { agentSteps: 20, llmSteps: 10, searchMax: 8, searchEnabled: true, creativeSwarmSize: 3 },
    };
    setEditPresetDraft(draft);
    setEditingPreset(draft.id); // 占位 id：保存时才真正写入列表
  };

  const removeCustomPreset = async (id: string) => {
    // ⑤ 删除零确认 → 加确认
    const ok = await confirmDialog("确定删除这个自定义预设？");
    if (!ok) return;
    setCustomPresets((cs) => cs.filter((c) => c.id !== id));
    if (activePreset === id) applyPreset(PRESETS[0]);
    if (editingPreset === id) setEditingPreset(null);
  };

  /** 打开自定义预设编辑：从预设拷贝草稿（改的是副本，取消不丢原数据） */
  const startEditPreset = (p: Preset) => {
    setEditPresetDraft(JSON.parse(JSON.stringify(p)) as Preset);
    setEditingPreset(p.id);
  };
  /** 技能组合 chips 切换（编辑草稿内） */
  const toggleDraftSkill = (skill: string) => {
    if (!editPresetDraft) return;
    const has = editPresetDraft.skills.includes(skill);
    setEditPresetDraft({
      ...editPresetDraft,
      skills: has
        ? editPresetDraft.skills.filter((s) => s !== skill)
        : [...editPresetDraft.skills, skill],
    });
  };
  /** 保存预设：新建（草稿 id 不在列表）追加，编辑写回；应用后设为默认 */
  const savePresetEdit = () => {
    if (!editPresetDraft || !editingPreset) return;
    const name = editPresetDraft.name.trim();
    if (!name) return;
    const final = { ...editPresetDraft, name };
    const exists = customPresets.some((c) => c.id === editingPreset);
    setCustomPresets((cs) =>
      exists ? cs.map((c) => (c.id === editingPreset ? final : c)) : [...cs, final]
    );
    applyPreset(final); // 新建/编辑后直接设为默认并应用参数
    setEditingPreset(null);
    setEditPresetDraft(null);
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
        <>
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
                    <p className="setting-page-intro">选择一个预设作为默认 Agent——预设推荐 skill 组合并设定编排参数；自定义预设可自建、可编辑</p>
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
                                    </div>
                                  </button>
                                  {/* 详情：内置/自定义都能看——"我没法查看详情我咋用" */}
                                  <button
                                    className="preset-card-edit"
                                    title="查看详情"
                                    onClick={(e) => { e.stopPropagation(); setPresetDetail(p); }}
                                  >
                                    详情
                                  </button>
                                  {isCustom && (
                                    <>
                                      <button
                                        className="preset-card-edit"
                                        title="编辑预设"
                                        onClick={() => startEditPreset(p)}
                                      >
                                        <IconPen size={13} />
                                      </button>
                                      <button
                                        className="preset-card-remove"
                                        title="移除预设"
                                        onClick={() => removeCustomPreset(p.id)}
                                      >
                                        <IconClose size={13} />
                                      </button>
                                    </>
                                  )}
                                </li>
                              ))}
                            </ul>
                          )}
                          {isCustom && (
                            <button className="preset-creator-btn" onClick={createPreset}>
                              <IconPlus size={14} /> 自建预设
                            </button>
                          )}
                        </div>
                      );
                    })}

                    {/* ── 自建/编辑表单（空白草稿 = 自建；带数据 = 编辑） ── */}
                    {editingPreset && editPresetDraft && (
                      <div className="preset-editor">
                        <div className="model-editor-header">
                          <span className="model-editor-title">
                            {customPresets.some((c) => c.id === editingPreset) ? "编辑预设" : "自建预设"}
                          </span>
                        </div>
                        <div className="model-field">
                          <label className="model-field-label">名称</label>
                          <input
                            className="setting-input"
                            placeholder="给我的预设起个名"
                            value={editPresetDraft.name}
                            onChange={(e) => setEditPresetDraft({ ...editPresetDraft, name: e.target.value })}
                            autoFocus
                          />
                        </div>
                        <div className="model-field">
                          <label className="model-field-label">描述</label>
                          <input
                            className="setting-input"
                            placeholder="这个预设擅长什么（一句话）"
                            value={editPresetDraft.desc}
                            onChange={(e) => setEditPresetDraft({ ...editPresetDraft, desc: e.target.value })}
                          />
                        </div>
                        <div className="model-field">
                          <label className="model-field-label">技能组合</label>
                          {/* 下拉列出后端全部 skill+tool（风格/工具两组）；已选显示为可移除 chips */}
                          {allSkills.length === 0 ? (
                            <span className="model-field-hint">暂无可用技能（后端未启动？）</span>
                          ) : (
                            <select
                              className="model-select-input"
                              value=""
                              onChange={(e) => {
                                const name = e.target.value;
                                if (name && !editPresetDraft.skills.includes(name)) {
                                  setEditPresetDraft({
                                    ...editPresetDraft,
                                    skills: [...editPresetDraft.skills, name],
                                  });
                                }
                              }}
                            >
                              <option value="">+ 添加技能…</option>
                              {(["风格", "工具"] as const).map((t) => (
                                <optgroup key={t} label={t}>
                                  {allSkills
                                    .filter((s) => s.type === t)
                                    .filter((s) => !editPresetDraft.skills.includes(s.name))
                                    .map((s) => (
                                      <option key={s.id} value={s.name}>{s.name}</option>
                                    ))}
                                </optgroup>
                              ))}
                            </select>
                          )}
                          {editPresetDraft.skills.length > 0 && (
                            <div className="preset-skill-picker">
                              {editPresetDraft.skills.map((name) => (
                                <button
                                  key={name}
                                  className="preset-skill-chip on"
                                  onClick={() => toggleDraftSkill(name)}
                                  title="点击移除"
                                >
                                  {name} ✕
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                        <div className="preset-editor-params">
                          <label className="model-field-label">编排参数</label>
                          <div className="preset-param-grid">
                            <div className="model-field">
                              <label className="model-field-label">Agent 步数</label>
                              <input
                                className="setting-input"
                                type="number"
                                min={1}
                                max={100}
                                placeholder="1–100，默认 20"
                                value={editPresetDraft.params.agentSteps}
                                onChange={(e) =>
                                  setEditPresetDraft({
                                    ...editPresetDraft,
                                    params: { ...editPresetDraft.params, agentSteps: parseInt(e.target.value) || 0 },
                                  })
                                }
                              />
                            </div>
                            <div className="model-field">
                              <label className="model-field-label">LLM 步数</label>
                              <input
                                className="setting-input"
                                type="number"
                                min={1}
                                max={100}
                                placeholder="1–100，默认 10"
                                value={editPresetDraft.params.llmSteps}
                                onChange={(e) =>
                                  setEditPresetDraft({
                                    ...editPresetDraft,
                                    params: { ...editPresetDraft.params, llmSteps: parseInt(e.target.value) || 0 },
                                  })
                                }
                              />
                            </div>
                            <div className="model-field">
                              <label className="model-field-label">搜索次数</label>
                              <input
                                className="setting-input"
                                type="number"
                                min={0}
                                max={20}
                                placeholder="0–20，默认 8"
                                value={editPresetDraft.params.searchMax}
                                onChange={(e) =>
                                  setEditPresetDraft({
                                    ...editPresetDraft,
                                    params: { ...editPresetDraft.params, searchMax: parseInt(e.target.value) || 0 },
                                  })
                                }
                              />
                            </div>
                            <div className="model-field">
                              <label className="model-field-label">创意脑数</label>
                              <input
                                className="setting-input"
                                type="number"
                                min={1}
                                max={6}
                                placeholder="1–6，默认 3"
                                value={editPresetDraft.params.creativeSwarmSize}
                                onChange={(e) =>
                                  setEditPresetDraft({
                                    ...editPresetDraft,
                                    params: { ...editPresetDraft.params, creativeSwarmSize: parseInt(e.target.value) || 3 },
                                  })
                                }
                              />
                            </div>
                          </div>
                          <label className="preset-offline-toggle">
                            <button
                              className={`toggle ${editPresetDraft.params.searchEnabled ? "on" : ""}`}
                              onClick={() =>
                                setEditPresetDraft({
                                  ...editPresetDraft,
                                  params: { ...editPresetDraft.params, searchEnabled: !editPresetDraft.params.searchEnabled },
                                })
                              }
                            />
                            {editPresetDraft.params.searchEnabled ? "联网搜索" : "离线（不联网）"}
                          </label>
                        </div>
                        <div className="model-editor-actions">
                          <button
                            className="btn-secondary"
                            onClick={() => { setEditingPreset(null); setEditPresetDraft(null); }}
                          >
                            取消
                          </button>
                          <button className="btn-primary" onClick={savePresetEdit} disabled={!editPresetDraft.name.trim()}>
                            保存
                          </button>
                        </div>
                      </div>
                    )}
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

                    {/* ── 搜索服务（和模型选择一样：用户选服务 + 独立 Key/地址；没配 = 不联网） ── */}
                    <div className="credential-block">
                      <div className="setting-section-title">搜索服务</div>
                      <p className="search-svc-intro">联网搜索用的服务——和模型一样：选哪个服务，就用哪个服务的 Key 与地址。没配置 Key = 不联网。</p>
                      <div className="search-svc-list">
                        {searchServices.map((s) => (
                          <div key={s.id} className={`search-svc-row ${activeSearchService === s.id ? "active" : ""}`}>
                            <div className="search-svc-head">
                              <span className="search-svc-name">
                                {s.name}
                                {!s.removable && <span className="model-row-provider">内置</span>}
                              </span>
                              <span
                                className={`credential-dot ${s.apiKey ? "configured" : "missing"}`}
                                title={s.apiKey ? "已配置 Key" : "未配置 Key——该服务不可用"}
                              />
                              <span className="model-row-actions">
                                {activeSearchService === s.id ? (
                                  s.apiKey ? (
                                    <span className="preset-inuse">使用中</span>
                                  ) : (
                                    <span className="search-svc-unconfigured">未配置 Key——不联网</span>
                                  )
                                ) : (
                                  <button
                                    className="btn-secondary"
                                    onClick={() => onActiveSearchServiceChange(s.id)}
                                    title={s.apiKey ? "切换到此搜索服务" : "该服务未配置 Key，切换后联网搜索不可用"}
                                  >
                                    设为当前
                                  </button>
                                )}
                                <button className="btn-secondary" onClick={() => setEditingSearch(editingSearch === s.id ? null : s.id)}>
                                  {editingSearch === s.id ? "收起" : "编辑"}
                                </button>
                                {s.removable && (
                                  <button className="btn-danger" onClick={() => removeSearchService(s.id)}>删除</button>
                                )}
                              </span>
                            </div>

                            {editingSearch === s.id && (
                              <div className="search-svc-editor">
                                <div className="model-field">
                                  <label className="model-field-label">API Key（联网搜索用）</label>
                                  {editingSearchKey === s.id ? (
                                    <div className="credential-edit-row">
                                      <input
                                        className="setting-input"
                                        type="password"
                                        placeholder={`${s.name} 的 Key`}
                                        value={searchKeyInput}
                                        onChange={(e) => setSearchKeyInput(e.target.value)}
                                        autoFocus
                                      />
                                      <button className="btn-secondary" onClick={() => setEditingSearchKey(null)}>取消</button>
                                      <button className="btn-primary" onClick={() => saveSearchKey(s.id)} disabled={!searchKeyInput.trim()}>保存</button>
                                    </div>
                                  ) : s.apiKey ? (
                                    <div className="credential-edit-row">
                                      <span className="credential-mask" title="已配置，Key 不可查看">
                                        {`••••••••${s.apiKey.length > 4 ? s.apiKey.slice(-4) : ""}`}
                                      </span>
                                      <button className="btn-secondary" onClick={() => { setSearchKeyInput(""); setEditingSearchKey(s.id); }}>更换 Key</button>
                                    </div>
                                  ) : (
                                    <div className="credential-edit-row">
                                      <input
                                        className="setting-input"
                                        type="password"
                                        placeholder={`${s.name} 的 Key（没填 = 不联网）`}
                                        value={searchKeyInput}
                                        onChange={(e) => setSearchKeyInput(e.target.value)}
                                      />
                                      <button className="btn-primary" onClick={() => saveSearchKey(s.id)} disabled={!searchKeyInput.trim()}>保存</button>
                                    </div>
                                  )}
                                </div>
                                <div className="model-field">
                                  <label className="model-field-label">API 地址</label>
                                  <input
                                    className="setting-input"
                                    placeholder="https://api.tavily.com"
                                    value={s.baseUrl}
                                    onChange={(e) => saveSearchBase(s.id, e.target.value)}
                                  />
                                </div>
                              </div>
                            )}
                          </div>
                        ))}
                      </div>

                      {addingSearch ? (
                        <div className="search-svc-add-card">
                          <div className="model-field">
                            <label className="model-field-label">服务名称</label>
                            <input className="setting-input" placeholder="如 我的搜索网关" value={newSearchName} onChange={(e) => setNewSearchName(e.target.value)} />
                          </div>
                          <div className="model-field">
                            <label className="model-field-label">API 地址</label>
                            <input className="setting-input" placeholder="https://api.example.com" value={newSearchBase} onChange={(e) => setNewSearchBase(e.target.value)} />
                          </div>
                          <div className="model-field">
                            <label className="model-field-label">API Key</label>
                            <input className="setting-input" type="password" placeholder="该服务的 Key" value={newSearchKey} onChange={(e) => setNewSearchKey(e.target.value)} />
                          </div>
                          <div className="model-editor-actions">
                            <button className="btn-secondary" onClick={() => setAddingSearch(false)}>取消</button>
                            <button className="btn-primary" onClick={addSearchService} disabled={!newSearchName.trim()}>保存</button>
                          </div>
                        </div>
                      ) : (
                        <button className="model-add-btn" onClick={() => setAddingSearch(true)}>
                          <IconPlus size={14} /> 添加搜索服务
                        </button>
                      )}
                    </div>

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
                                  title={creds.apiKey ? "已配置该提供方的 Key" : "未配置 Key——该提供方不可用"}
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

                                {/* 该提供方的连接凭证（独立；已填只显示掩码，不可复制；没填 = 不可用） */}
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
                                    <div key={m.id}>
                                      {editingModel === m.id ? (
                                        /* 编辑态：垂直布局，独占整行（不再挤进横排 flex） */
                                        <div className="model-editor">
                                          <div className="model-field">
                                            <label className="model-field-label">显示名称</label>
                                            <input
                                              className="setting-input"
                                              placeholder="显示名称"
                                              value={editModelName}
                                              onChange={(e) => setEditModelName(e.target.value)}
                                            />
                                          </div>
                                          <div className="model-field">
                                            <label className="model-field-label">模型 ID</label>
                                            <input
                                              className="setting-input"
                                              placeholder="模型 ID（如 deepseek-v4-flash / gpt-4o）"
                                              value={editModelId}
                                              onChange={(e) => setEditModelId(e.target.value)}
                                            />
                                            <span className="model-field-hint">DeepSeek 官方模型名：deepseek-v4-flash / deepseek-v4-pro，填错 API 会拒绝</span>
                                          </div>
                                          <div className="model-editor-actions">
                                            <button className="btn-secondary" onClick={() => setEditingModel(null)}>取消</button>
                                            <button className="btn-primary" onClick={() => saveEdit(m.id)}>保存</button>
                                          </div>
                                        </div>
                                      ) : (
                                        <div className="provider-model-row">
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
                                        </div>
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
                            <input className="setting-input" placeholder="如 deepseek-v4-flash / gpt-4o" value={newModelId} onChange={(e) => setNewModelId(e.target.value)} />
                            <span className="model-field-hint">调用 API 用的精确模型名——DeepSeek 官方：deepseek-v4-flash / deepseek-v4-pro</span>
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
                    <SettingRow title="Agent 步数" desc="Agent 自主决策的最大循环步数（1–100，后端会钳制）">
                      <input className="setting-input" type="number" min={1} max={100} placeholder="默认 20" value={params.agentSteps} onChange={(e) => onParamsChange({ ...params, agentSteps: parseInt(e.target.value) || 0 })} />
                    </SettingRow>
                    <SettingRow title="LLM 步数" desc="每类内部重试上限：渲染自检 / 换词 / 审查回退（1–100）">
                      <input className="setting-input" type="number" min={1} max={100} placeholder="默认 10" value={params.llmSteps} onChange={(e) => onParamsChange({ ...params, llmSteps: parseInt(e.target.value) || 0 })} />
                    </SettingRow>
                    <SettingRow title="创意脑数量" desc="创作阶段并行发散的子脑数（1–6）——越高越多人海战术，越烧 token">
                      <input className="setting-input" type="number" min={1} max={6} placeholder="默认 3" value={params.creativeSwarmSize} onChange={(e) => onParamsChange({ ...params, creativeSwarmSize: parseInt(e.target.value) || 3 })} />
                    </SettingRow>
                    <SettingRow title="搜索次数上限" desc="素材检索的最多轮数（0–20，0=不联网）">
                      <input className="setting-input" type="number" min={0} max={20} placeholder="默认 8" value={params.searchMax} onChange={(e) => onParamsChange({ ...params, searchMax: parseInt(e.target.value) || 0 })} />
                    </SettingRow>
                    <SettingRow title="联网搜索" desc="允许 Lumen 联网检索素材（需在搜索服务里配置 Key）">
                      <button className={`toggle ${params.searchEnabled ? "on" : ""}`} onClick={() => onParamsChange({ ...params, searchEnabled: !params.searchEnabled })} />
                    </SettingRow>
                  </>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* 预设详情（内置/自定义都能看） */}
        {presetDetail && (
          <div className="confirm-overlay" onClick={() => setPresetDetail(null)}>
            <div className="preset-detail" onClick={(e) => e.stopPropagation()}>
              <div className="preset-detail-head">
                <span className="preset-card-name">{presetDetail.name}</span>
                {presetDetail.badge && <span className="preset-badge">{presetDetail.badge}</span>}
              </div>
              <p className="preset-card-desc">{presetDetail.desc}</p>

              <div className="preset-detail-block">
                <div className="preset-detail-title">技能组合</div>
                <div className="preset-card-skills">
                  {presetDetail.skills.length > 0 ? (
                    presetDetail.skills.map((s) => <span key={s} className="preset-skill-chip">{s}</span>)
                  ) : (
                    <span className="preset-detail-none">未选技能（LLM 自由发挥）</span>
                  )}
                </div>
              </div>

              <div className="preset-detail-block">
                <div className="preset-detail-title">编排参数</div>
                <ul className="preset-detail-list">
                  <li><b>Agent 步数 {presetDetail.params.agentSteps}</b> — 自主决策最大循环步数</li>
                  <li><b>LLM 步数 {presetDetail.params.llmSteps}</b> — 内部重试上限（渲染自检/换词/审查回退）</li>
                  <li><b>搜索 ×{presetDetail.params.searchMax}</b> — 素材检索轮数上限</li>
                  <li><b>创意脑 {presetDetail.params.creativeSwarmSize} 个</b> — 创作阶段并行发散子脑（人海战术）</li>
                  <li><b>{presetDetail.params.searchEnabled ? "联网搜索" : "离线"}</b> — {presetDetail.params.searchEnabled ? "可检索素材" : "只用自身知识，不联网"}</li>
                </ul>
              </div>

              <div className="preset-detail-actions">
                {activePreset !== presetDetail.id && (
                  <button className="btn-primary" onClick={() => { applyPreset(presetDetail); setPresetDetail(null); }}>
                    套用此预设
                  </button>
                )}
                {presetDetail.trust === "user" && (
                  <button className="btn-secondary" onClick={() => { startEditPreset(presetDetail); setPresetDetail(null); }}>
                    编辑
                  </button>
                )}
                <button className="btn-secondary" onClick={() => setPresetDetail(null)}>关闭</button>
              </div>
            </div>
          </div>
        )}
        </>
      )}
    </>
  );
}
