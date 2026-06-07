import { describe, it, expect } from 'vitest'
import { rmsLevel16 } from './level.js'

describe('rmsLevel16（PCM 帧 → 0..1 电平，Record 电平条 / Live 波形共用）', () => {
  it('静音帧归 0', () => {
    expect(rmsLevel16(new Int16Array(160))).toBe(0)
  })

  it('空帧/缺失帧归 0（不抛）', () => {
    expect(rmsLevel16(new Int16Array(0))).toBe(0)
    expect(rmsLevel16(null)).toBe(0)
  })

  it('满刻度（RMS=fullScale）夹到 1，超出不溢出', () => {
    const loud = new Int16Array(160).fill(9000)
    expect(rmsLevel16(loud)).toBe(1)
    const over = new Int16Array(160).fill(30000)
    expect(rmsLevel16(over)).toBe(1)
  })

  it('半刻度 ≈ 0.5（线性归一）', () => {
    const half = new Int16Array(160).fill(4500)
    expect(rmsLevel16(half)).toBeCloseTo(0.5, 5)
  })
})
