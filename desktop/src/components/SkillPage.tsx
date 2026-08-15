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
import { deleteSkill, fetchSkills } from "../lib/api";
import type { Skill as ApiSkill } from "../lib/api";

type Skill = {
  id: string;
  name: string;
  type: string;
  desc: string;
  by: string;
  builtin: boolean;
  icon: ComponentType<IconProps>;
};

/** skill id → 图标（未知 id 用网格兜底） */
const SKILL_ICONS: Record<string, ComponentType<IconProps>> = {
  pixel: IconGamepad,
  magazine: IconNewspaper,
  infographic: IconChartBar,
  search: IconSearch,
};

const TABS = ["精选", "我的 Skill", "分类"];
const CATEGORIES = ["全部", "风格", "工具"];

export default function SkillPage({ onBack }: { onBack: () => void }) {
  const [tab, setTab] = useState("精选");
  const [search, setSearch] = useState("");
  const [detail, setDetail] = useState<Skill | null>(null);
  const [category, setCategory] = useState("全部");
  const [skills, setSkills] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  const reload = () => {
    setLoading(true);
    setFailed(false);
    fetchSkills()
      .then((data) => {
        setSkills(
          (data.skills ?? []).map((s: ApiSkill) => ({
            id: s.id,
            name: s.name,
            type: s.type,
            desc: s.desc,
            by: s.builtin ? "官方" : "自定义",
            builtin: s.builtin,
            icon: SKILL_ICONS[s.id] ?? IconGrid,
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

  /** 删除自定义 skill（内置不可删） */
  const removeSkill = async (id: string) => {
    try {
      await deleteSkill(id);
      reload();
    } catch {
      /* 删除失败静默（内置/不存在等） */
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
          <div className="skill-detail-by">作者 {detail.by}</div>
          <button className="start-chat-btn" onClick={onBack}>开始生成</button>
          <p className="skill-detail-desc">{detail.desc}</p>
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
        <button className="back-btn" onClick={onBack}>
          <IconClose size={16} />
        </button>
      </div>

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
              <p className="my-skills-hint">在对话里输入「帮我找 XX skill 并下载」，Lumen 会下载到这里；制作时它会自动选用合适的 skill</p>
              <button className="new-skill-btn" onClick={onBack}>去对话找 Skill</button>
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
