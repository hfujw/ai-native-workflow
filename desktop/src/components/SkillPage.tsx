import { useState } from "react";

type Skill = {
  name: string;
  type: string;
  desc: string;
  by: string;
  icon: string;
  uses: number;
};

// 随项目一起打包、作者推荐的 skill（精选展示；没有上线，不存在"热门"）
const SKILLS: Skill[] = [
  { name: "像素风", type: "风格", desc: "复古像素游戏画面，适合解谜与怀旧题材", by: "官方", icon: "🎮", uses: 1200000 },
  { name: "杂志长图", type: "风格", desc: "编辑级杂志排版，图文混排长页", by: "官方", icon: "📰", uses: 860000 },
  { name: "信息图", type: "风格", desc: "数据可视化，图表 + 关键数字一眼看懂", by: "官方", icon: "📊", uses: 940000 },
  { name: "搜索", type: "工具", desc: "联网搜素材，向量语义兜底", by: "官方", icon: "🔍", uses: 1500000 },
  { name: "3D 场景", type: "风格", desc: "沉浸式三维场景叙事", by: "社区", icon: "🧊", uses: 620000 },
  { name: "图表", type: "工具", desc: "生成折线 / 柱状 / 饼图", by: "社区", icon: "📈", uses: 710000 },
];

const TABS = ["精选", "我的 Skill", "分类"];
const CATEGORIES = ["全部", "风格", "工具"];

function formatUses(n: number): string {
  if (n >= 1000000) return (n / 1000000).toFixed(1) + "M";
  return Math.round(n / 1000) + "K";
}

export default function SkillPage({ onBack }: { onBack: () => void }) {
  const [tab, setTab] = useState("精选");
  const [search, setSearch] = useState("");
  const [detail, setDetail] = useState<Skill | null>(null);
  const [category, setCategory] = useState("全部");

  // ── 详情页 ──
  if (detail) {
    return (
      <div className="skill-page">
        <button className="back-btn" onClick={() => setDetail(null)}>← 返回</button>
        <div className="skill-detail">
          <div className="skill-detail-icon">{detail.icon}</div>
          <h2 className="skill-detail-name">{detail.name}</h2>
          <div className="skill-detail-by">作者 {detail.by}</div>
          <div className="skill-detail-rating">★ 4.8 · {formatUses(detail.uses)} 次使用</div>
          <button className="start-chat-btn" onClick={onBack}>开始生成</button>
          <p className="skill-detail-desc">{detail.desc}</p>
          <div className="skill-detail-starters">
            <div className="starter-label">对话起手式</div>
            <button className="starter-pill">「{detail.name}」适合什么主题？</button>
            <button className="starter-pill">给我一个示例</button>
          </div>
        </div>
      </div>
    );
  }

  // ── 按标签取数据 ──
  let skills: Skill[] = [];
  if (tab === "精选") skills = SKILLS.filter((s) => s.by === "官方");
  else if (tab === "分类") skills = SKILLS.filter((s) => category === "全部" || s.type === category);
  // 我的 Skill：用户在对话里让 DeepSeek 搜索下载的 skill 会出现在这里（当前为空）

  if (tab !== "我的 Skill") {
    skills = skills.filter((s) => s.name.includes(search) || s.desc.includes(search));
  }

  return (
    <div className="skill-page">
      <div className="skill-topbar">
        <div className="skill-search">
          <span>🔍</span>
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="搜索 Skill..." />
        </div>
        <button className="back-btn" onClick={onBack}>✕</button>
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
        <div className="my-skills-empty">
          <div className="my-skills-icon">🧩</div>
          <p>还没有下载的 Skill</p>
          <p className="my-skills-hint">在对话里输入「帮我找 XX skill 并下载」，DeepSeek 会下载到这里；制作时它会自动选用合适的 skill</p>
          <button className="new-skill-btn" onClick={onBack}>去对话找 Skill</button>
        </div>
      ) : (
        <>
          <div className="skill-section-title">{tab}</div>
          {skills.length === 0 ? (
            <p className="skill-no-result">没找到匹配的 Skill</p>
          ) : (
            <div className="skill-grid">
              {skills.map((s) => (
                <div key={s.name} className="skill-card" onClick={() => setDetail(s)}>
                  <div className="skill-card-icon">{s.icon}</div>
                  <div className="skill-card-name">{s.name}</div>
                  <div className="skill-card-desc">{s.desc}</div>
                  <div className="skill-card-meta">
                    <span>作者 {s.by}</span>
                    <span>🔥 {formatUses(s.uses)}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
