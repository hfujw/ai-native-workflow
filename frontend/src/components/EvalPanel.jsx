import { useEffect, useState } from 'react'

// Phase D：评测——真实数字：通过率 / 平均步数 / 成本
export function EvalPanel({ refresh }) {
  const [report, setReport] = useState(null)

  useEffect(() => {
    refresh().then(setReport)
  }, [refresh])

  if (!report) {
    return (
      <div className="p-6 max-w-3xl">
        <h2 className="text-2xl font-light text-white mb-4">📊 评测</h2>
        <p className="text-white/40 text-sm">加载中…</p>
      </div>
    )
  }

  if (report.status === 'not_run') {
    return (
      <div className="p-6 max-w-3xl">
        <h2 className="text-2xl font-light text-white mb-4">📊 评测</h2>
        <p className="text-white/40 text-sm mb-2">还没跑过评测。</p>
        <code className="text-amber-200/70 text-xs bg-white/5 px-3 py-2 rounded-lg block w-fit">
          cd backend && python scripts/eval_run.py
        </code>
      </div>
    )
  }

  return (
    <div className="p-6 max-w-3xl">
      <h2 className="text-2xl font-light text-white mb-4">📊 评测</h2>
      <div className="grid grid-cols-3 gap-3 mb-6">
        <Stat label="通过率" value={`${(report.pass_rate * 100).toFixed(0)}%`} />
        <Stat label="平均步数" value={report.avg_steps} />
        <Stat label="平均成本" value={`¥${report.avg_cost}`} />
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-white/40 text-xs">
            <th className="text-left py-2">话题</th>
            <th className="text-center">状态</th>
            <th className="text-center">步数</th>
            <th className="text-center">成本</th>
          </tr>
        </thead>
        <tbody>
          {(report.results || []).map((r, i) => (
            <tr key={i} className="border-t border-white/5 text-white/80">
              <td className="py-2">{r.topic}</td>
              <td className="text-center">{r.status === 'success' ? '✅' : '❌'}</td>
              <td className="text-center">{r.steps ?? '?'}</td>
              <td className="text-center">¥{r.cost ?? 0}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Stat({ label, value }) {
  return (
    <div className="p-4 rounded-xl bg-white/[0.04] border border-white/10">
      <div className="text-white/40 text-xs mb-1">{label}</div>
      <div className="text-2xl font-light text-amber-200">{value}</div>
    </div>
  )
}
