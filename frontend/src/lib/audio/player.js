// 24k PCM 播放队列（F6 下行，handoff 001）。Live 输出 24kHz/16-bit/mono 裸帧：
// Int16 → Float32 → AudioBuffer 按时间轴顺播；收到 `interrupted` 调 flush()
// 立即停掉所有已排程源（含未开播的）—— barge-in 闭环，否则已缓冲音频会把
// "考官"播完，打断听感断链（FRONTEND.md §3）。

// 纯函数拆出便于 vitest（无 AudioContext 依赖）
export function int16ToFloat32(arrayBuffer) {
  const pcm = new Int16Array(arrayBuffer)
  const out = new Float32Array(pcm.length)
  for (let i = 0; i < pcm.length; i++) out[i] = pcm[i] / 0x8000
  return out
}

export class PcmPlayer {
  constructor({ sampleRate = 24000, onIdle = null } = {}) {
    this.onIdle = onIdle // 队列播空回调（考官说话指示熄灭）
    this._rate = sampleRate // PCM 数据的真实采样率（buffer 按它标记）
    this._ctx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate })
    this._nextTime = 0
    this._sources = new Set()
    // 电平分接口（Batch 4 Live 波形）：source → analyser → destination；
    // 防御式——环境无 createAnalyser（老 fake/老浏览器）时直连 destination，
    // level() 恒 0，播放路径不受影响。
    this._analyser = this._ctx.createAnalyser?.() ?? null
    if (this._analyser) {
      this._analyser.fftSize = 256
      this._analyser.connect(this._ctx.destination)
      this._levelBuf = new Uint8Array(this._analyser.fftSize)
    }
  }

  enqueue(arrayBuffer) {
    const f32 = int16ToFloat32(arrayBuffer)
    if (f32.length === 0) return
    // buffer 必须按数据本身的 24k 标记，不能用 ctx.sampleRate：Safari 会把
    // AudioContext 钳到设备原生 44.1k/48k，按 ctx 标记会 2 倍速播放（review W2）；
    // 标对采样率后浏览器自行重采样到设备
    const buf = this._ctx.createBuffer(1, f32.length, this._rate)
    buf.copyToChannel(f32, 0)
    const src = this._ctx.createBufferSource()
    src.buffer = buf
    src.connect(this._analyser ?? this._ctx.destination)
    src.onended = () => {
      this._sources.delete(src)
      if (this._sources.size === 0) this.onIdle?.()
    }
    // 帧首尾相接排程：晚到的帧接在上一帧结束点，避免重叠或空隙
    const t = Math.max(this._ctx.currentTime, this._nextTime)
    src.start(t)
    this._nextTime = t + buf.duration
    this._sources.add(src)
  }

  // barge-in：清空队列 + 停掉一切已排程源
  flush() {
    for (const s of this._sources) {
      s.onended = null
      try {
        s.stop()
      } catch {
        // 已自然结束的源 stop 会抛，忽略
      }
    }
    this._sources.clear()
    this._nextTime = 0
    this.onIdle?.()
  }

  get speaking() {
    return this._sources.size > 0
  }

  // 当前播放电平 0..1（time-domain RMS，128 = 静音中线）；无 analyser 恒 0。
  level() {
    if (!this._analyser) return 0
    this._analyser.getByteTimeDomainData(this._levelBuf)
    let sum = 0
    for (let i = 0; i < this._levelBuf.length; i++) {
      const d = (this._levelBuf[i] - 128) / 128
      sum += d * d
    }
    // RMS 0..1；×3 增益让正常语音占满条幅（语音 RMS 远低于满刻度正弦）
    return Math.min(1, Math.sqrt(sum / this._levelBuf.length) * 3)
  }

  async close() {
    this.flush()
    try {
      await this._ctx.close()
    } catch {
      // already closed — fine
    }
  }
}
