import { describe, it, expect } from 'vitest'
import {
  FLUENCY_METRICS,
  formatStartedAt,
  gapRows,
  latestToDimensions,
  sessionTitle,
  sessionVisible,
  statusTag,
  summaryScore,
  tickDate,
} from './sessions.js'

// pin GET /sessions 行的展示映射（SCHEMA §6.2 / handoff 007）
describe('sessionTitle', () => {
  it('三种模式形态全覆盖', () => {
    expect(sessionTitle({ mode: 'ielts', sub_mode: 'exam', scenario_case: null })).toBe(
      'IELTS · Mock Exam',
    )
    expect(sessionTitle({ mode: 'ielts', sub_mode: 'module_p2', scenario_case: null })).toBe(
      'IELTS · Part 2',
    )
    expect(sessionTitle({ mode: 'scenario', sub_mode: null, scenario_case: 'ordering' })).toBe(
      'Scenario · Ordering Food',
    )
  })

  it('契约外行兜底不炸', () => {
    expect(sessionTitle({ mode: 'ielts', sub_mode: 'module_p9' })).toBe('ielts')
    expect(sessionTitle({})).toBe('—')
  })
})

describe('summaryScore（方式 A band 优先，余退 WPM，无报告 —）', () => {
  it('band / wpm / null 三态', () => {
    expect(summaryScore({ overall_band: 6.5, wpm: 110 })).toBe('Band 6.5')
    expect(summaryScore({ overall_band: null, wpm: 97.6 })).toBe('98 WPM')
    expect(summaryScore({ overall_band: null, wpm: null })).toBe('—')
  })
})

describe('sessionVisible / statusTag（status 枚举 §5.1，展示策略 007 前端定）', () => {
  it('completed/failed/processing 展示；live/recording 瞬态隐藏', () => {
    expect(sessionVisible({ status: 'completed' })).toBe(true)
    expect(sessionVisible({ status: 'failed' })).toBe(true)
    expect(sessionVisible({ status: 'processing' })).toBe(true)
    expect(sessionVisible({ status: 'live' })).toBe(false)
    expect(sessionVisible({ status: 'recording' })).toBe(false)
  })

  it('failed/processing 打标，completed 无标签', () => {
    expect(statusTag({ status: 'failed' })).toEqual({ kind: 'failed', text: 'Failed' })
    expect(statusTag({ status: 'processing' })).toEqual({
      kind: 'processing',
      text: 'Processing',
    })
    expect(statusTag({ status: 'completed' })).toBeNull()
  })
})

describe('latestToDimensions（§6.4 latest_bands → BandRadar 适配）', () => {
  it('扁平字段映射四维 shape；缺维置 null；无 latest 整体 null', () => {
    expect(
      latestToDimensions({ date: 'x', overall_band: 6, fc_band: 6, lr_band: 5.5, gra_band: null, pron_band: 6 }),
    ).toEqual({
      fluency_coherence: { band: 6 },
      lexical_resource: { band: 5.5 },
      grammatical_range_accuracy: { band: null },
      pronunciation: { band: 6 },
    })
    expect(latestToDimensions(null)).toBeNull()
  })
})

describe('gapRows（target − latest：正=还差 负=已超，§6.4）', () => {
  it('Overall + 四维成行，正值带 +，缺维 —', () => {
    const rows = gapRows({ overall_band: 0.5, fc_band: -0.5, lr_band: 1.0, gra_band: null, pron_band: 0 })
    expect(rows.map((r) => r.label)).toEqual(['Overall', 'Fluency', 'Lexical', 'Grammar', 'Pronun.'])
    expect(rows[0].text).toBe('+0.5')
    expect(rows[1].text).toBe('-0.5')
    expect(rows[3].text).toBe('—')
    expect(rows[4].text).toBe('0.0')
  })

  it('整体 null（无目标或无 latest）→ null，调用方不渲染', () => {
    expect(gapRows(null)).toBeNull()
  })
})

describe('时间格式', () => {
  it('formatStartedAt 本地 M/D HH:mm；非法回退', () => {
    expect(formatStartedAt('2026-06-07T03:15:00')).toBe('6/7 03:15')
    expect(formatStartedAt('not a date')).toBe('not a date')
  })

  it('tickDate → M/D', () => {
    expect(tickDate('2026-06-07T03:15:00')).toBe('6/7')
  })
})

describe('FLUENCY_METRICS（§6.4 fluency_series 四指标，error_rate 新增）', () => {
  it('key 与契约字段一致，fmt 可用', () => {
    expect(FLUENCY_METRICS.map((m) => m.key)).toEqual([
      'wpm',
      'silence_ratio',
      'filler_pm',
      'error_rate',
    ])
    expect(FLUENCY_METRICS[1].fmt(0.234)).toBe('23%')
  })
})
