import { describe, it, expect } from 'vitest'
import {
  LOCAL_QUESTIONS,
  PART_META,
  USE_LOCAL_QUESTIONS,
  fetchQuestions,
  getQuestions,
  partParam,
  speechText,
} from './questions.js'

// pin 题库 shape 与 GET /questions?part= 契约一致（SCHEMA §6.5）：
// [{id, part, text, bullets?(p2), tts_url}]，part ∈ p1|p2|p3。
describe('LOCAL_QUESTIONS 契约 shape', () => {
  it('只含契约内的 part 键', () => {
    expect(Object.keys(LOCAL_QUESTIONS).sort()).toEqual(['p1', 'p2', 'p3'])
  })

  it('每题都有 id / part / text / tts_url，part 与所属键一致', () => {
    for (const [part, list] of Object.entries(LOCAL_QUESTIONS)) {
      expect(list.length).toBeGreaterThan(0)
      for (const q of list) {
        expect(typeof q.id).toBe('string')
        expect(q.part).toBe(part)
        expect(typeof q.text).toBe('string')
        expect(q.tts_url).toBeNull() // 离线 mock 题库无预生成音频恒 null（真题库由后端下发 /static/tts/{id}.wav）
      }
    }
  })

  it('p2 是 cue card：带 bullets 数组；p1/p3 不带', () => {
    for (const q of LOCAL_QUESTIONS.p2) expect(Array.isArray(q.bullets)).toBe(true)
    for (const q of [...LOCAL_QUESTIONS.p1, ...LOCAL_QUESTIONS.p3]) {
      expect(q.bullets).toBeUndefined()
    }
  })

  it('每个 part 都有页面 meta', () => {
    for (const part of Object.keys(LOCAL_QUESTIONS)) expect(PART_META[part]).toBeTruthy()
  })
})

describe('partParam（sub_mode → part 参数映射）', () => {
  it('module_pN → pN', () => {
    expect(partParam('module_p1')).toBe('p1')
    expect(partParam('module_p2')).toBe('p2')
    expect(partParam('module_p3')).toBe('p3')
  })

  it('契约外输入归 null', () => {
    expect(partParam('module_p4')).toBeNull()
    expect(partParam('exam')).toBeNull()
    expect(partParam(undefined)).toBeNull()
  })
})

describe('getQuestions / fetchQuestions / speechText', () => {
  it('按 sub_mode 取题，未命中 null', () => {
    expect(getQuestions('module_p1')).toBe(LOCAL_QUESTIONS.p1)
    expect(getQuestions('nope')).toBeNull()
  })

  it('feature flag 默认走真接口（VITE_SESSIONS_API 未设 ≠ mock）', () => {
    expect(USE_LOCAL_QUESTIONS).toBe(false)
  })

  it('fetchQuestions：sub_mode 非法 resolve null（不发请求）', async () => {
    await expect(fetchQuestions('exam')).resolves.toBeNull()
    await expect(fetchQuestions(undefined)).resolves.toBeNull()
  })

  it('fetchQuestions：真接口按契约打 GET /questions?part=（SCHEMA §6.5）', async () => {
    const calls = []
    const origFetch = globalThis.fetch
    globalThis.fetch = async (url) => {
      calls.push(String(url))
      return { ok: true, status: 200, json: async () => LOCAL_QUESTIONS.p2 }
    }
    try {
      const qs = await fetchQuestions('module_p2')
      expect(calls).toEqual(['/api/questions?part=p2'])
      expect(qs).toBe(LOCAL_QUESTIONS.p2)
    } finally {
      globalThis.fetch = origFetch
    }
  })

  it('朗读文本一律只读题面——p2 bullets 不口播（对齐拍板 D4，与 TTS/live 同规）', () => {
    const p2 = speechText(LOCAL_QUESTIONS.p2[0])
    expect(p2).toBe(LOCAL_QUESTIONS.p2[0].text)
    expect(p2).not.toContain('You should say')
    expect(speechText(LOCAL_QUESTIONS.p1[0])).toBe(LOCAL_QUESTIONS.p1[0].text)
  })
})
