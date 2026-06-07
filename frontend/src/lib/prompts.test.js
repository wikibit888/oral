import { describe, it, expect } from 'vitest'
import { IELTS_PROMPTS, SCENARIO_PROMPTS, getPrompt } from './prompts.js'
import { IELTS_PARTS, SCENARIO_CASES } from './modes.js'

// 题目数据必须覆盖 modes.js 镜像的全部契约串 —— 漏一个就是录音页白屏。
describe('prompts 与契约串对齐', () => {
  it('每个雅思 Part 都有题目', () => {
    for (const p of IELTS_PARTS) {
      expect(IELTS_PROMPTS[p.value], `缺 ${p.value}`).toBeTruthy()
    }
  })

  it('每个情景 case 都有题目', () => {
    for (const c of SCENARIO_CASES) {
      expect(SCENARIO_PROMPTS[c.value], `缺 ${c.value}`).toBeTruthy()
    }
  })

  it('题目结构完整：questions/tasks/cueCard 三选一非空', () => {
    const all = [...Object.values(IELTS_PROMPTS), ...Object.values(SCENARIO_PROMPTS)]
    for (const p of all) {
      expect(p.title).toBeTruthy()
      expect(p.intro).toBeTruthy()
      const items = p.questions ?? p.tasks ?? p.cueCard?.bullets
      expect(items?.length, `${p.title} 无内容`).toBeGreaterThan(0)
    }
  })
})

describe('getPrompt', () => {
  it('按 mode 分发', () => {
    expect(getPrompt('ielts', 'module_p2', null)).toBe(IELTS_PROMPTS.module_p2)
    expect(getPrompt('scenario', null, 'ordering')).toBe(SCENARIO_PROMPTS.ordering)
  })

  it('未命中返回 null', () => {
    expect(getPrompt('ielts', 'nope', null)).toBeNull()
    expect(getPrompt('bogus', null, null)).toBeNull()
  })
})
