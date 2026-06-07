// 方式 B 会话化接口（F3）：POST /sessions → 逐题 recordings → 末题 /review；
// Give Up = DELETE（SCHEMA §6.2）。后端 P4 已收口（handoff 004-mode-b，
// PR #17 旧 /recordings 已删）——**默认走真接口**；离线前端开发设
// `VITE_SESSIONS_API=mock` 切内存 mock（shape 与契约一字不差，Get Review
// 落方式 B fixture 报告，零后端可演示）。
import { request } from './api.js'

export const USE_MOCK_SESSIONS = import.meta.env.VITE_SESSIONS_API === 'mock'

// —— 真实现（默认）——
const real = {
  // POST /sessions {mode, sub_mode} → 201 {session_id}（仅方式 B；exam/scenario 422 走 /ws/live）
  create({ mode, subMode }) {
    return request('/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode, sub_mode: subMode }),
    })
  },
  // POST /sessions/{id}/recordings — multipart audio(16k/mono/16bit WAV) + question_id
  // → 202 {status:"accepted", question_id, duration_s}；422 格式违约 / 409 已 review；
  // 同题重传 = 重录替换（按最新一次评）
  uploadRecording(sessionId, { blob, questionId }) {
    const form = new FormData()
    form.append('audio', blob, 'recording.wav')
    form.append('question_id', questionId)
    return request(`/sessions/${sessionId}/recordings`, { method: 'POST', body: form })
  },
  // POST /sessions/{id}/review → {status:"processing"}；前端跳 /report/{id} 轮询
  review(sessionId) {
    return request(`/sessions/${sessionId}/review`, { method: 'POST' })
  },
  // DELETE /sessions/{id} — 物理删除会话与音频，不留痕
  giveUp(sessionId) {
    return request(`/sessions/${sessionId}`, { method: 'DELETE' })
  },
}

// —— mock（工厂导出供测试建独立实例）——
// session_id 固定 'demo-ielts-b'：Get Review 后页面跳 /report/{session_id}，
// 正好命中方式 B fixture（fixtures/reportFixtures.js），零后端走通全流程演示；
// 切真实现后自然换成后端返回的真 id。
export const MOCK_SESSION_ID = 'demo-ielts-b'

export function createMockSessions() {
  const store = new Map() // session_id → { mode, sub_mode, recordings: [{question_id, bytes}] }

  const mustGet = (id) => {
    const s = store.get(id)
    if (!s) throw new Error(`mock: session ${id} 不存在（已删除或未创建）`)
    return s
  }

  return {
    // 全部 async：mustGet 的 throw 一律变成 rejection，与真实现的失败语义一致
    async create({ mode, subMode }) {
      store.set(MOCK_SESSION_ID, { mode, sub_mode: subMode, recordings: [] })
      return { session_id: MOCK_SESSION_ID }
    },
    async uploadRecording(sessionId, { blob, questionId }) {
      mustGet(sessionId).recordings.push({ question_id: questionId, bytes: blob?.size ?? 0 })
      return null // 契约 202 无 body
    },
    async review(sessionId) {
      const s = mustGet(sessionId)
      if (s.recordings.length === 0) throw new Error('mock: 没有任何录音')
      return { status: 'processing' }
    },
    async giveUp(sessionId) {
      mustGet(sessionId)
      store.delete(sessionId) // 物理删除，不留痕
      return null
    },
    // 测试探针（真实现没有，页面禁用）
    _recordingsOf: (id) => store.get(id)?.recordings ?? null,
  }
}

export const sessions = USE_MOCK_SESSIONS ? createMockSessions() : real
