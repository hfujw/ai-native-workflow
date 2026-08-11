import { useState, useRef, useEffect } from 'react'
import { motion } from 'framer-motion'
import { useWebSocket } from './hooks/useWebSocket'
import RevealLayer from './components/RevealLayer'
import { StoryPanel } from './components/StoryPanel'
import { SearchBubble } from './components/SearchBubble'
import { EventTags } from './components/EventTags'
import { DecisionLog } from './components/DecisionLog'
import { FailureNotice } from './components/FailureNotice'
import { ErrorBoundary } from './components/ErrorBoundary'
import { Sidebar } from './components/Sidebar'
import { IterationBar } from './components/IterationBar'
import { HistoryPanel } from './components/HistoryPanel'
import { PreferencesPanel } from './components/PreferencesPanel'
import { EvalPanel } from './components/EvalPanel'

const BG_BASE   = '/images/base.jpg'
const BG_REVEAL = '/images/reveal.jpg'

export default function App() {
  const ws = useWebSocket()
  const { messages, pageHtml, streamingHtml, error, isGenerating, iterations,
          sendEvent, sendInstruction, loadDemo, cancel, dismiss,
          refreshHistory, refreshEval, refreshPreferences, savePreferences } = ws

  const [view, setView] = useState('generate')

  // 演示话题 — 和后端 main.py DEMO_TOPICS 保持同步
  const DEMO_TOPICS = ['秦始皇修长城','Turing 破译 Enigma','Python 装饰器','郑和下西洋','世界杯历届冠军']
  const [demoReady, setDemoReady] = useState(new Set())

  useEffect(() => {
    fetch('/api/demos').then(r => r.json()).then(d => {
      setDemoReady(new Set(d.demos.filter((x) => x.ready).map((x) => x.name)))
    }).catch(() => {})
  }, [])

  const handleTopicSelect = (topic) => {
    if (DEMO_TOPICS.includes(topic)) {
      loadDemo(topic)
    } else {
      sendEvent(topic)
    }
  }

  // ── 光标聚光灯（同 lithos-replica）──
  const mouse  = useRef({ x:-999, y:-999 })
  const smooth = useRef({ x:-999, y:-999 })
  const rafRef = useRef()
  const [cursorPos, setCursorPos] = useState({ x:-999, y:-999 })

  useEffect(() => {
    const onMove = (e) => { mouse.current = { x:e.clientX, y:e.clientY } }
    window.addEventListener('mousemove', onMove)
    const loop = () => {
      smooth.current.x += (mouse.current.x - smooth.current.x) * 0.1
      smooth.current.y += (mouse.current.y - smooth.current.y) * 0.1
      const rx=Math.round(smooth.current.x), ry=Math.round(smooth.current.y)
      setCursorPos(p => (p.x===rx&&p.y===ry)?p:{x:rx,y:ry})
      rafRef.current = requestAnimationFrame(loop)
    }
    rafRef.current = requestAnimationFrame(loop)
    return () => { window.removeEventListener('mousemove',onMove); cancelAnimationFrame(rafRef.current) }
  }, [])

  return (
    <ErrorBoundary>
      <div className="min-h-screen bg-black">
        <Sidebar active={view} onChange={setView} />

        {view === 'generate' && (
          <section className="relative w-full h-screen overflow-hidden bg-black" style={{ height:'100dvh' }}>

            {/* z-10: 基底图 */}
            <div className="absolute inset-0 bg-center bg-cover bg-no-repeat z-10 hero-zoom"
              style={{ backgroundImage:`url(${BG_BASE})` }} />

            {/* z-20: 光标揭示层 */}
            <RevealLayer image={BG_REVEAL} cursorX={cursorPos.x} cursorY={cursorPos.y} />

            {/* z-50: 标题 */}
            <div className="absolute z-50 top-[8%] left-0 right-0 flex flex-col items-center text-center px-5 pointer-events-none">
              <h1 className="text-white leading-[0.95]">
                <span className="block text-5xl sm:text-7xl md:text-8xl font-semibold hero-anim hero-reveal"
                  style={{ fontFamily:"'PingFang SC','Noto Serif SC','STSong',serif", letterSpacing:'0.04em', animationDelay:'0.25s' }}>
                  时光像素
                </span>
                <span className="block text-lg sm:text-2xl md:text-3xl font-light mt-3 text-white/45 hero-anim hero-reveal"
                  style={{ letterSpacing:'0.22em', animationDelay:'0.42s' }}>
                  以 光 为 笔  ·  以 史 为 墨
                </span>
              </h1>
            </div>

            {/* z-50: 搜索框 + 快捷标签 + 工具状态灯 */}
            <div className="absolute z-50 top-[28%] left-1/2 -translate-x-1/2 w-[90vw] max-w-lg pointer-events-auto flex flex-col items-center gap-4">
              <SearchBubble onGenerate={sendEvent} isGenerating={isGenerating} onCancel={cancel} />
              <div className="flex flex-wrap justify-center gap-2">
                {DEMO_TOPICS.map(t => (
                  <motion.button
                    key={t}
                    onClick={() => loadDemo(t)}
                    whileHover={{ boxShadow: '0 0 16px rgba(251,191,36,0.15), 0 0 4px rgba(251,191,36,0.1)' }}
                    className="px-3 py-1 text-[11px] text-amber-200/40 hover:text-amber-200/70 bg-amber-400/[0.02] hover:bg-amber-400/[0.06] border border-amber-400/[0.06] hover:border-amber-400/[0.15] rounded-full transition-all">
                    {t}{demoReady.has(t) && <span className="ml-1 text-amber-400/50">✓</span>}
                  </motion.button>
                ))}
              </div>
            </div>

            {/* z-50: 事件标签 */}
            <div className="absolute z-50 inset-0 pointer-events-none">
              <EventTags onSelect={handleTopicSelect} disabled={isGenerating} />
            </div>

            {/* z-50: 生成结果展示 */}
            <StoryPanel
              visible={!!pageHtml}
              pageHtml={pageHtml}
              streamingHtml={streamingHtml}
              isGenerating={isGenerating}
              onClose={dismiss}
            />

            {/* z-100: 失败提示 */}
            <FailureNotice
              visible={!!error}
              reason={error?.reason||''}
              suggestions={error?.suggestions||[]}
              onRetry={handleTopicSelect}
              onDismiss={dismiss}
            />

            {/* z-100: 决策轨迹 */}
            <DecisionLog messages={messages} autoCollapse={!!pageHtml} />

            {/* z-150: Phase C 多轮迭代条 */}
            <IterationBar
              visible={!!pageHtml}
              iterations={iterations}
              isGenerating={isGenerating}
              onSend={sendInstruction}
            />

          </section>
        )}

        {view !== 'generate' && (
          <div className="ml-16 min-h-screen bg-black overflow-y-auto">
            {view === 'history' && <HistoryPanel refresh={refreshHistory} />}
            {view === 'preferences' && <PreferencesPanel refresh={refreshPreferences} save={savePreferences} />}
            {view === 'eval' && <EvalPanel refresh={refreshEval} />}
          </div>
        )}
      </div>
    </ErrorBoundary>
  )
}
