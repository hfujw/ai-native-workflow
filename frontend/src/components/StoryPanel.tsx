import { useState, useRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Maximize2, Minimize2, Minus, X } from 'lucide-react'

interface Props {
  visible: boolean
  pageHtml: string | null
  streamingHtml: string
  isGenerating: boolean
  onClose: () => void
}

export function StoryPanel({ visible, pageHtml, streamingHtml, isGenerating, onClose }: Props) {
  const [isFullscreen, setFullscreen] = useState(false)
  const [minimized, setMinimized] = useState(false)
  const streamRef = useRef<HTMLIFrameElement>(null)

  // 流式更新：直接写 iframe document，不换 srcdoc → 不频闪
  useEffect(() => {
    if (!streamingHtml || !streamRef.current) return
    const doc = streamRef.current.contentDocument
    if (!doc) return
    doc.open()
    doc.write(streamingHtml)
    doc.close()
  }, [streamingHtml])

  if (!visible && !isGenerating) return null

  if (minimized && visible) {
    return (
      <div className="absolute z-50 left-1/2 -translate-x-1/2 pointer-events-auto" style={{ top: '62%' }}>
        <button onClick={() => setMinimized(false)}
          className="flex items-center gap-2 px-3 py-2 bg-black/40 backdrop-blur-xl border border-lime-400/20 rounded-full text-lime-400/70 hover:text-lime-300 hover:border-lime-400/40 transition-all shadow-lg">
          <div className="w-2 h-2 rounded-full bg-lime-400 animate-pulse" />
        </button>
      </div>
    )
  }

  const panelStyle = (full: boolean) => ({
    position: 'absolute' as const, left: '50%',
    zIndex: full ? 300 : 50,   // 全屏时盖过侧边栏(z-200)，避免图标重叠
    width: full ? '100vw' : 'min(560px, 55vw)',
    height: full ? '100vh' : 'auto',
    aspectRatio: full ? undefined : '16/9',
    top: full ? 0 : '60%',
    transform: full ? 'translate(-50%,0)' : 'translate(-50%,-50%)',
    borderRadius: full ? 0 : 20,
    background: full ? 'rgba(0,0,0,0.95)'
      : visible ? 'rgba(0,0,0,0.55)'
      : 'rgba(0,0,0,0.12)',
    backdropFilter: full ? 'none' : visible ? 'blur(18px)' : 'blur(6px)',
    WebkitBackdropFilter: full ? 'none' : visible ? 'blur(18px)' : 'blur(6px)',
    border: visible ? '1px solid rgba(52,211,153,0.3)'
      : isGenerating ? '1px solid rgba(255,255,255,0.1)'
      : '1px solid rgba(255,255,255,0.06)',
    boxShadow: visible ? '0 0 40px rgba(52,211,153,0.2)'
      : isGenerating ? '0 0 0 transparent'
      : '0 4px 24px rgba(0,0,0,0.3)',
    transition: 'all 0.5s cubic-bezier(0.16,1,0.3,1)',
  })

  const s = panelStyle(isFullscreen)

  return (
    <div style={s}>
      {/* 流式生成中：contentDocument.write 不触发 reload → 不频闪 */}
      {isGenerating && !visible && (
        streamingHtml ? (
          <iframe ref={streamRef} sandbox="allow-scripts" title="生成中"
            className="w-full h-full border-none bg-black opacity-60" style={{ borderRadius: 16 }} />
        ) : (
          <div className="w-full h-full flex items-center justify-center">
            <div className="flex items-center gap-2.5">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-lime-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-lime-500"></span>
              </span>
              <span className="text-white/30 text-xs tracking-[0.05em]">策展中</span>
            </div>
          </div>
        )
      )}

      {/* 成品：显影动画 */}
      <AnimatePresence>
        {visible && !isFullscreen && (
          <motion.div
            className="w-full h-full"
            initial={{ opacity: 0, scale: 0.92, filter: 'brightness(2)' }}
            animate={{ opacity: 1, scale: 1, filter: 'brightness(1)' }}
            exit={{ opacity: 0, scale: 0.95 }}
            transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
          >
            <div className="absolute top-3 right-3 z-10 flex gap-1 bg-black/30 backdrop-blur-sm rounded-xl p-0.5">
              <button onClick={() => setMinimized(true)}
                className="p-2 rounded-lg hover:bg-white/[0.12] text-white/60 hover:text-amber-300 transition-colors" title="最小化">
                <Minus size={15} /></button>
              <button onClick={() => setFullscreen(true)}
                className="p-2 rounded-lg hover:bg-white/[0.12] text-white/60 hover:text-lime-300 transition-colors" title="全屏">
                <Maximize2 size={15} /></button>
              <button onClick={onClose}
                className="p-2 rounded-lg hover:bg-red-500/20 text-white/60 hover:text-red-400 transition-colors" title="关闭">
                <X size={15} /></button>
            </div>
            <iframe srcDoc={pageHtml || ''} sandbox="allow-scripts" title="视觉故事"
              className="w-full h-full border-none bg-black" style={{ borderRadius: 16 }} />
          </motion.div>
        )}
      </AnimatePresence>

      {/* Fullscreen */}
      {visible && isFullscreen && (
        <div className="relative w-full h-full">
          <button onClick={() => setFullscreen(false)}
            className="absolute top-4 right-4 z-20 p-2.5 rounded-lg bg-black/40 backdrop-blur-sm hover:bg-red-500/25 text-white/60 hover:text-red-400 transition-colors" title="退出全屏">
            <Minimize2 size={16} /></button>
          <iframe srcDoc={pageHtml || ''} sandbox="allow-scripts" title="视觉故事-全屏"
            className="w-full h-full border-none bg-black" />
        </div>
      )}
    </div>
  )
}
