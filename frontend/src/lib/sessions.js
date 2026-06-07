// F5 Library / Review 的纯函数层（DOM-free 可测）。契约：SCHEMA §6.2 的
// GET /sessions 行 + §6.4 /progress（handoff 007）。展示约定：标题/标签
// 简洁英文，解释性文字中文（FRONTEND.md §4）。
import { IELTS_PARTS, scenarioLabel } from './modes.js'
import { DIMENSION_META } from './report.js'

// 会话行 → 列表标题（与 Live/Record 页眉一致的叫法）
export function sessionTitle({ mode, sub_mode, scenario_case }) {
  if (mode === 'scenario') return `Scenario · ${scenarioLabel(scenario_case)}`
  if (mode === 'ielts' && sub_mode === 'exam') return 'IELTS · Mock Exam'
  const part = IELTS_PARTS.find((p) => p.value === sub_mode)
  if (part) return `IELTS · ${part.label}`
  return mode ?? '—' // 契约外行兜底，不炸列表
}

// 摘要分：方式 A 有 band 优先；其余模式退 WPM；都没有（未出报告）'—'
export function summaryScore({ overall_band, wpm }) {
  if (typeof overall_band === 'number') return `Band ${overall_band.toFixed(1)}`
  if (typeof wpm === 'number') return `${Math.round(wpm)} WPM`
  return '—'
}

// 列表展示策略（handoff 007 由前端定）：completed/failed/processing 展示
// （failed 打标、processing 标评测中可点进轮询页）；live/recording 是进行中
// 瞬态（弃局残留/并行会话）不进历史列表。
export function sessionVisible({ status }) {
  return status === 'completed' || status === 'failed' || status === 'processing'
}

// 状态标签：completed 无标签；其余给短英文标签（样式按 kind 区分）
export function statusTag({ status }) {
  if (status === 'failed') return { kind: 'failed', text: 'Failed' }
  if (status === 'processing') return { kind: 'processing', text: 'Processing' }
  return null
}

// ISO 时间 → 列表友好显示（本地时区，"M/D HH:mm"）；非法输入回退原值
export function formatStartedAt(iso) {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return String(iso ?? '—')
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

// latest_bands（§6.4 扁平字段）→ BandRadar 期望的 dimensions shape 适配
export function latestToDimensions(latest) {
  if (!latest) return null
  return {
    fluency_coherence: { band: latest.fc_band ?? null },
    lexical_resource: { band: latest.lr_band ?? null },
    grammatical_range_accuracy: { band: latest.gra_band ?? null },
    pronunciation: { band: latest.pron_band ?? null },
  }
}

// gap（target − latest，正=还差/负=已超）→ 展示行 [{label, value, text}]
// 缺单维该维 null（text '—'）；整体 null 由调用方挡（不渲染 gap 区）
export function gapRows(gap) {
  if (!gap) return null
  const rows = [
    { key: 'overall_band', label: 'Overall' },
    ...DIMENSION_META.map(({ key, short }) => ({ key: keyToGapField(key), label: short })),
  ]
  return rows.map(({ key, label }) => {
    const v = gap[key]
    const has = typeof v === 'number' && Number.isFinite(v)
    return {
      label,
      value: has ? v : null,
      text: has ? (v > 0 ? `+${v.toFixed(1)}` : v.toFixed(1)) : '—',
    }
  })
}

// report.js 的维度 key → /progress gap 的扁平字段名
function keyToGapField(dimensionKey) {
  return {
    fluency_coherence: 'fc_band',
    lexical_resource: 'lr_band',
    grammatical_range_accuracy: 'gra_band',
    pronunciation: 'pron_band',
  }[dimensionKey]
}

// series 的 date（ISO）→ 横轴刻度 "M/D"
export function tickDate(iso) {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return `${d.getMonth() + 1}/${d.getDate()}`
}

// 流利度趋势的四条线（error_rate 为 §6.4 新增可选线）：
// 各指标量纲不同 → Review 页按指标分四张小图，不挤一张
export const FLUENCY_METRICS = [
  { key: 'wpm', label: 'WPM', desc: '语速（词/分钟）', fmt: (v) => Math.round(v) },
  {
    key: 'silence_ratio',
    label: 'Silence %',
    desc: '静默占比',
    fmt: (v) => `${Math.round(v * 100)}%`,
  },
  { key: 'filler_pm', label: 'Fillers / min', desc: '填充词密度', fmt: (v) => v.toFixed(1) },
  {
    key: 'error_rate',
    label: 'Errors / 100w',
    desc: '每百词错误数',
    fmt: (v) => v.toFixed(1),
  },
]
