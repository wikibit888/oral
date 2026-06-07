import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { int16ToFloat32, PcmPlayer } from './player.js'

// pin 下行 24k PCM 裸帧 → Float32 的字节解释（LE int16 / 0x8000 归一化）
describe('int16ToFloat32', () => {
  it('满刻度与零点映射正确', () => {
    const pcm = new Int16Array([0, 32767, -32768, 16384])
    const out = int16ToFloat32(pcm.buffer)
    expect(out[0]).toBe(0)
    expect(out[1]).toBeCloseTo(0.99997, 4) // 32767/32768
    expect(out[2]).toBe(-1)
    expect(out[3]).toBeCloseTo(0.5, 5)
  })

  it('空帧返回空数组（enqueue 端直接丢弃）', () => {
    expect(int16ToFloat32(new ArrayBuffer(0)).length).toBe(0)
  })
})

// —— PcmPlayer（review W3：flush/barge-in 是契约关键路径，须有单测）—— //
// node 环境无 AudioContext：用最小假体 pin 排程/flush 行为
class FakeSource {
  constructor() {
    this.started = null
    this.stopped = false
    this.onended = null
    this.connected = null
  }
  connect(dst) {
    this.connected = dst
  }
  start(t) {
    this.started = t
  }
  stop() {
    this.stopped = true
  }
}

class FakeAnalyser {
  constructor() {
    this.fftSize = 0
    this.connected = null
    this.fill = 128 // time-domain 静音中线
  }
  connect(dst) {
    this.connected = dst
  }
  getByteTimeDomainData(buf) {
    buf.fill(this.fill)
  }
}

class FakeAudioContext {
  constructor({ sampleRate } = {}) {
    this.sampleRate = 48000 // 模拟 Safari 钳到设备原生采样率（≠ 请求的 24k）
    this.requestedRate = sampleRate
    this.currentTime = 0
    this.destination = {}
    this.createdBuffers = []
    this.sources = []
    this.analyser = null
    this.closed = false
  }
  createBuffer(channels, length, rate) {
    const buf = { channels, length, rate, duration: length / rate, copyToChannel() {} }
    this.createdBuffers.push(buf)
    return buf
  }
  createBufferSource() {
    const src = new FakeSource()
    this.sources.push(src)
    return src
  }
  createAnalyser() {
    this.analyser = new FakeAnalyser()
    return this.analyser
  }
  async close() {
    this.closed = true
  }
}

// 无 createAnalyser 的最小假体：pin 防御路径（直连 destination、level() 恒 0）
class BareAudioContext extends FakeAudioContext {
  createAnalyser = undefined
}

describe('PcmPlayer', () => {
  beforeEach(() => {
    vi.stubGlobal('window', { AudioContext: FakeAudioContext })
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  const frame = (n) => new Int16Array(n).buffer

  it('buffer 按数据真实 24k 标记，而非被钳过的 ctx.sampleRate（review W2）', () => {
    const p = new PcmPlayer()
    p.enqueue(frame(2400)) // 0.1s @ 24k
    const buf = p._ctx.createdBuffers[0]
    expect(buf.rate).toBe(24000) // ctx 是 48000——按 ctx 标会 2 倍速
    expect(buf.duration).toBeCloseTo(0.1, 5)
  })

  it('帧首尾相接排程：第二帧 start 在第一帧结束点', () => {
    const p = new PcmPlayer()
    p.enqueue(frame(2400)) // 0.1s
    p.enqueue(frame(4800)) // 0.2s
    const [s1, s2] = p._ctx.sources
    expect(s1.started).toBe(0)
    expect(s2.started).toBeCloseTo(0.1, 5)
    expect(p.speaking).toBe(true)
  })

  it('空帧 enqueue 是 no-op', () => {
    const p = new PcmPlayer()
    p.enqueue(new ArrayBuffer(0))
    expect(p._ctx.sources.length).toBe(0)
    expect(p.speaking).toBe(false)
  })

  it('flush（barge-in）：停掉全部已排程源、清队列、回调 onIdle、speaking 归 false', () => {
    const onIdle = vi.fn()
    const p = new PcmPlayer({ onIdle })
    p.enqueue(frame(2400))
    p.enqueue(frame(2400))
    p.flush()
    expect(p._ctx.sources.every((s) => s.stopped)).toBe(true)
    expect(p.speaking).toBe(false)
    expect(onIdle).toHaveBeenCalledTimes(1)
    // _nextTime 重置：flush 后新帧从当下排，不接在被清掉的旧时间轴上
    p.enqueue(frame(2400))
    expect(p._ctx.sources[2].started).toBe(p._ctx.currentTime)
  })

  it('空队列 flush 不抛且回调 onIdle', () => {
    const onIdle = vi.fn()
    const p = new PcmPlayer({ onIdle })
    expect(() => p.flush()).not.toThrow()
    expect(onIdle).toHaveBeenCalledTimes(1)
  })

  it('close 先 flush 再关 AudioContext', async () => {
    const p = new PcmPlayer()
    p.enqueue(frame(2400))
    await p.close()
    expect(p._ctx.sources[0].stopped).toBe(true)
    expect(p._ctx.closed).toBe(true)
  })

  // —— 电平分接口（Batch 4 Live 波形）—— //
  it('源接 analyser、analyser 接 destination；静音 level()=0、有信号 >0', () => {
    const p = new PcmPlayer()
    p.enqueue(frame(2400))
    expect(p._ctx.analyser).not.toBeNull()
    expect(p._ctx.sources[0].connected).toBe(p._ctx.analyser)
    expect(p._ctx.analyser.connected).toBe(p._ctx.destination)
    expect(p.level()).toBe(0) // 128 中线 = 静音
    p._ctx.analyser.fill = 192 // 偏移 0.5 → RMS 0.5×3 增益夹到 1
    expect(p.level()).toBeGreaterThan(0)
  })

  it('无 createAnalyser 环境防御：直连 destination、level() 恒 0', () => {
    vi.stubGlobal('window', { AudioContext: BareAudioContext })
    const p = new PcmPlayer()
    p.enqueue(frame(2400))
    expect(p._ctx.sources[0].connected).toBe(p._ctx.destination)
    expect(p.level()).toBe(0)
  })
})
