import { useEffect, useState } from 'react'

// Phase C：用户偏好——查看/编辑记忆的风格
export function PreferencesPanel({ refresh, save }) {
  const [prefs, setPrefs] = useState({ style_hints: [], preferred_components: [] })
  const [style, setStyle] = useState('')
  const [comp, setComp] = useState('')

  useEffect(() => {
    refresh().then(setPrefs)
  }, [refresh])

  const addStyle = async () => {
    if (!style.trim()) return
    const next = [...(prefs.style_hints || []), style.trim()]
    const saved = await save({ style_hints: next })
    if (saved) setPrefs(saved)
    setStyle('')
  }

  const removeStyle = async (s) => {
    const next = (prefs.style_hints || []).filter(x => x !== s)
    const saved = await save({ style_hints: next })
    if (saved) setPrefs(saved)
  }

  const addComp = async () => {
    if (!comp.trim()) return
    const next = [...(prefs.preferred_components || []), comp.trim()]
    const saved = await save({ preferred_components: next })
    if (saved) setPrefs(saved)
    setComp('')
  }

  return (
    <div className="p-6 max-w-2xl">
      <h2 className="text-2xl font-light text-white mb-1">🎨 我的偏好</h2>
      <p className="text-white/40 text-sm mb-6">生成后自动记住你的风格，下次生成自动带上。</p>

      <div className="mb-8">
        <div className="text-white/60 text-xs mb-2">风格（visual_hint 关键词）</div>
        <div className="flex flex-wrap gap-2 mb-2">
          {(prefs.style_hints || []).length === 0 && (
            <span className="text-white/30 text-xs">还没有记住风格</span>
          )}
          {(prefs.style_hints || []).map((s, i) => (
            <span key={i}
              className="group px-2 py-1 text-xs bg-amber-400/10 text-amber-200 border border-amber-400/20 rounded-full cursor-pointer"
              onClick={() => removeStyle(s)} title="点击删除">
              {s} <span className="opacity-50 group-hover:opacity-100">×</span>
            </span>
          ))}
        </div>
        <div className="flex gap-2">
          <input
            value={style}
            onChange={e => setStyle(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') addStyle() }}
            placeholder="加个风格…（如：暗色）"
            className="flex-1 px-3 py-1.5 rounded-lg bg-white/5 border border-white/10 text-white placeholder-white/30 text-sm focus:outline-none focus:border-amber-400/30"
          />
          <button onClick={addStyle}
            className="px-3 py-1.5 rounded-lg bg-amber-400/20 text-amber-200 text-sm hover:bg-amber-400/30 transition-all">
            添加
          </button>
        </div>
      </div>

      <div>
        <div className="text-white/60 text-xs mb-2">偏好组件（timeline / cards / …）</div>
        <div className="flex flex-wrap gap-2 mb-2">
          {(prefs.preferred_components || []).length === 0 && (
            <span className="text-white/30 text-xs">还没记住组件偏好</span>
          )}
          {(prefs.preferred_components || []).map((c, i) => (
            <span key={i} className="px-2 py-1 text-xs bg-white/10 text-white/70 border border-white/10 rounded-full">{c}</span>
          ))}
        </div>
        <div className="flex gap-2">
          <input
            value={comp}
            onChange={e => setComp(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') addComp() }}
            placeholder="加个组件…（如：timeline）"
            className="flex-1 px-3 py-1.5 rounded-lg bg-white/5 border border-white/10 text-white placeholder-white/30 text-sm focus:outline-none focus:border-amber-400/30"
          />
          <button onClick={addComp}
            className="px-3 py-1.5 rounded-lg bg-white/10 text-white/70 text-sm hover:bg-white/15 transition-all">
            添加
          </button>
        </div>
      </div>
    </div>
  )
}
