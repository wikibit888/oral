import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import BandRadar from '../components/report/BandRadar.jsx'
import { errorText, getProgress, putSettings } from '../lib/api.js'
import { FLUENCY_METRICS, gapRows, latestToDimensions, tickDate } from '../lib/sessions.js'

// recharts 不吃 CSS 变量——与 index.css 手动同步（BandRadar 同款约定）
const LINE_COLORS = {
  overall_band: '#0d9c6e',
  fc_band: '#7c8db5',
  lr_band: '#c9a227',
  gra_band: '#b56576',
  pron_band: '#5e9ed6',
}
const BAND_LINES = [
  { key: 'overall_band', label: 'Overall', width: 2.4 },
  { key: 'fc_band', label: 'Fluency', width: 1.2 },
  { key: 'lr_band', label: 'Lexical', width: 1.2 },
  { key: 'gra_band', label: 'Grammar', width: 1.2 },
  { key: 'pron_band', label: 'Pronun.', width: 1.2 },
]

// 节标题：preflight 重置裸 h2 后显式补回（数据页统一 19px 半粗）
const BLOCK = 'mt-6.5'
const BLOCK_H2 = 'mb-1 mt-0 text-[19px] font-semibold text-ink-strong'

// F5 Review 进步面板（handoff 007，真 GET /progress + GET/PUT /settings）：
// band 轨迹折线（仅方式 A，接口已过滤）+ 最新雷达（latest_bands）+ 流利度
// 趋势四小图（全模式，error_rate 为 §6.4 新增线）+ 目标差距（gap，正=还差
// 负=已超）。目标 band 存后端 settings（已替代 localStorage）。
export default function Review() {
  const [data, setData] = useState(null) // /progress 响应
  const [error, setError] = useState(null)
  const [attempt, setAttempt] = useState(0)
  // 目标 band 编辑框：以 /progress 回的 target_band 为初值，保存走 PUT
  const [targetInput, setTargetInput] = useState('')
  const [saveState, setSaveState] = useState(null) // null | 'saving' | 'saved' | 错误文案

  // Retry/保存后重拉 → 渲染期重置加载态（Record.jsx 同款，effect 内不做同步 setState）
  const [prevAttempt, setPrevAttempt] = useState(attempt)
  if (prevAttempt !== attempt) {
    setPrevAttempt(attempt)
    setData(null)
    setError(null)
  }

  useEffect(() => {
    const ac = new AbortController()
    getProgress({ signal: ac.signal }).then(
      (d) => {
        setData(d)
        setTargetInput(d.target_band == null ? '' : String(d.target_band))
      },
      (e) => {
        if (!ac.signal.aborted) setError(errorText(e))
      },
    )
    return () => ac.abort()
  }, [attempt])

  const saveTarget = async (value) => {
    setSaveState('saving')
    try {
      await putSettings(value)
      setSaveState('saved')
      setAttempt((n) => n + 1) // 重拉 /progress：gap 由后端算
    } catch (e) {
      setSaveState(errorText(e)) // 422 中文 detail 直出
    }
  }

  if (error) {
    return (
      <section>
        <h1>Review</h1>
        <p className="form-error">{error}</p>
        <button type="button" className="btn-primary" onClick={() => setAttempt((n) => n + 1)}>
          Retry
        </button>
      </section>
    )
  }

  if (data == null) {
    return (
      <section>
        <h1>Review</h1>
        <p className="muted">加载中…</p>
      </section>
    )
  }

  const { band_series, fluency_series, latest_bands, gap } = data
  const latestDims = latestToDimensions(latest_bands)
  const gapList = gapRows(gap)
  const empty = band_series.length === 0 && fluency_series.length === 0

  return (
    <section>
      <h1>Review</h1>
      <p className="muted">进步面板——band 轨迹仅雅思 Mock Exam 产生；流利度趋势全模式可比。</p>

      {empty && (
        <p className="muted">
          还没有可比的完成会话——去 <Link to="/practice">Practice</Link> 攒下第一个数据点。
        </p>
      )}

      {band_series.length > 0 && (
        <div className={BLOCK}>
          <h2 className={BLOCK_H2}>Band Trajectory</h2>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={band_series} margin={{ top: 8, right: 16, bottom: 0, left: -18 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e7e7ea" />
              <XAxis dataKey="date" tickFormatter={tickDate} tick={{ fontSize: 11 }} />
              <YAxis domain={[0, 9]} tickCount={10} tick={{ fontSize: 11 }} />
              <Tooltip labelFormatter={tickDate} />
              <Legend />
              {BAND_LINES.map(({ key, label, width }) => (
                <Line
                  key={key}
                  type="monotone"
                  dataKey={key}
                  name={label}
                  stroke={LINE_COLORS[key]}
                  strokeWidth={width}
                  dot={{ r: 2.5 }}
                  connectNulls // 四维可空（judge 降级），跳过缺点连线
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="grid grid-cols-[repeat(auto-fit,minmax(300px,1fr))] gap-x-7">
        {latestDims && (
          <div className={BLOCK}>
            <h2 className={BLOCK_H2}>Latest Bands</h2>
            <p className="muted">最新一次 Mock Exam（{tickDate(latest_bands.date)}）四维雷达。</p>
            <BandRadar dimensions={latestDims} />
          </div>
        )}

        <div className={BLOCK}>
          <h2 className={BLOCK_H2}>Target Band</h2>
          <p className="muted">设定目标分（0–9，步进 0.5）；差距由最新四维对照计算。</p>
          <div className="my-2.5 mb-3.5 flex items-center gap-2.5">
            <input
              className="w-[90px] rounded-[10px] border border-line px-3 py-2.5 font-mono text-base font-semibold text-ink-strong transition-colors duration-150 focus:border-accent-bright focus:outline-none focus:ring-2 focus:ring-accent-soft"
              type="number"
              min="0"
              max="9"
              step="0.5"
              value={targetInput}
              onChange={(e) => setTargetInput(e.target.value)}
              aria-label="Target band"
            />
            <button
              type="button"
              className="btn-primary"
              disabled={saveState === 'saving' || targetInput === ''}
              onClick={() => saveTarget(Number(targetInput))}
            >
              Save
            </button>
            <button
              type="button"
              className="btn-ghost"
              disabled={saveState === 'saving' || data.target_band == null}
              onClick={() => {
                setTargetInput('')
                saveTarget(null) // null = 清除（§6.4）
              }}
            >
              Clear
            </button>
          </div>
          {saveState && saveState !== 'saving' && saveState !== 'saved' && (
            <p className="form-error">{saveState}</p>
          )}
          {gapList ? (
            <div className="flex flex-wrap gap-2">
              {gapList.map(({ label, value, text }) => {
                const reached = value != null && value <= 0
                return (
                  <span
                    key={label}
                    className={`rounded-full border px-3 py-2 font-mono text-[13px] leading-none ${
                      reached
                        ? 'border-accent-line bg-accent-soft text-accent [&_strong]:text-accent'
                        : 'border-line text-ink [&_strong]:text-ink-strong'
                    }`}
                    title={reached ? '已达/超目标' : '距目标差值'}
                  >
                    {label} <strong>{text}</strong>
                  </span>
                )
              })}
            </div>
          ) : (
            <p className="muted">
              {data.target_band == null
                ? '未设定目标——保存后这里显示与最新四维的差距。'
                : '还没有 Mock Exam 报告——完成一次方式 A 后这里显示差距。'}
            </p>
          )}
        </div>
      </div>

      {fluency_series.length > 0 && (
        <div className={BLOCK}>
          <h2 className={BLOCK_H2}>Fluency Trends</h2>
          <p className="muted">全模式可比的客观信号（最近 {fluency_series.length} 次完成会话）。</p>
          <div className="mt-3 grid grid-cols-[repeat(auto-fit,minmax(260px,1fr))] gap-x-7 gap-y-5">
            {FLUENCY_METRICS.map(({ key, label, desc, fmt }) => {
              const latest = [...fluency_series].reverse().find((p) => typeof p[key] === 'number')
              return (
                <div key={key}>
                  <p className="m-0 flex items-baseline justify-between">
                    <span className="font-mono text-[13px] font-semibold tracking-[0.04em] text-ink-strong">
                      {label}
                    </span>
                    <span className="font-mono text-lg font-bold text-accent">
                      {latest ? fmt(latest[key]) : '—'}
                    </span>
                  </p>
                  <p className="muted mb-1.5 mt-0.5 text-[12.5px]">{desc}</p>
                  <ResponsiveContainer width="100%" height={120}>
                    <LineChart data={fluency_series} margin={{ top: 4, right: 8, bottom: 0, left: -22 }}>
                      <XAxis dataKey="date" tickFormatter={tickDate} tick={{ fontSize: 10 }} />
                      {/* 整数刻度：WPM 量级 ~100，一位小数会把 "100.0" 挤出可视宽度 */}
                      <YAxis
                        tick={{ fontSize: 10 }}
                        width={46}
                        tickFormatter={(v) => String(Math.round(v * 100) / 100)}
                      />
                      <Tooltip labelFormatter={tickDate} />
                      <Line
                        type="monotone"
                        dataKey={key}
                        stroke="#0d9c6e"
                        strokeWidth={1.6}
                        dot={{ r: 2 }}
                        connectNulls
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </section>
  )
}
