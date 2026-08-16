import { useEffect, useState } from "react";
import type { ComponentType } from "react";
import type { IconProps } from "./icons";
import {
  IconArrowLeft,
  IconChartBar,
  IconClose,
  IconGamepad,
  IconGrid,
  IconNewspaper,
  IconSearch,
  IconTrash,
} from "./icons";
import { deleteSkill, fetchSkills, installSkill } from "../lib/api";
import type { Skill as ApiSkill } from "../lib/api";
import { confirmDialog } from "../lib/confirm";
import { toast } from "../lib/toast";

type Skill = {
  id: string;
  name: string;
  type: string;
  desc: string;
  by: string;
  builtin: boolean;
  icon: ComponentType<IconProps>;
  /** skill 给 AI 的系统指令（详情页 Prompt 预览用） */
  prompt?: string;
};

/** skill id → 图标（未知 id 用网格兜底） */
const SKILL_ICONS: Record<string, ComponentType<IconProps>> = {
  pixel: IconGamepad,
  magazine: IconNewspaper,
  infographic: IconChartBar,
  search: IconSearch,
};

/** 系统人格 skill（编排/审查/批评家/迭代）——内置机制，不是用户可选的"风格"，不展示 */
const PERSONA_IDS = new Set(["core", "judge", "critique", "refine"]);

const TABS = ["精选", "我的 Skill", "分类"];
const CATEGORIES = ["全部", "风格", "工具"];

export default function SkillPage({
  onBack,
}: {
  onBack: () => void;
}) {
  const [tab, setTab] = useState("精选");
  const [search, setSearch] = useState("");
  const [detail, setDetail] = useState<Skill | null>(null);
  const [category, setCategory] = useState("全部");
  const [skills, setSkills] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  // 下载 skill 表单
  const [addingSkill, setAddingSkill] = useState(false);
  const [newSkillId, setNewSkillId] = useState("");
  const [newSkillMarkdown, setNewSkillMarkdown] = useState("");

  const reload = () => {
    setLoading(true);
    setFailed(false);
    fetchSkills()
      .then((data) => {
        setSkills(
          (data.skills ?? [])
            .filter((s) => !PERSONA_IDS.has(s.id)) // 系统人格不展示（不是可选的风格）
            .map((s: ApiSkill) => ({
              id: s.id,
              name: s.name,
              type: s.type,
              desc: s.desc,
              by: s.builtin ? "官方" : "自定义",
              builtin: s.builtin,
              icon: SKILL_ICONS[s.id] ?? IconGrid,
              prompt: s.prompt,
            }))
        );
        setLoading(false);
      })
      .catch(() => {
        setFailed(true);
        setLoading(false);
      });
  };

  useEffect(() => {
    reload();
  }, []);

  /** 删除自定义 skill（内置不可删；⑤ 删除零确认 → 加确认） */
  const removeSkill = async (id: string) => {
    const ok = await confirmDialog("确定删除这个 Skill？");
    if (!ok) return;
    try {
      await deleteSkill(id);
      if (detail?.id === id) setDetail(null); // 删除的是正在看的 → 回列表
      reload();
    } catch {
      /* 删除失败静默（内置/不存在等） */
    }
  };


  /** 下载/安装 skill（粘贴 SKILL.md 的 markdown）——使用靠预设 + LLM，这里只是"有可用 skill"的来源 */
  const addSkill = async () => {
    const id = newSkillId.trim();
    const md = newSkillMarkdown.trim();
    if (!id || !md) {
      toast("请填写 skill id 和 markdown 内容", "error");
      return;
    }
    try {
      const s = await installSkill(id, md);
      toast(`已下载「${s.name}」`);
      setAddingSkill(false);
      setNewSkillId("");
      setNewSkillMarkdown("");
      reload();
    } catch {
      toast("下载失败：id 非法或格式缺 name", "error");
    }
  };

  // ── 详情页 ──
  if (detail) {
    const DetailIcon = detail.icon;
    return (
      <div className="skill-page">
        <button className="back-btn" onClick={() => setDetail(null)}>
          <IconArrowLeft size={15} /> 返回
        </button>
        <div className="skill-detail">
          <div className="skill-detail-icon"><DetailIcon size={52} /></div>
          <h2 className="skill-detail-name">{detail.name}</h2>
          <div className="skill-detail-by">作者 {detail.by} · 类型：{detail.type}</div>
          <p className="skill-detail-desc">{detail.desc}</p>

          {/* Prompt 直接展示——Skill 的全部内容，不点不看 */}
          {detail.prompt && (
            <div className="skill-prompt-section">
              <div className="skill-prompt-label">Prompt（这段指令定义了这个 Skill）</div>
              <pre className="skill-prompt-code">{detail.prompt}</pre>
            </div>
          )}

          {/* 已有 skill 只有删除（"下载"是拿新的，在列表页） */}
          {!detail.builtin && (
            <div className="skill-actions">
              <button className="btn-danger" onClick={() => removeSkill(detail.id)}>
                <IconTrash size={14} /> 删除
              </button>
            </div>
          )}
        </div>
      </div>
    );
  }

  // ── 按标签取数据 ──
  let shown: Skill[] = [];
  if (tab === "精选") shown = skills.filter((s) => s.by === "官方");
  else if (tab === "分类") shown = skills.filter((s) => category === "全部" || s.type === category);
  // 我的 Skill：用户在对话里让 Lumen 下载的 skill 会出现在这里（接口后续接）

  if (tab !== "我的 Skill") {
    shown = shown.filter((s) => s.name.includes(search) || s.desc.includes(search));
  }

  return (
    <div className="skill-page">
      <div className="skill-topbar">
        <div className="skill-search">
          <IconSearch size={15} />
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="搜索 Skill..." />
        </div>
        <button className="download-skill-btn" onClick={() => setAddingSkill((v) => !v)}>
          {addingSkill ? "收起" : "下载新 Skill"}
        </button>
        <button className="back-btn" onClick={onBack}>
          <IconClose size={16} />
        </button>
      </div>

      {/* 下载 skill 表单：粘贴 SKILL.md 的 markdown */}
      {addingSkill && (
        <div className="skill-download-form">
          <div className="skill-download-hint">从 GitHub 或任意来源下载新 Skill——把它的 SKILL.md 内容粘贴到这里，填个唯一 id</div>
          <div className="model-field">
            <label className="model-field-label">Skill id（唯一，如 my-style）</label>
            <input className="setting-input" placeholder="my-style" value={newSkillId} onChange={(e) => setNewSkillId(e.target.value)} />
          </div>
          <div className="model-field">
            <label className="model-field-label">SKILL.md 内容（frontmatter 需含 name）</label>
            <textarea
              className="skill-download-textarea"
              placeholder={"---\nname: 我的风格\ntype: 风格\ndesc: 一句话\n---\n正文指令"}
              value={newSkillMarkdown}
              onChange={(e) => setNewSkillMarkdown(e.target.value)}
              rows={6}
            />
          </div>
          <div className="model-editor-actions">
            <button className="btn-secondary" onClick={() => setAddingSkill(false)}>取消</button>
            <button className="btn-primary" onClick={addSkill} disabled={!newSkillId.trim() || !newSkillMarkdown.trim()}>下载</button>
          </div>
        </div>
      )}

      <div className="skill-tabs">
        {TABS.map((t) => (
          <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>

      {tab === "分类" && (
        <div className="category-filter">
          {CATEGORIES.map((c) => (
            <button key={c} className={category === c ? "active" : ""} onClick={() => setCategory(c)}>{c}</button>
          ))}
        </div>
      )}

      {tab === "我的 Skill" ? (
        loading ? (
          <p className="skill-no-result">加载中…</p>
        ) : failed ? (
          <p className="skill-no-result">无法加载 Skill（后端未启动？）</p>
        ) : (() => {
          const mine = skills.filter((s) => !s.builtin);
          return mine.length === 0 ? (
            <div className="my-skills-empty">
              <div className="my-skills-icon"><IconGrid size={44} /></div>
              <p>还没有下载的 Skill</p>
              <p className="my-skills-hint">点上方"下载新 Skill"，从 GitHub 等来源粘贴 SKILL.md 添加；生成时用哪个风格由 Agent 预设与 LLM 自主选用</p>
              <button className="new-skill-btn" onClick={onBack}>返回对话</button>
            </div>
          ) : (
            <div className="skill-grid">
              {mine.map((s) => {
                const Icon = s.icon;
                return (
                  <div key={s.id} className="skill-card" onClick={() => setDetail(s)}>
                    <button
                      className="skill-card-remove"
                      title="删除 skill"
                      onClick={(e) => { e.stopPropagation(); removeSkill(s.id); }}
                    >
                      <IconTrash size={13} />
                    </button>
                    <div className="skill-card-icon"><Icon size={26} /></div>
                    <div className="skill-card-name">{s.name}</div>
                    <div className="skill-card-desc">{s.desc}</div>
                    <div className="skill-card-meta">
                      <span>作者 {s.by}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          );
        })()
      ) : (
        <>
          <div className="skill-section-title">{tab}</div>
          {loading ? (
            <p className="skill-no-result">加载中…</p>
          ) : failed ? (
            <p className="skill-no-result">无法加载 Skill（后端未启动？）</p>
          ) : shown.length === 0 ? (
            <p className="skill-no-result">没找到匹配的 Skill</p>
          ) : (
            <div className="skill-grid">
              {shown.map((s) => {
                const Icon = s.icon;
                return (
                  <div key={s.id} className="skill-card" onClick={() => setDetail(s)}>
                    <div className="skill-card-icon"><Icon size={26} /></div>
                    <div className="skill-card-name">{s.name}</div>
                    <div className="skill-card-desc">{s.desc}</div>
                    <div className="skill-card-meta">
                      <span>作者 {s.by}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </>
      )}
    </div>
  );
}
