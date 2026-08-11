import { useState } from 'react'

const QUICK = ['再大胆一点', '换个配色', '更简洁', '加一页数据']

// Phase C：多轮迭代——成品下方继续提要求，agent 接着改
export function IterationBar({ visible, iterations, isGenerating, onSend }) {
  const [text, setText] = useState('')
  if (!visible) return null

  const submit = () => {
    if (!text.trim() || isGenerating) return
    onSend(text.trim())
    setText('')
  }

  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-[150] w-[min(90vw,560px)]">
      {iterations > 0 && (
        <div className="text-center mb-2 text-xs text-amber-200/60">
          第 {iterations} 版 · 生成完成后可继续提要求
        </div>
      )}
      <div className="flex flex-wrap justify-center gap-2 mb-2">
        {QUICK.map(q => (
          <button
            key={q}
            disabled={isGenerating}
            onClick={() => onSend(q)}
            className="px-3 py-1 text-[11px] text-amber-200/50 hover:text-amber-200/80 bg-amber-400/[0.04] hover:bg-amber-400/[0.08] border border-amber-400/10 rounded-full transition-all disabled:opacity-30"
          >
            {q}
          </button>
        ))}
      </div>
      <div className="flex gap-2">
        <input
          value={text}
          onChange={e => setText(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') submit() }}
          placeholder="提修改要求…（如：把标题放大、改成暗色系）"
          className="flex-1 px-4 py-2.5 rounded-xl bg-white/5 border border-white/10 text-white placeholder-white/30 text-sm focus:outline-none focus:border-amber-400/30"
        />
        <button
          onClick={submit}
          disabled={isGenerating || !text.trim()}
          className="px-4 py-2.5 rounded-xl bg-amber-400/20 text-amber-200 text-sm hover:bg-amber-400/30 disabled:opacity-30 transition-all"
        >
          改
        </button>
      </div>
    </div>
  )
}
