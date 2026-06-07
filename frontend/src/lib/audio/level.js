// 16-bit PCM 帧 → 0..1 归一电平（RMS）。
// fullScale=9000：16-bit RMS 经验满刻度（正常说话音量），Record 电平条
// 与 Live 波形共用（Batch 4 从 Record.jsx 内联抽出）。
export function rmsLevel16(int16, fullScale = 9000) {
  if (!int16 || int16.length === 0) return 0
  let sum = 0
  for (let i = 0; i < int16.length; i++) sum += int16[i] * int16[i]
  return Math.min(1, Math.sqrt(sum / int16.length) / fullScale)
}
