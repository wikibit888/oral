import { describe, it, expect } from 'vitest';
import {
  TARGET_SAMPLE_RATE,
  downsampleMono,
  floatTo16BitPCM,
  encodeWavFromInt16,
  encodeWav,
} from './wavEncoder.js';

function ascii(view, offset, len) {
  let s = '';
  for (let i = 0; i < len; i++) s += String.fromCharCode(view.getUint8(offset + i));
  return s;
}

describe('floatTo16BitPCM', () => {
  it('clamps the full-scale range to signed 16-bit', () => {
    const out = floatTo16BitPCM(new Float32Array([0, 1, -1, 2, -2, 0.5]));
    expect(out[0]).toBe(0);
    expect(out[1]).toBe(32767); // +1.0 -> max positive
    expect(out[2]).toBe(-32768); // -1.0 -> max negative
    expect(out[3]).toBe(32767); // clamp > 1
    expect(out[4]).toBe(-32768); // clamp < -1
    expect(out[5]).toBe(Math.trunc(0.5 * 0x7fff)); // Int16Array assignment truncates toward zero
  });
});

describe('downsampleMono', () => {
  it('halves length going 32k -> 16k and averages pairs', () => {
    const input = new Float32Array([0, 1, 0, 1, 0, 1, 0, 1]); // 8 samples
    const out = downsampleMono(input, 32000, 16000);
    expect(out.length).toBe(4);
    for (const v of out) expect(v).toBeCloseTo(0.5, 5); // each window avg of [0,1]
  });

  // 主路径（review W6）：浏览器 AudioContext 默认 48k，整段链路实际跑的是 48k→16k。
  it('48k -> 16k thirds the length and averages each triplet', () => {
    const input = new Float32Array([0, 0.3, 0.6, 1, 1, 1, -0.5, -0.5, 0.5])
    const out = downsampleMono(input, 48000, 16000)
    expect(out.length).toBe(3)
    expect(out[0]).toBeCloseTo(0.3, 5) // avg(0, 0.3, 0.6)
    expect(out[1]).toBeCloseTo(1, 5) // avg(1, 1, 1)
    expect(out[2]).toBeCloseTo(-1 / 6, 5) // avg(-0.5, -0.5, 0.5)
  })

  it('handles a non-integer ratio (44.1k -> 16k) with floor length', () => {
    const input = new Float32Array(4410) // 0.1s @ 44.1k
    const out = downsampleMono(input, 44100, 16000)
    expect(out.length).toBe(1600) // 0.1s @ 16k
  })

  it('returns the input untouched when rates match', () => {
    const input = new Float32Array([0.1, 0.2, 0.3]);
    expect(downsampleMono(input, 16000, 16000)).toBe(input);
  });

  it('refuses to upsample', () => {
    expect(() => downsampleMono(new Float32Array([0, 0]), 8000, 16000)).toThrow(/upsample/);
  });
});

describe('encodeWavFromInt16', () => {
  it('writes a valid 16k/16-bit/mono WAV header', () => {
    const pcm = new Int16Array([0, 100, -100, 32767]);
    const buf = encodeWavFromInt16(pcm, TARGET_SAMPLE_RATE);
    const view = new DataView(buf);
    const dataSize = pcm.length * 2;

    expect(buf.byteLength).toBe(44 + dataSize);
    expect(ascii(view, 0, 4)).toBe('RIFF');
    expect(view.getUint32(4, true)).toBe(36 + dataSize);
    expect(ascii(view, 8, 4)).toBe('WAVE');
    expect(ascii(view, 12, 4)).toBe('fmt ');
    expect(view.getUint32(16, true)).toBe(16); // PCM fmt size
    expect(view.getUint16(20, true)).toBe(1); // PCM
    expect(view.getUint16(22, true)).toBe(1); // mono
    expect(view.getUint32(24, true)).toBe(16000); // sample rate
    expect(view.getUint32(28, true)).toBe(16000 * 2); // byte rate
    expect(view.getUint16(32, true)).toBe(2); // block align
    expect(view.getUint16(34, true)).toBe(16); // bits/sample
    expect(ascii(view, 36, 4)).toBe('data');
    expect(view.getUint32(40, true)).toBe(dataSize);
    // samples are little-endian int16 right after the header
    expect(view.getInt16(44, true)).toBe(0);
    expect(view.getInt16(46, true)).toBe(100);
    expect(view.getInt16(48, true)).toBe(-100);
    expect(view.getInt16(50, true)).toBe(32767);
  });
});

describe('encodeWav (end to end)', () => {
  it('downsamples then encodes, sizing the buffer to the target rate', () => {
    const input = new Float32Array(3200); // 0.1s @ 32k
    const buf = encodeWav(input, 32000, 16000);
    expect(buf.byteLength).toBe(44 + 1600 * 2); // 0.1s @ 16k = 1600 samples
    const view = new DataView(buf);
    expect(view.getUint32(24, true)).toBe(16000);
  });

  it('48k 主路径：0.1s 采集 → 1600 样本 16k WAV', () => {
    const input = new Float32Array(4800); // 0.1s @ 48k
    const buf = encodeWav(input, 48000, 16000);
    expect(buf.byteLength).toBe(44 + 1600 * 2);
    const view = new DataView(buf);
    expect(view.getUint32(24, true)).toBe(16000);
  });
});
