import { motion } from 'framer-motion'

const NAV = [
  { key: 'generate', icon: '🎬', label: '生成' },
  { key: 'history', icon: '🕘', label: '历史' },
  { key: 'preferences', icon: '🎨', label: '偏好' },
  { key: 'eval', icon: '📊', label: '评测' },
]

export function Sidebar({ active, onChange }) {
  return (
    <div className="fixed left-0 top-0 bottom-0 w-16 z-[200] flex flex-col items-center py-4 gap-2 bg-black/60 backdrop-blur-xl border-r border-white/5">
      <div className="mb-3 text-lg select-none">✨</div>
      {NAV.map(n => (
        <motion.button
          key={n.key}
          onClick={() => onChange(n.key)}
          whileHover={{ scale: 1.05 }}
          className={`w-11 h-11 rounded-xl flex flex-col items-center justify-center gap-0.5 transition-all
            ${active === n.key
              ? 'bg-amber-400/15 text-amber-300 border border-amber-400/25'
              : 'text-white/40 hover:text-white/80 hover:bg-white/5 border border-transparent'}`}
          title={n.label}
        >
          <span className="text-base leading-none">{n.icon}</span>
          <span className="text-[9px] leading-none">{n.label}</span>
        </motion.button>
      ))}
    </div>
  )
}
