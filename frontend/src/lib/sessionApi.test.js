import { describe, it, expect } from 'vitest'
import { MOCK_SESSION_ID, USE_MOCK_SESSIONS, createMockSessions } from './sessionApi.js'

const fakeBlob = { size: 1234 } // 纯逻辑测试不依赖 DOM Blob

// pin mock 返回 shape 与 SCHEMA §6.2 契约一致 —— mock/real 互换页面零改动的前提。
describe('mock sessions（契约 shape）', () => {
  it('feature flag 默认走真接口（VITE_SESSIONS_API 未设 ≠ mock；后端 P4 已收口）', () => {
    expect(USE_MOCK_SESSIONS).toBe(false)
  })

  it('create → {session_id}', async () => {
    const s = createMockSessions()
    const res = await s.create({ mode: 'ielts', subMode: 'module_p1' })
    expect(res).toEqual({ session_id: MOCK_SESSION_ID })
  })

  it('逐题 upload 入库，review → {status:"processing"}', async () => {
    const s = createMockSessions()
    const { session_id } = await s.create({ mode: 'ielts', subMode: 'module_p1' })
    await s.uploadRecording(session_id, { blob: fakeBlob, questionId: 'p1-q1' })
    await s.uploadRecording(session_id, { blob: fakeBlob, questionId: 'p1-q2' })
    expect(s._recordingsOf(session_id).map((r) => r.question_id)).toEqual(['p1-q1', 'p1-q2'])
    expect(await s.review(session_id)).toEqual({ status: 'processing' })
  })

  it('零录音 review 拒绝（不许空 Part 出报告）', async () => {
    const s = createMockSessions()
    const { session_id } = await s.create({ mode: 'ielts', subMode: 'module_p2' })
    await expect(s.review(session_id)).rejects.toThrow()
  })

  it('giveUp 物理删除：之后任何操作都失败、不留痕', async () => {
    const s = createMockSessions()
    const { session_id } = await s.create({ mode: 'ielts', subMode: 'module_p3' })
    await s.uploadRecording(session_id, { blob: fakeBlob, questionId: 'p3-q1' })
    await s.giveUp(session_id)
    expect(s._recordingsOf(session_id)).toBeNull()
    await expect(s.uploadRecording(session_id, { blob: fakeBlob, questionId: 'p3-q2' })).rejects.toThrow()
    await expect(s.review(session_id)).rejects.toThrow()
  })

  it('未创建 session 直接 upload/review/giveUp 都失败', async () => {
    const s = createMockSessions()
    await expect(s.uploadRecording('nope', { blob: fakeBlob, questionId: 'x' })).rejects.toThrow()
    await expect(s.review('nope')).rejects.toThrow()
    await expect(s.giveUp('nope')).rejects.toThrow()
  })
})
