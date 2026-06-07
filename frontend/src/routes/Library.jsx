import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { errorText, getSessions } from '../lib/api.js'
import { formatDuration } from '../lib/report.js'
import {
  formatStartedAt,
  sessionTitle,
  sessionVisible,
  statusTag,
  summaryScore,
} from '../lib/sessions.js'

// 状态标签配色：seed 演示数据（暖黄）/ failed（绯红）/ processing（翡翠）
const TAG_BASE =
  'rounded-full border px-2 py-1 font-mono text-[11px] font-semibold leading-none'
const TAG_KIND = {
  seed: 'border-[#e8d98a] bg-[#fdf6d8] text-[#7c6a00]',
  failed: 'border-[#eebac2] bg-[#fbe9ec] text-[#a0303f]',
  processing: 'border-accent-line bg-accent-soft text-accent',
}

// F5 Library（handoff 007，真 GET /sessions）：历史会话列表（时间/模式/时长/
// 摘要分）→ 点进 /report/{id}；is_seed 标「演示数据」；failed/processing 打标
// 仍可点（报告页有对应终态/轮询展示）；live/recording 瞬态不进列表。
export default function Library() {
  const [rows, setRows] = useState(null) // null=加载中
  const [error, setError] = useState(null)
  const [attempt, setAttempt] = useState(0)

  // Retry 变化 → 渲染期重置加载态（Record.jsx 同款，effect 内不做同步 setState）
  const [prevAttempt, setPrevAttempt] = useState(attempt)
  if (prevAttempt !== attempt) {
    setPrevAttempt(attempt)
    setRows(null)
    setError(null)
  }

  useEffect(() => {
    const ac = new AbortController()
    getSessions({ signal: ac.signal }).then(
      (list) => setRows(list.filter(sessionVisible)),
      (e) => {
        if (!ac.signal.aborted) setError(errorText(e))
      },
    )
    return () => ac.abort()
  }, [attempt])

  return (
    <section>
      <h1>Library</h1>
      <p className="muted">练习历史——点击任意一次进入完整报告。</p>

      {error && (
        <>
          <p className="form-error">{error}</p>
          <button type="button" className="btn-primary" onClick={() => setAttempt((n) => n + 1)}>
            Retry
          </button>
        </>
      )}

      {!error && rows == null && <p className="muted">加载中…</p>}

      {rows != null && rows.length === 0 && (
        <p className="muted">
          还没有练习记录——去 <Link to="/practice">Practice</Link> 开始第一次会话。
        </p>
      )}

      {rows != null && rows.length > 0 && (
        <ul className="m-0 mt-4.5 flex list-none flex-col gap-2.5 p-0">
          {rows.map((r) => {
            const tag = statusTag(r)
            return (
              <li key={r.id}>
                <Link
                  className="flex items-center gap-3.5 rounded-xl border border-line bg-white px-4.5 py-3.5 text-ink-strong no-underline shadow-[0_1px_2px_rgba(10,10,10,0.02)] transition-[border-color,box-shadow] duration-150 hover:border-accent-line hover:shadow-[0_4px_16px_-8px_rgba(13,156,110,0.25)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                  to={`/report/${r.id}`}
                >
                  <span className="min-w-[180px] font-semibold">{sessionTitle(r)}</span>
                  <span className="flex flex-1 gap-3.5 font-mono text-[13px] leading-none text-ink">
                    <span>{formatStartedAt(r.started_at)}</span>
                    <span>
                      {typeof r.duration_s === 'number' ? formatDuration(r.duration_s) : '—'}
                    </span>
                  </span>
                  <span className="flex items-center gap-2">
                    {r.is_seed && <span className={`${TAG_BASE} ${TAG_KIND.seed}`}>演示数据</span>}
                    {tag && <span className={`${TAG_BASE} ${TAG_KIND[tag.kind] ?? ''}`}>{tag.text}</span>}
                    <span className="min-w-[76px] text-right font-mono text-[13px] font-semibold leading-none text-accent">
                      {summaryScore(r)}
                    </span>
                  </span>
                </Link>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
