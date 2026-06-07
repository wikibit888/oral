// 方式 B 题库（F3）。默认走真接口 `GET /questions?part=`（SCHEMA §6.5，
// handoff 004-mode-b：24 题 tts_url 预生成 /static/tts/{id}.wav 可直接播放）；
// 离线开发设 VITE_SESSIONS_API=mock 时回本地静态题库（shape 与契约一字
// 不差，tts_url 恒 null → 页面 SpeechSynthesis 兜底朗读）。
import { request } from './api.js'

export const USE_LOCAL_QUESTIONS = import.meta.env.VITE_SESSIONS_API === 'mock'

// sub_mode（后端契约串 module_p1…）→ /questions 的 part 参数（p1|p2|p3）
export function partParam(subMode) {
  const m = /^module_(p[123])$/.exec(subMode ?? '')
  return m ? m[1] : null
}

// 页面头部文案（不属于 /questions 契约，纯前端展示层）
export const PART_META = {
  p1: { label: 'Part 1', topic: 'Daily Life', intro: '考官就熟悉话题快问快答。每题说 2–3 句：' },
  // 对齐拍板 D1/D3（2026-06-07）：P2 每场一张卡——读题后 1 分钟准备（不录音），再连续讲 1–2 分钟
  p2: { label: 'Part 2', topic: 'Cue Card', intro: '读题后有 1 分钟准备（不录音）；随后围绕卡片连续讲 1–2 分钟：' },
  p3: { label: 'Part 3', topic: 'Discussion', intro: '考官就抽象话题深入追问。给出有论证的展开回答：' },
}

export const LOCAL_QUESTIONS = {
  p1: [
    { id: 'p1-q1', part: 'p1', text: 'Where is your hometown?', tts_url: null },
    { id: 'p1-q2', part: 'p1', text: 'What do you like most about it?', tts_url: null },
    {
      id: 'p1-q3',
      part: 'p1',
      text: 'Has your hometown changed much in recent years?',
      tts_url: null,
    },
  ],
  p2: [
    {
      id: 'p2-q1',
      part: 'p2',
      text: 'Describe a skill you would like to learn.',
      bullets: [
        'what the skill is',
        'why you want to learn it',
        'how you would learn it',
        'and explain how it would help you',
      ],
      tts_url: null,
    },
  ],
  p3: [
    {
      id: 'p3-q1',
      part: 'p3',
      text: 'Why do some people give up learning new skills quickly?',
      tts_url: null,
    },
    { id: 'p3-q2', part: 'p3', text: 'Should schools focus more on practical skills?', tts_url: null },
    {
      id: 'p3-q3',
      part: 'p3',
      text: 'How has technology changed the way people learn?',
      tts_url: null,
    },
  ],
}

// 按 sub_mode 取本地题库列表；未命中返回 null（页面挡未选定入口）。
export function getQuestions(subMode) {
  const part = partParam(subMode)
  return part ? LOCAL_QUESTIONS[part] : null
}

// 拉取该 Part 题目（页面入口）：真接口 GET /questions?part=；mock 模式回本地
// 题库（resolve 同 shape）。sub_mode 非法 resolve null，与 getQuestions 一致。
export async function fetchQuestions(subMode) {
  const part = partParam(subMode)
  if (!part) return null
  if (USE_LOCAL_QUESTIONS) return LOCAL_QUESTIONS[part]
  return request(`/questions?part=${part}`)
}

// 朗读文本：一律只读题面（对齐拍板 D4，2026-06-07）——P2 bullets 卡上展示
// 不口播，与预生成 TTS（app/tts.py compose_tts_text）/ live 考官同规。
export function speechText(q) {
  return q.text
}
