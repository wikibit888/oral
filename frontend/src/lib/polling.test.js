import { describe, it, expect } from 'vitest'
import { classifyStatus, STAGES, stageIndex, STATUS_TEXT } from './polling.js'

// pin 后端状态机契约（SCHEMA §5.1，PR #16 枚举迁移后的现行版）：
// live | recording | processing → completed | failed
describe('classifyStatus', () => {
  it('live / recording / uploaded / processing 继续轮询', () => {
    expect(classifyStatus('live')).toBe('continue')
    expect(classifyStatus('recording')).toBe('continue')
    expect(classifyStatus('uploaded')).toBe('continue')
    expect(classifyStatus('processing')).toBe('continue')
  })

  it('completed / failed 是终态；旧代 done / ready 同义兼容（纵深防御）', () => {
    expect(classifyStatus('completed')).toBe('done')
    expect(classifyStatus('done')).toBe('done')
    expect(classifyStatus('ready')).toBe('done')
    expect(classifyStatus('failed')).toBe('failed')
  })

  it('契约外状态归 unknown，不死轮询', () => {
    expect(classifyStatus('what')).toBe('unknown')
    expect(classifyStatus(undefined)).toBe('unknown')
  })

  it('每个 continue 状态都有兜底文案', () => {
    for (const s of ['live', 'uploaded', 'processing', 'recording']) {
      expect(STATUS_TEXT[s]).toBeTruthy()
    }
  })
})

// pin 流水线 stage 契约：transcribe → signals → judge（SCHEMA §6 / R4 真分步进度）
describe('stageIndex', () => {
  it('processing + 契约内 stage → 对应步下标', () => {
    expect(STAGES.map((s) => s.key)).toEqual(['transcribe', 'signals', 'judge'])
    expect(stageIndex('processing', 'transcribe')).toBe(0)
    expect(stageIndex('processing', 'signals')).toBe(1)
    expect(stageIndex('processing', 'judge')).toBe(2)
  })

  it('uploaded 排队 / stage 缺失或契约外 → -1，降级整体文案', () => {
    expect(stageIndex('uploaded', 'transcribe')).toBe(-1)
    expect(stageIndex('processing', undefined)).toBe(-1)
    expect(stageIndex('processing', 'wat')).toBe(-1)
  })
})
