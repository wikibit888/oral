// Pure helpers for rendering the Report schema (app/report.py). Kept DOM-free so
// the band/mode logic is unit-testable without a renderer (report.test.js).

// The 4 IELTS dimensions, in display order. `key` matches the schema field;
// `label` is the page heading; `short` is the radar axis label.
// UI 约定（handoff 013，用户确认 2026-06-07，覆盖 2026-06-06「章节术语一律
// 英文」旧约定）：章节标题中文（练习概况/综合分析/优先改进项…），评分术语
// 保留英文原文（四维 label / Overall Band / Fossilization）；解释性文字
// （descriptor 分析、建议正文）保持中文，由 judge 数据决定。
export const DIMENSION_META = [
  { key: 'fluency_coherence', label: 'Fluency & Coherence', short: 'Fluency' },
  { key: 'lexical_resource', label: 'Lexical Resource', short: 'Lexical' },
  { key: 'grammatical_range_accuracy', label: 'Grammatical Range & Accuracy', short: 'Grammar' },
  { key: 'pronunciation', label: 'Pronunciation', short: 'Pronun.' },
]

// IELTS reports carry a band; Scenario reports set dimensions/overall_band null.
export function isIelts(report) {
  return report?.dimensions != null && report?.overall_band != null
}

// 雅思不可评（静音/非英语/录音问题）：unscorable=true 且 band 全 null，但诊断层
// 仍渲染。注意与情景对话区分 —— 情景 band 恒 null 但 unscorable=false，设计如此，
// 不能误入本分支（FRONTEND_HANDOFF §4 三渲染分支 / G3）。
export function isUnscorable(report) {
  return report?.unscorable === true
}

// Map the dimensions object to recharts radar rows: [{ dimension, band }].
// 缺维防御：judge 输出残缺时该轴置 null（recharts 跳点），不炸整页。
export function toRadarData(dimensions) {
  return DIMENSION_META.map(({ key, short }) => ({
    dimension: short,
    band: dimensions?.[key]?.band ?? null,
  }))
}

// null-safe 的 number.toFixed：band / vocabulary_diversity_pct 等字段在
// unscorable、方式 B（band 置空）或后端回填前可能缺位——渲染占位符而不是
// 让 `null.toFixed` 炸掉整页（review C2）。
export function fmtNum(value, digits = 1, fallback = '—') {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : fallback
}

// Seconds -> "m:ss" (>=1min) or "Ns" (<1min). For the practice summary stat.
export function formatDuration(seconds) {
  const s = Math.round(seconds)
  const m = Math.floor(s / 60)
  const rem = s % 60
  return m > 0 ? `${m}:${String(rem).padStart(2, '0')}` : `${rem}s`
}
