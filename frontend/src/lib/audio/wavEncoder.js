// Pure, browser+node-safe helpers that turn captured Float32 audio into a
// 16kHz / 16-bit / mono PCM WAV — the exact format `POST /recordings` expects
// (CLAUDE.md 音频规范). No DOM / AudioContext here on purpose: keeps the byte
// math unit-testable (see wavEncoder.test.js) and reusable by F3 + F6.

export const TARGET_SAMPLE_RATE = 16000;

// Downsample a mono Float32 buffer from inputRate to targetRate by averaging the
// source samples that fall into each output window. Averaging (vs naive picking)
// acts as a cheap anti-alias low-pass — good enough for speech.
export function downsampleMono(input, inputRate, targetRate = TARGET_SAMPLE_RATE) {
  if (targetRate === inputRate) return input;
  if (targetRate > inputRate) {
    throw new Error(`refusing to upsample (${inputRate} -> ${targetRate})`);
  }
  const ratio = inputRate / targetRate;
  const outLength = Math.floor(input.length / ratio);
  const out = new Float32Array(outLength);
  for (let i = 0; i < outLength; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.min(Math.floor((i + 1) * ratio), input.length);
    let sum = 0;
    let count = 0;
    for (let j = start; j < end; j++) {
      sum += input[j];
      count++;
    }
    out[i] = count > 0 ? sum / count : 0;
  }
  return out;
}

// Clamp Float32 [-1, 1] to signed 16-bit PCM.
export function floatTo16BitPCM(input) {
  const out = new Int16Array(input.length);
  for (let i = 0; i < input.length; i++) {
    const s = Math.max(-1, Math.min(1, input[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out;
}

function writeAscii(view, offset, str) {
  for (let i = 0; i < str.length; i++) {
    view.setUint8(offset + i, str.charCodeAt(i));
  }
}

// Wrap 16-bit mono PCM samples in a 44-byte WAV header -> ArrayBuffer.
export function encodeWavFromInt16(pcm16, sampleRate = TARGET_SAMPLE_RATE) {
  const bytesPerSample = 2;
  const blockAlign = bytesPerSample; // mono => 1 channel * 2 bytes
  const byteRate = sampleRate * blockAlign;
  const dataSize = pcm16.length * bytesPerSample;
  const buffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buffer);

  writeAscii(view, 0, 'RIFF');
  view.setUint32(4, 36 + dataSize, true); // RIFF chunk size
  writeAscii(view, 8, 'WAVE');
  writeAscii(view, 12, 'fmt ');
  view.setUint32(16, 16, true); // fmt chunk size (PCM)
  view.setUint16(20, 1, true); // audio format = PCM
  view.setUint16(22, 1, true); // channels = mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, byteRate, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, 16, true); // bits per sample
  writeAscii(view, 36, 'data');
  view.setUint32(40, dataSize, true);
  for (let i = 0; i < pcm16.length; i++) {
    view.setInt16(44 + i * 2, pcm16[i], true);
  }
  return buffer;
}

// Full path: captured Float32 @ inputRate -> 16k mono 16-bit WAV ArrayBuffer.
export function encodeWav(float32Mono, inputRate, targetRate = TARGET_SAMPLE_RATE) {
  const down = downsampleMono(float32Mono, inputRate, targetRate);
  const pcm16 = floatTo16BitPCM(down);
  return encodeWavFromInt16(pcm16, targetRate);
}

// Browser-only convenience: same as encodeWav but returns a Blob ready to upload.
export function encodeWavBlob(float32Mono, inputRate, targetRate = TARGET_SAMPLE_RATE) {
  return new Blob([encodeWav(float32Mono, inputRate, targetRate)], { type: 'audio/wav' });
}
