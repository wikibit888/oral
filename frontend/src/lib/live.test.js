import { describe, it, expect } from 'vitest'
import {
  PART_STAGES,
  appendDelta,
  buildLiveUrl,
  createFrameBatcher,
  formatLatency,
  normalizeTurn,
  parseEvent,
  partStage,
  pttReducer,
  validateLiveParams,
} from './live.js'

describe('validateLiveParams（契约 SCHEMA §6.1）', () => {
  it('ielts_a 不需要 case；scenario 必须带', () => {
    expect(validateLiveParams({ mode: 'ielts_a', caseId: null })).toBeNull()
    expect(validateLiveParams({ mode: 'scenario', caseId: 'ordering' })).toBeNull()
    expect(validateLiveParams({ mode: 'scenario', caseId: null })).toMatch(/case/)
  })

  it('mode 缺失/非法挡住', () => {
    expect(validateLiveParams({ mode: null, caseId: null })).toMatch(/mode/)
    expect(validateLiveParams({ mode: 'ielts', caseId: null })).toMatch(/mode/)
  })
})

describe('buildLiveUrl', () => {
  const loc = { protocol: 'http:', host: 'localhost:5173' }
  it('拼出代理路径 + query；https → wss', () => {
    expect(buildLiveUrl({ mode: 'ielts_a' }, loc)).toBe('ws://localhost:5173/ws/live?mode=ielts_a')
    expect(buildLiveUrl({ mode: 'scenario', caseId: 'ordering', turn: 'natural' }, loc)).toBe(
      'ws://localhost:5173/ws/live?mode=scenario&case=ordering&turn=natural',
    )
    expect(buildLiveUrl({ mode: 'ielts_a' }, { protocol: 'https:', host: 'x.app' })).toBe(
      'wss://x.app/ws/live?mode=ielts_a',
    )
  })

  it('turn=ptt 建链 pin（handoff 004：PTT 关 VAD，turn_end 显式断轮）', () => {
    expect(buildLiveUrl({ mode: 'ielts_a', turn: 'ptt' }, loc)).toBe(
      'ws://localhost:5173/ws/live?mode=ielts_a&turn=ptt',
    )
  })
})

describe('parseEvent', () => {
  it('合法事件透传，非 JSON / 无 type 归 null', () => {
    expect(parseEvent('{"type":"interrupted"}')).toEqual({ type: 'interrupted' })
    expect(parseEvent('not json')).toBeNull()
    expect(parseEvent('{"x":1}')).toBeNull()
  })

  it('latency_ms 事件 shape pin（handoff 004：value 为毫秒整数）', () => {
    expect(parseEvent('{"type":"latency_ms","value":912}')).toEqual({
      type: 'latency_ms',
      value: 912,
    })
  })

  it('方式 A 导演事件 shape pin（handoff 005）', () => {
    expect(parseEvent('{"type":"part_change","part":"p2_prep"}')).toEqual({
      type: 'part_change',
      part: 'p2_prep',
    })
    expect(
      parseEvent('{"type":"present_cue_card","card":{"id":"p2-03","text":"Describe…","bullets":["a","b"]}}'),
    ).toEqual({
      type: 'present_cue_card',
      card: { id: 'p2-03', text: 'Describe…', bullets: ['a', 'b'] },
    })
    expect(parseEvent('{"type":"start_prep_timer","seconds":60}')).toEqual({
      type: 'start_prep_timer',
      seconds: 60,
    })
  })
})

describe('partStage（part_change → 进度条阶段，IELTS.md §2）', () => {
  it('p1/p3 直映；p2 三态合并 Part 2；done 特殊态', () => {
    expect(partStage('p1')).toBe('Part 1')
    expect(partStage('p2_prep')).toBe('Part 2')
    expect(partStage('p2_talk')).toBe('Part 2')
    expect(partStage('p2_followup')).toBe('Part 2')
    expect(partStage('p3')).toBe('Part 3')
    expect(partStage('done')).toBe('done')
  })

  it('已撤回的收尾态（009 终版不再下发）按契约外值归 null', () => {
    expect(partStage('p1_closing')).toBeNull()
    expect(partStage('p3_closing')).toBeNull()
  })

  it('契约外/缺失归 null（scenario 无 part 事件不出进度条）', () => {
    expect(partStage('p4')).toBeNull()
    expect(partStage(undefined)).toBeNull()
  })

  it('PART_STAGES 顺序 pin（进度条渲染序）', () => {
    expect(PART_STAGES).toEqual(['Part 1', 'Part 2', 'Part 3'])
  })
})

describe('normalizeTurn（turn=ptt|natural，SCHEMA §6.1）', () => {
  it('ptt 透传；其余一律落 natural（默认值）', () => {
    expect(normalizeTurn('ptt')).toBe('ptt')
    expect(normalizeTurn('natural')).toBe('natural')
    expect(normalizeTurn(null)).toBe('natural')
    expect(normalizeTurn('junk')).toBe('natural')
  })
})

describe('pttReducer（PTT 显式轮次状态机，handoff 004）', () => {
  it('主循环：idle → pressed → waiting → turn_complete 解锁回 idle', () => {
    let s = 'idle'
    s = pttReducer(s, 'press')
    expect(s).toBe('pressed')
    s = pttReducer(s, 'release')
    expect(s).toBe('waiting')
    s = pttReducer(s, 'turn_complete')
    expect(s).toBe('idle')
  })

  it('非法迁移原状返回：waiting 期按键锁死、乱序事件不脏状态', () => {
    expect(pttReducer('waiting', 'press')).toBe('waiting') // turn_complete 前不解锁
    expect(pttReducer('idle', 'release')).toBe('idle') // 未按先松
    expect(pttReducer('pressed', 'turn_complete')).toBe('pressed') // 考官旧轮完成不打断按住
    expect(pttReducer('idle', 'turn_complete')).toBe('idle') // natural 轮次事件无副作用
  })

  it('reset 无条件回 idle（重连/切模式）', () => {
    expect(pttReducer('pressed', 'reset')).toBe('idle')
    expect(pttReducer('waiting', 'reset')).toBe('idle')
  })
})

describe('formatLatency（延迟徽章，FRONTEND §3）', () => {
  it('ptt 精确值；natural 标 ≈ 近似（含 VAD 判停耗时）', () => {
    expect(formatLatency(912, 'ptt')).toBe('912 ms')
    expect(formatLatency(2300, 'natural')).toBe('≈ 2300 ms')
  })

  it('非数值（事件畸形）归 null 不渲染', () => {
    expect(formatLatency(undefined, 'ptt')).toBeNull()
    expect(formatLatency('912', 'ptt')).toBeNull()
    expect(formatLatency(NaN, 'natural')).toBeNull()
  })
})

describe('appendDelta（双人转写流合并）', () => {
  it('同 role 连续增量并入同一气泡', () => {
    let t = []
    t = appendDelta(t, { role: 'user', text: 'Hel' })
    t = appendDelta(t, { role: 'user', text: 'lo' })
    expect(t).toEqual([{ role: 'user', text: 'Hello' }])
  })

  it('role 切换开新气泡', () => {
    let t = [{ role: 'user', text: 'Hello' }]
    t = appendDelta(t, { role: 'examiner', text: 'Hi' })
    t = appendDelta(t, { role: 'user', text: 'Yes' })
    expect(t.map((b) => b.role)).toEqual(['user', 'examiner', 'user'])
  })
})

describe('createFrameBatcher（上行合批）', () => {
  it('攒满阈值才发，且按序拼接', () => {
    const sent = []
    const b = createFrameBatcher((m) => sent.push(m), 6)
    b.push(new Int16Array([1, 2]))
    b.push(new Int16Array([3, 4]))
    expect(sent.length).toBe(0) // 4 < 6，还没发
    b.push(new Int16Array([5, 6])) // 6 ≥ 6，触发
    expect(sent.length).toBe(1)
    expect([...sent[0]]).toEqual([1, 2, 3, 4, 5, 6])
  })

  it('flush 清尾包；空时 no-op', () => {
    const sent = []
    const b = createFrameBatcher((m) => sent.push(m), 100)
    b.flush()
    expect(sent.length).toBe(0)
    b.push(new Int16Array([7]))
    b.flush()
    expect([...sent[0]]).toEqual([7])
  })

  it('自动发批后状态清零，续推不带旧数据（review W4）', () => {
    const sent = []
    const b = createFrameBatcher((m) => sent.push(m), 3)
    b.push(new Int16Array([1, 2, 3])) // 攒满自动触发
    expect([...sent[0]]).toEqual([1, 2, 3])
    b.push(new Int16Array([4, 5]))    // 低于阈值，压着
    expect(sent.length).toBe(1)
    b.flush()                         // End 路径：排空尾包（review W1 的依赖行为）
    expect(sent.length).toBe(2)
    expect([...sent[1]]).toEqual([4, 5])
  })
})
