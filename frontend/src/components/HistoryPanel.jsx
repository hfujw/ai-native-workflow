import { useEffect, useState } from 'react'

// Phase B：生成历史——卡片列表 + 点开回看
export function HistoryPanel({ refresh }) {
  const [projects, setProjects] = useState([])
  const [selected, setSelected] = useState(null)

  useEffect(() => {
    refresh().then(setProjects)
  }, [refresh])

  return (
    <div className="p-6 max-w-3xl">
      <h2 className="text-2xl font-light text-white mb-1">🕘 生成历史</h2>
      <p className="text-white/40 text-sm mb-4">每次生成（含迭代）都会留在这里，点开可回看。</p>
      {projects.length === 0 && (
        <p className="text-white/40 text-sm">还没有生成记录——去「生成」页试试。</p>
      )}
      <div className="space-y-2">
        {projects.map(p => (
          <button
            key={p.id}
            onClick={() => setSelected(p)}
            className="w-full text-left p-3 rounded-xl bg-white/[0.04] hover:bg-white/[0.08] border border-white/10 flex items-center justify-between transition-all"
          >
            <div className="min-w-0">
              <div className="text-white text-sm truncate">{p.topic}</div>
              <div className="text-white/40 text-[11px] mt-0.5">
                {new Date(p.created_at * 1000).toLocaleString()} · {p.iterations} 版
                {p.status === 'success' ? ' · ✅' : ' · ❌'}
              </div>
            </div>
            <div className="text-amber-200/70 text-xs shrink-0 ml-3">¥{p.cost}</div>
          </button>
        ))}
      </div>

      {selected && (
        <div
          className="fixed inset-0 z-[300] flex items-center justify-center bg-black/85 p-6"
          onClick={() => setSelected(null)}
        >
          <div className="relative w-[85vw] h-[85vh] max-w-5xl">
            <div className="absolute -top-8 left-0 text-white/60 text-sm">{selected.topic}</div>
            <iframe
              title="history-preview"
              srcDoc={selected.html}
              className="w-full h-full rounded-xl bg-white border border-white/10"
              onClick={e => e.stopPropagation()}
            />
          </div>
        </div>
      )}
    </div>
  )
}
