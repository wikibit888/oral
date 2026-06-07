import {
  encodeWavBlob,
  downsampleMono,
  floatTo16BitPCM,
  TARGET_SAMPLE_RATE,
} from './wavEncoder.js';
import workletUrl from './pcmWorkletProcessor.js?url';

// Mic -> AudioWorklet capture -> (on stop) 16k/16-bit/mono WAV Blob.
// Shared by F3 (recording upload) and F6 (live streaming via the onFrame hook).
//
// Why a worklet and not MediaRecorder: MediaRecorder yields webm/opus at the
// device rate — wrong container + rate for `POST /recordings`. Capturing raw
// Float32 and encoding ourselves is the only reliable way to hit the fixed
// 16k/16-bit/mono PCM contract (see TODO.frontend R2).
export class PcmRecorder {
  constructor({ targetSampleRate = TARGET_SAMPLE_RATE, onFrame = null } = {}) {
    this.targetSampleRate = targetSampleRate;
    this.onFrame = onFrame; // optional (Int16Array @ targetRate) => void, for F6 live streaming
    this._chunks = [];
    this._stream = null;
    this._ctx = null;
    this._node = null;
    this._source = null;
  }

  async start() {
    // 半途失败（如 addModule 拒载、worklet 不支持）必须释放已到手的资源，
    // 否则 mic 红点常亮 + AudioContext 泄漏，且调用方拿不到 recorder 引用没法兜底（review C1）。
    try {
      this._stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
      this._ctx = new (window.AudioContext || window.webkitAudioContext)();
      await this._ctx.audioWorklet.addModule(workletUrl);
      this._source = this._ctx.createMediaStreamSource(this._stream);
      this._node = new AudioWorkletNode(this._ctx, 'pcm-capture');
      this._node.port.onmessage = (e) => {
        const frame = e.data; // Float32Array @ ctx.sampleRate
        this._chunks.push(frame);
        if (this.onFrame) {
          const down = downsampleMono(frame, this._ctx.sampleRate, this.targetSampleRate);
          this.onFrame(floatTo16BitPCM(down));
        }
      };
      this._source.connect(this._node);
      // The processor never writes to its output, so the node emits silence.
      // Connecting it to destination just keeps the graph pulling render quanta
      // (no mic echo). Some engines run a sink-less graph; this is the safe path.
      this._node.connect(this._ctx.destination);
    } catch (err) {
      await this._release();
      throw err;
    }
  }

  // 释放全部音频资源（mic 轨、worklet 节点、AudioContext），幂等可重复调用。
  async _release() {
    if (this._node) this._node.port.onmessage = null;
    this._source?.disconnect();
    this._node?.disconnect();
    this._stream?.getTracks().forEach((t) => t.stop());
    try {
      await this._ctx?.close();
    } catch {
      // already closed — fine
    }
    this._stream = this._ctx = this._node = this._source = null;
  }

  // 暂停 / 恢复采集（F3 Pause/Resume）：挂起 AudioContext 后 worklet 停止出帧，
  // 恢复后无缝续录——不重建图、不丢已采样本，暂停期不产生静音填充。
  async pause() {
    await this._ctx?.suspend()
  }

  async resume() {
    await this._ctx?.resume()
  }

  // Returns { blob, durationS, sampleRate }. Safe to call once after start().
  async stop() {
    const sampleRate = this._ctx?.sampleRate ?? this.targetSampleRate;
    await this._release();

    const merged = mergeFloat32(this._chunks);
    const blob = encodeWavBlob(merged, sampleRate, this.targetSampleRate);
    const durationS = sampleRate > 0 ? merged.length / sampleRate : 0;
    this._chunks = [];
    return { blob, durationS, sampleRate };
  }
}

function mergeFloat32(chunks) {
  const total = chunks.reduce((n, c) => n + c.length, 0);
  const out = new Float32Array(total);
  let offset = 0;
  for (const c of chunks) {
    out.set(c, offset);
    offset += c.length;
  }
  return out;
}
