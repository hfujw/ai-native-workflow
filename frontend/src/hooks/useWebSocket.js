import { useState, useRef, useCallback } from 'react'

// HTTPS 环境自动用 wss
const WS_URL = `ws${location.protocol === 'https:' ? 's' : ''}://${window.location.host}/ws/generate`

export function useWebSocket() {
  const [messages, setMessages] = useState([])
  const [pageHtml, setPageHtml] = useState(null)
  const [streamingHtml, setStreamingHtml] = useState('')
  const [error, setError] = useState(null)
  const [isGenerating, setIsGenerating] = useState(false)
  const [iterations, setIterations] = useState(0)   // Phase C：多轮迭代版本号
  const wsRef = useRef(null)
  const logIdRef = useRef(0)
  const generatingRef = useRef(false)

  const lastSend = useRef(0)
  const reconnectRef = useRef(0)
  const eventRef = useRef('')

  const connectWS = useCallback((eventText) => {
    // 关闭旧的 socket
    if (wsRef.current) {
      wsRef.current.close()
    }

    const ws = new WebSocket(WS_URL)
    wsRef.current = ws

    ws.onopen = () => {
      reconnectRef.current = 0
      ws.send(JSON.stringify({ event: eventText }))
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)

        switch (data.type) {
          case 'html_chunk':
            setStreamingHtml(data.html || '')
            break

          case 'page_ready':
            setPageHtml(data.page_html)
            setStreamingHtml('')
            setIsGenerating(false)
            generatingRef.current = false
            break

          case 'generation_failed':
            setError({
              reason: data.reason || '生成失败',
              suggestions: data.suggestions || [],
            })
            setIsGenerating(false)
            generatingRef.current = false
            break

          case 'thinking_stream':
            // 逐字追加到同一条 thinking 消息
            setMessages(prev => {
              const last = prev[prev.length - 1]
              if (last && last.type === 'thinking_stream' && last.agent === data.tool) {
                // 追加到上一条
                const updated = [...prev]
                updated[updated.length - 1] = { ...last, detail: last.detail + data.chunk }
                return updated
              }
              // 新建一条
              return [...prev, {
                id: ++logIdRef.current,
                time: new Date().toLocaleTimeString(),
                agent: data.tool || 'decide',
                detail: data.chunk || '',
                type: 'thinking_stream',
              }]
            })
            break

          case 'thinking':
            setMessages(prev => [...prev, {
              id: ++logIdRef.current,
              time: new Date().toLocaleTimeString(),
              agent: data.tool || 'thinking',
              detail: data.thought || '',
              type: 'thinking',
            }])
            break

          case 'tool_result':
            setMessages(prev => [...prev, {
              id: ++logIdRef.current,
              time: new Date().toLocaleTimeString(),
              agent: data.tool || 'tool',
              detail: data.summary || '',
              type: 'tool_result',
            }])
            break

        }
      } catch (e) {
        // 忽略无法解析的消息帧
        setMessages(prev => [...prev, {
          id: ++logIdRef.current,
          time: new Date().toLocaleTimeString(),
          agent: 'system',
          detail: `消息解析失败: ${e.message}`,
        }])
      }
    }

    ws.onerror = () => {
      // 不立即报错——让 onclose 处理重连逻辑
    }

    ws.onclose = () => {
      if (!generatingRef.current) return
      const MAX_RECONNECT = 3
      if (reconnectRef.current < MAX_RECONNECT) {
        const delay = 1000 * Math.pow(2, reconnectRef.current)
        reconnectRef.current++
        setMessages(prev => [...prev, {
          id: ++logIdRef.current,
          time: new Date().toLocaleTimeString(),
          agent: 'system',
          detail: `连接断开，${delay / 1000}s 后重连（第 ${reconnectRef.current}/${MAX_RECONNECT} 次）`,
        }])
        setTimeout(() => connectWS(eventRef.current), delay)
      } else {
        setError({ reason: 'WebSocket 连接失败，请确认后端已启动', suggestions: [] })
        setIsGenerating(false)
        generatingRef.current = false
      }
    }
  }, [])

  const sendEvent = useCallback((eventText) => {
    if (!eventText.trim()) return

    // 防抖：1秒内不重复触发
    const now = Date.now()
    if (now - lastSend.current < 1000) return
    lastSend.current = now

    // Reset state
    setMessages([])
    setPageHtml(null)
    setStreamingHtml('')
    setError(null)
    setIsGenerating(true)
    generatingRef.current = true
    reconnectRef.current = 0
    eventRef.current = eventText
    setIterations(0)

    connectWS(eventText)
  }, [connectWS])

  // ── Phase C：多轮迭代——在成品基础上继续改 ──
  const sendInstruction = useCallback((text) => {
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN || !text.trim()) return
    setIsGenerating(true)
    generatingRef.current = true
    setIterations(prev => prev + 1)
    ws.send(JSON.stringify({ instruction: text.trim() }))
  }, [])

  const dismiss = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
    setIsGenerating(false)
    generatingRef.current = false
    setPageHtml(null)
    setStreamingHtml('')
    setError(null)
    setMessages([])
    setIterations(0)
  }, [])

  const cancel = useCallback(() => dismiss(), [dismiss])

  // ── Phase B/E：历史 / 评测 / 偏好 ──
  const refreshHistory = useCallback(async () => {
    try {
      const r = await fetch('/api/history')
      if (r.ok) return (await r.json()).projects || []
    } catch {}
    return []
  }, [])

  const refreshEval = useCallback(async () => {
    try {
      const r = await fetch('/api/eval')
      if (r.ok) return await r.json()
    } catch {}
    return null
  }, [])

  const refreshPreferences = useCallback(async () => {
    try {
      const r = await fetch('/api/preferences')
      if (r.ok) return await r.json()
    } catch {}
    return {}
  }, [])

  const savePreferences = useCallback(async (patch) => {
    try {
      const r = await fetch('/api/preferences', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      })
      if (r.ok) return await r.json()
    } catch {}
    return null
  }, [])

  // ── Demo 模式：加载预生成 HTML，零成本即时展示 ──
  const loadDemo = useCallback(async (topic) => {
    // 关闭正在运行的生成
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }

    // 重置状态
    setMessages([])
    setPageHtml(null)
    setStreamingHtml('')
    setError(null)
    setIsGenerating(false)
    generatingRef.current = false

    try {
      const resp = await fetch(`/api/demos/${encodeURIComponent(topic)}`)
      if (!resp.ok) throw new Error('demo not found')
      const data = await resp.json()

      setPageHtml(data.html)
      const tag = data.cached ? '📖' : '⏳'
      const note = data.cached ? '' : '（待生成，本地运行一次即可替换）'
      setMessages([{
        id: ++logIdRef.current,
        time: new Date().toLocaleTimeString(),
        agent: 'system',
        detail: `${tag} 演示：「${topic}」${note}`,
      }])
    } catch {
      setError({ reason: '演示内容加载失败，请确认后端已启动', suggestions: [] })
    }
  }, [])

  return {
    messages, pageHtml, streamingHtml, error, isGenerating, iterations,
    sendEvent, sendInstruction, loadDemo, cancel, dismiss,
    refreshHistory, refreshEval, refreshPreferences, savePreferences,
  }
}
