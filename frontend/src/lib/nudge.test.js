import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import {
  NUDGE_DELAYS_MS,
  NUDGE_VOICE_FRAMES,
  NUDGE_VOICE_LEVEL,
  createNudgeTimer,
} from './nudge.js'

// handoff 011：计时起点 = turn_complete 且播放队列排空；~10s→1 / 再~12s→2 /
// 再~15s→3 之后停发；人声/AI 播音/teaching 重置；PTT 只发 stage 1 且阈值翻倍。

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

// 模拟一段真实人声：连续达阈帧确认 + 一个静音帧落点（倒计时从落点起）
function speak(t) {
  for (let i = 0; i < NUDGE_VOICE_FRAMES; i++) t.voice(1)
  t.voice(0)
}

function make(opts = {}) {
  const sent = []
  const t = createNudgeTimer({ send: (m) => sent.push(m), ...opts })
  return { sent, t }
}

describe('createNudgeTimer（沉默分级探询，handoff 011）', () => {
  it('上行消息 shape pin：{"type":"nudge","stage":N}', () => {
    const { sent, t } = make()
    t.turnComplete()
    vi.advanceTimersByTime(NUDGE_DELAYS_MS[0])
    expect(sent).toEqual([{ type: 'nudge', stage: 1 }])
  })

  it('持续沉默升级链：10s→1、再 12s→2、再 15s→3，之后停发', () => {
    const { sent, t } = make()
    t.turnComplete()
    vi.advanceTimersByTime(10000)
    expect(sent.map((m) => m.stage)).toEqual([1])
    vi.advanceTimersByTime(12000)
    expect(sent.map((m) => m.stage)).toEqual([1, 2])
    vi.advanceTimersByTime(15000)
    expect(sent.map((m) => m.stage)).toEqual([1, 2, 3])
    vi.advanceTimersByTime(120000) // stage 3 之后不再升级
    expect(sent.length).toBe(3)
  })

  it('turn_complete 前不计时（考官开场期沉默不探询）', () => {
    const { sent, t } = make()
    t.playbackIdle()
    vi.advanceTimersByTime(60000)
    expect(sent.length).toBe(0)
  })

  it('AI 播音暂停倒计时（不清阶梯），排空后重新计满一段', () => {
    const { sent, t } = make()
    t.turnComplete()
    vi.advanceTimersByTime(9000)
    t.playbackStart() // 差 1s 时考官开口 → 取消
    vi.advanceTimersByTime(30000)
    expect(sent.length).toBe(0)
    t.playbackIdle() // 排空 → 重起 10s（不接续剩余 1s）
    vi.advanceTimersByTime(9999)
    expect(sent.length).toBe(0)
    vi.advanceTimersByTime(1)
    expect(sent.map((m) => m.stage)).toEqual([1])
  })

  it('nudge 语音播完继续沿阶梯升级（播音不重置 stage）', () => {
    const { sent, t } = make()
    t.turnComplete()
    vi.advanceTimersByTime(10000) // stage 1
    t.playbackStart() // stage 1 的探询语音
    t.playbackIdle()
    vi.advanceTimersByTime(12000) // 继续沉默 → stage 2（不是重发 1）
    expect(sent.map((m) => m.stage)).toEqual([1, 2])
  })

  it('真实人声重置阶梯：开口取消倒计时，话音落点重起且回 stage 1', () => {
    const { sent, t } = make()
    t.turnComplete()
    vi.advanceTimersByTime(10000)
    vi.advanceTimersByTime(12000) // 升到 stage 2
    expect(sent.map((m) => m.stage)).toEqual([1, 2])
    speak(t) // 用户开口 → 阶梯清零，落点重起
    vi.advanceTimersByTime(10000)
    expect(sent.map((m) => m.stage)).toEqual([1, 2, 1]) // 回到 stage 1
  })

  it('说话进行中不触发（上沿取消后，达阈帧持续期间无倒计时）', () => {
    const { sent, t } = make()
    t.turnComplete()
    for (let i = 0; i < NUDGE_VOICE_FRAMES; i++) t.voice(1) // 确认人声
    vi.advanceTimersByTime(60000) // 一直说（无静音帧）
    expect(sent.length).toBe(0)
  })

  it('单帧爆音/键盘瞬态不重置（未达连续帧数，倒计时照走）', () => {
    const { sent, t } = make()
    t.turnComplete()
    vi.advanceTimersByTime(5000)
    t.voice(1) // 一帧爆音
    t.voice(0)
    vi.advanceTimersByTime(5000) // 原倒计时未被打断：累计 10s 触发
    expect(sent.map((m) => m.stage)).toEqual([1])
  })

  it('底噪（阈下电平）不重置', () => {
    const { sent, t } = make()
    t.turnComplete()
    vi.advanceTimersByTime(5000)
    for (let i = 0; i < 200; i++) t.voice(NUDGE_VOICE_LEVEL * 0.5)
    vi.advanceTimersByTime(5000)
    expect(sent.map((m) => m.stage)).toEqual([1])
  })

  it('teaching 事件全量重置（用户在求助，阶梯清零重起）', () => {
    const { sent, t } = make()
    t.turnComplete()
    vi.advanceTimersByTime(22000) // stage 1 + 2
    t.teaching()
    vi.advanceTimersByTime(10000)
    expect(sent.map((m) => m.stage)).toEqual([1, 2, 1])
  })

  it('PTT：阈值翻倍只发 stage 1，之后不升级', () => {
    const { sent, t } = make({ ptt: true })
    t.turnComplete()
    vi.advanceTimersByTime(19999) // 10s × 2 翻倍
    expect(sent.length).toBe(0)
    vi.advanceTimersByTime(1)
    expect(sent).toEqual([{ type: 'nudge', stage: 1 }])
    vi.advanceTimersByTime(120000)
    expect(sent.length).toBe(1) // 永不到 stage 2
  })

  it('PTT：人声重置后仍可再发 stage 1', () => {
    const { sent, t } = make({ ptt: true })
    t.turnComplete()
    vi.advanceTimersByTime(20000)
    speak(t)
    vi.advanceTimersByTime(20000)
    expect(sent.map((m) => m.stage)).toEqual([1, 1])
  })

  it('stop() 终态：取消在途倒计时，之后一切输入 no-op', () => {
    const { sent, t } = make()
    t.turnComplete()
    vi.advanceTimersByTime(9000)
    t.stop()
    vi.advanceTimersByTime(60000)
    t.turnComplete()
    t.playbackIdle()
    t.teaching()
    vi.advanceTimersByTime(60000)
    expect(sent.length).toBe(0)
  })
})
