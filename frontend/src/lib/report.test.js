import { describe, it, expect } from 'vitest'
import { fmtNum, isIelts, isUnscorable, toRadarData, formatDuration, DIMENSION_META } from './report.js'
import {
  ieltsModuleReport,
  ieltsReport,
  scenarioReport,
  unscorableReport,
} from '../fixtures/reportFixtures.js'

describe('isIelts', () => {
  it('is true when dimensions + overall_band are present', () => {
    expect(isIelts(ieltsReport)).toBe(true)
  })
  it('is false for scenario (null band)', () => {
    expect(isIelts(scenarioReport)).toBe(false)
  })
  it('is false for nullish input', () => {
    expect(isIelts(null)).toBe(false)
    expect(isIelts(undefined)).toBe(false)
  })
})

// G3 三渲染分支的核心区分：雅思不可评 vs 情景「设计上无 band」都 band 全 null，
// 只能靠 unscorable 标志位分流，不能混。
describe('isUnscorable', () => {
  it('is true only for the unscorable report', () => {
    expect(isUnscorable(unscorableReport)).toBe(true)
    expect(isIelts(unscorableReport)).toBe(false)
  })
  it('scenario（band null 但设计如此）不得误入 unscorable 分支', () => {
    expect(isUnscorable(scenarioReport)).toBe(false)
  })
  it('is false for normal ielts / nullish / missing field', () => {
    expect(isUnscorable(ieltsReport)).toBe(false)
    expect(isUnscorable(null)).toBe(false)
    expect(isUnscorable({})).toBe(false)
  })
})

describe('toRadarData', () => {
  it('returns the 4 dimensions in order with their bands', () => {
    const rows = toRadarData(ieltsReport.dimensions)
    expect(rows).toHaveLength(4)
    expect(rows.map((r) => r.dimension)).toEqual(DIMENSION_META.map((d) => d.short))
    expect(rows[0].band).toBe(ieltsReport.dimensions.fluency_coherence.band)
    expect(rows[3].band).toBe(ieltsReport.dimensions.pronunciation.band)
  })
})

describe('formatDuration', () => {
  it('formats sub-minute as seconds', () => {
    expect(formatDuration(42.4)).toBe('42s')
  })
  it('formats minutes as m:ss with zero-padding', () => {
    expect(formatDuration(132.4)).toBe('2:12')
    expect(formatDuration(65)).toBe('1:05')
  })
})

// review C2：band / vocabulary_diversity_pct 可能为 null（unscorable、方式 B、
// 回填前），fmtNum 必须给占位符而不是抛 TypeError。
describe('fmtNum', () => {
  it('formats finite numbers to 1 decimal by default', () => {
    expect(fmtNum(6.5)).toBe('6.5')
    expect(fmtNum(44)).toBe('44.0')
    expect(fmtNum(0)).toBe('0.0')
  })
  it('falls back on null / undefined / NaN / non-number', () => {
    expect(fmtNum(null)).toBe('—')
    expect(fmtNum(undefined)).toBe('—')
    expect(fmtNum(NaN)).toBe('—')
    expect(fmtNum('6.5')).toBe('—')
  })
})

// 情景报告结构契约 pin（handoff 014 / app/report.py Diagnostics）：summary 仅
// 情景非空、雅思恒 null（显式 null 非 undefined，防两种缺位行为分叉）；情景
// rewrites 后端强制空列表。渲染端按数据显隐：rewrites 空→改写示范整节不出，
// summary null→总结节不出。
describe('diagnostics.summary / rewrites fixture shape（handoff 014）', () => {
  it('情景：summary 非空中文段落 + rewrites 空列表', () => {
    expect(typeof scenarioReport.diagnostics.summary).toBe('string')
    expect(scenarioReport.diagnostics.summary.length).toBeGreaterThan(0)
    expect(scenarioReport.diagnostics.rewrites).toEqual([])
  })
  it('雅思 A/B 与 unscorable：summary 显式 null（非 undefined）', () => {
    expect(ieltsReport.diagnostics.summary).toBeNull()
    expect(ieltsModuleReport.diagnostics.summary).toBeNull()
    expect(unscorableReport.diagnostics.summary).toBeNull()
  })
  it('雅思照旧产出 rewrites；unscorable 空列表（隐藏分支受益场景）', () => {
    expect(ieltsReport.diagnostics.rewrites.length).toBeGreaterThan(0)
    expect(unscorableReport.diagnostics.rewrites).toEqual([])
  })
})

// 缺维防御：judge 输出残缺时雷达该轴置 null，不抛错。
describe('toRadarData with missing dimensions', () => {
  it('maps missing/null dims to null band', () => {
    const rows = toRadarData({ fluency_coherence: { band: 6 } })
    expect(rows[0].band).toBe(6)
    expect(rows[1].band).toBeNull()
    expect(rows[3].band).toBeNull()
  })
  it('survives null dimensions object', () => {
    expect(toRadarData(null)).toHaveLength(4)
  })
})
