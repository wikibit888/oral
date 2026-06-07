import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { MODE_IELTS } from '../lib/modes.js'
import { PART_META, fetchQuestions, partParam, speechText } from '../lib/questions.js'
import { sessions } from '../lib/sessionApi.js'
import { PcmRecorder } from '../lib/audio/recorder.js'
import { rmsLevel16 } from '../lib/audio/level.js'
import { errorText } from '../lib/api.js'

const LEVEL_BAR_SCALES = [0.45, 0.8, 1, 0.7, 0.5] // 电平条形态（中间高两侧低）
const REC_ACTIONS = 'flex items-center gap-3' // 操作行（Pause/Next/Give Up…）
// P2 对齐拍板 D1/D3（2026-06-07）：单卡长谈——读题后 60s 备题（不录音，可提前
// I'm ready），录音满 2 分钟提示可收尾（官方上限，不强切）
const PREP_SECONDS = 60
const LONG_TURN_HINT_S = 120

// 朗读题目兜底链（handoff 004-mode-b）：优先播预生成 tts_url（24k WAV，
// /static/tts/{id}.wav，runQuestion 处理）→ 失败/缺失回 SpeechSynthesis →
// 两者都不可用立即进录音。无声环境（headless / 关闭系统 TTS）事件可能
// 永不触发——按词数估时上限兜底，不卡死在朗读态。
function speak(text) {
  return new Promise((resolve) => {
    const synth = window.speechSynthesis
    if (!synth || typeof SpeechSynthesisUtterance === 'undefined') {
      resolve(false)
      return
    }
    let settled = false
    const settle = (ok) => {
      if (settled) return
      settled = true
      clearTimeout(cap)
      resolve(ok)
    }
    const cap = setTimeout(
      () => settle(false),
      Math.min(30000, 3000 + text.split(/\s+/).length * 600),
    )
    const u = new SpeechSynthesisUtterance(text)
    u.lang = 'en-GB' // 雅思考官口音；无英音 voice 时浏览器自动回退
    u.onend = () => settle(true)
    u.onerror = () => settle(false)
    synth.cancel()
    synth.speak(u)
  })
}

// F3 多题录音页（IELTS.md §3，docs 唯一形态——已替换原单题页）：
// 一个 Part 多题（后端每场随机抽：p1/p3 五题、p2 单卡）；考官朗读题目，
// p1/p3 **朗读结束自动进入录音**；p2 朗读结束先进 60s 备题（不录音，倒计时 +
// I'm ready 提前），到点自动开录，录音满 2 分钟提示可收尾（对齐拍板 D1/D3）；
// Next 保留本题进下一题；末题 Get Review 替代 Next，提交整个 Part 出一份报告；
// Pause/Resume 前端暂停；Give Up 直接物理删除退出（无确认框）。接口走
// lib/sessionApi（mock + feature flag，SCHEMA §6.2）；按钮简洁英文（FRONTEND.md §4）。
export default function Record() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const mode = params.get('mode')
  const subMode = params.get('sub_mode')
  const validEntry = mode === MODE_IELTS && partParam(subMode) != null
  const meta = PART_META[partParam(subMode)]

  // intro → starting → 每题 reading →（p2: prep 备题）→ recording ⇄ paused
  //   → advancing（Next 上传）| submitting（Get Review）→ 跳 /report/{id}
  // error 是可重试态（retryRef 记住失败的动作）。
  const [phase, setPhase] = useState('intro')
  const [qIndex, setQIndex] = useState(0)
  const [error, setError] = useState(null)
  const [elapsed, setElapsed] = useState(0)
  const [level, setLevel] = useState(0)
  const [prepLeft, setPrepLeft] = useState(null) // p2 备题剩余秒；null=不在备题
  // 题目异步加载（GET /questions?part=）：null=加载中；loadError 可 Retry
  const [questions, setQuestions] = useState(null)
  const [loadError, setLoadError] = useState(null)
  const [loadAttempt, setLoadAttempt] = useState(0)

  const sessionRef = useRef(null) // session_id（POST /sessions 返回）
  const prepDoneRef = useRef(false) // 备题只收口一次（到点与 I'm ready 先到先得）
  const recorderRef = useRef(null)
  const pendingRef = useRef(null) // 停录待上传的 {blob, questionId}；上传失败 Retry 复用
  const retryRef = useRef(null) // 失败动作（begin/next/getReview/startRecording）
  const ttsRef = useRef(null) // 播放中的题目音频（Audio 元素），卸载/Give Up 停掉
  const levelRef = useRef(0)
  const elapsedRef = useRef(0)
  const aliveRef = useRef(true) // 卸载后丢弃 await 续体，防 setState 泄漏

  // 加载身份变化（换 Part / Retry）→ 渲染期重置加载态
  // （Live.jsx 同款「adjusting state when props change」，effect 内不做同步 setState）
  const loadKey = `${subMode}|${loadAttempt}`
  const [prevLoadKey, setPrevLoadKey] = useState(loadKey)
  if (prevLoadKey !== loadKey) {
    setPrevLoadKey(loadKey)
    setQuestions(null)
    setLoadError(null)
  }

  // 拉题目（真接口/离线 mock 由 lib 层 flag 决定）
  useEffect(() => {
    if (!validEntry) return
    let alive = true
    fetchQuestions(subMode).then(
      (qs) => {
        if (alive) setQuestions(qs)
      },
      (e) => {
        if (alive) setLoadError(errorText(e))
      },
    )
    return () => {
      alive = false
    }
  }, [validEntry, subMode, loadAttempt])

  const question = questions?.[qIndex]
  const isLast = questions != null && qIndex === questions.length - 1

  // 录音计时 + 电平节流：worklet 帧只写 ref，100ms 读一次；
  // 暂停不清零（t0 用累计值回推），Resume 接着计。
  useEffect(() => {
    if (phase !== 'recording') return
    const t0 = Date.now() - elapsedRef.current * 1000
    const id = setInterval(() => {
      elapsedRef.current = (Date.now() - t0) / 1000
      setElapsed(elapsedRef.current)
      setLevel(levelRef.current)
    }, 100)
    return () => clearInterval(id)
  }, [phase])

  // p2 备题倒计时：每秒递减到 0 即停（收口在 startRecording 声明后的 effect 单次触发）
  useEffect(() => {
    if (phase !== 'prep' || prepLeft == null || prepLeft <= 0) return
    const id = setInterval(
      () => setPrepLeft((s) => (s == null || s <= 1 ? 0 : s - 1)),
      1000,
    )
    return () => clearInterval(id)
  }, [phase, prepLeft])

  // 卸载兜底：停 TTS（预生成音频 + SpeechSynthesis）+ 释放麦克风
  useEffect(() => {
    aliveRef.current = true
    return () => {
      aliveRef.current = false
      ttsRef.current?.pause()
      ttsRef.current = null
      window.speechSynthesis?.cancel()
      recorderRef.current?.stop().catch(() => {})
      recorderRef.current = null
    }
  }, [])

  // 播放预生成题目音频（24k WAV，vite /static 代理）；失败/被禁自动回退
  const playTts = (url) =>
    new Promise((resolve) => {
      const a = new Audio(url)
      ttsRef.current = a
      let settled = false
      const settle = (ok) => {
        if (settled) return
        settled = true
        if (ttsRef.current === a) ttsRef.current = null
        resolve(ok)
      }
      a.onended = () => settle(true)
      a.onerror = () => settle(false)
      a.play().catch(() => settle(false)) // autoplay 被拒/解码失败 → SpeechSynthesis 兜底
    })

  const startRecording = async () => {
    const rec = new PcmRecorder({
      // 0..1 电平（RMS，lib/audio/level.js——与 Live 波形共用）
      onFrame: (int16) => {
        levelRef.current = rmsLevel16(int16)
      },
    })
    try {
      await rec.start()
      if (!aliveRef.current) {
        rec.stop().catch(() => {})
        return
      }
      recorderRef.current = rec
      setPhase('recording')
    } catch {
      if (!aliveRef.current) return
      setError('无法访问麦克风：请在浏览器地址栏允许麦克风权限后 Retry。')
      retryRef.current = startRecording
      setPhase('error')
    }
  }

  const runQuestion = async (i) => {
    setQIndex(i)
    setError(null)
    setPhase('reading')
    elapsedRef.current = 0
    setElapsed(0)
    // 朗读链：预生成 tts_url 优先 → 失败/缺失回 SpeechSynthesis（含估时上限）
    const q = questions[i]
    const ttsOk = q.tts_url ? await playTts(q.tts_url) : false
    if (!aliveRef.current) return
    if (!ttsOk) await speak(speechText(q))
    if (!aliveRef.current) return
    if (partParam(subMode) === 'p2') {
      // 对齐拍板 D1/D3：P2 单卡——读题后 60s 备题（不录音），到点/I'm ready 进长谈
      prepDoneRef.current = false
      setPrepLeft(PREP_SECONDS)
      setPhase('prep')
      return
    }
    await startRecording() // p1/p3：朗读结束自动进录音（IELTS.md §3）
  }

  // I'm ready：提前结束备题（与 60s 倒计时先到先得，prepDoneRef 防双触发）
  const startNow = () => {
    if (prepDoneRef.current) return
    prepDoneRef.current = true
    setPrepLeft(null)
    startRecording()
  }

  // 备题到点自动开录（prepDoneRef 防与 I'm ready 双触发）
  useEffect(() => {
    if (phase !== 'prep' || prepLeft !== 0 || prepDoneRef.current) return
    prepDoneRef.current = true
    setPrepLeft(null)
    startRecording()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- startRecording 每渲染重建但行为稳定
  }, [phase, prepLeft])

  // Start：POST /sessions 建会话 → 第一题
  const begin = async () => {
    setError(null)
    setPhase('starting')
    try {
      const res = await sessions.create({ mode, subMode })
      sessionRef.current = res.session_id
    } catch (e) {
      if (!aliveRef.current) return
      setError(errorText(e))
      retryRef.current = begin
      setPhase('error')
      return
    }
    if (!aliveRef.current) return
    runQuestion(0)
  }

  // 停录并暂存 blob；已停过则 no-op（上传失败 Retry 不重复 stop）
  const stopAndStash = async () => {
    const rec = recorderRef.current
    if (!rec) return
    recorderRef.current = null
    const { blob } = await rec.stop()
    pendingRef.current = { blob, questionId: question.id }
  }

  const uploadPending = async () => {
    if (!pendingRef.current) return
    await sessions.uploadRecording(sessionRef.current, pendingRef.current)
    pendingRef.current = null
  }

  // Next：保留本题录音 → 逐题上传 → 进下一题
  const next = async () => {
    setError(null)
    setPhase('advancing')
    try {
      await stopAndStash()
      await uploadPending()
    } catch (e) {
      if (!aliveRef.current) return
      setError(errorText(e))
      retryRef.current = next
      setPhase('error')
      return
    }
    if (!aliveRef.current) return
    runQuestion(qIndex + 1)
  }

  // Get Review（末题替代 Next）：上传末题 → POST /review 触发 judge → 跳报告轮询
  const getReview = async () => {
    setError(null)
    setPhase('submitting')
    try {
      await stopAndStash()
      await uploadPending()
      await sessions.review(sessionRef.current)
    } catch (e) {
      if (!aliveRef.current) return
      setError(errorText(e))
      retryRef.current = getReview
      setPhase('error')
      return
    }
    navigate(`/report/${sessionRef.current}`)
  }

  const pause = async () => {
    await recorderRef.current?.pause()
    setPhase('paused')
  }
  const resume = async () => {
    await recorderRef.current?.resume()
    setPhase('recording')
  }

  // Give Up：直接退出（无确认框，2026-06-07 用户拍板）→ DELETE /sessions/{id}
  // 物理删除会话与音频 → 回选 Part 页
  const giveUp = async () => {
    ttsRef.current?.pause()
    ttsRef.current = null
    window.speechSynthesis?.cancel()
    recorderRef.current?.stop().catch(() => {})
    recorderRef.current = null
    try {
      if (sessionRef.current) await sessions.giveUp(sessionRef.current)
    } catch {
      // 删除请求失败不挡退出（本地 demo；残留交后端清理兜底）
    }
    navigate('/ielts')
  }

  const retry = () => {
    const fn = retryRef.current
    retryRef.current = null
    fn?.()
  }

  if (!validEntry || !meta) {
    return (
      <section>
        <h1>录音练习</h1>
        <p>
          未选定 Part——请从 <Link to="/ielts">IELTS 选方式</Link> 进入。
        </p>
      </section>
    )
  }

  // 题目加载失败（GET /questions）：可 Retry，不进入流程
  if (loadError) {
    return (
      <section>
        <h1 className="mt-0 text-center">{meta.label}</h1>
        <p className="form-error mx-auto">{loadError}</p>
        <div className={`${REC_ACTIONS} mt-3 justify-center`}>
          <button type="button" className="btn-primary" onClick={() => setLoadAttempt((n) => n + 1)}>
            Retry
          </button>
          <Link className="text-sm" to="/ielts">
            Back
          </Link>
        </div>
      </section>
    )
  }

  const busy = phase === 'starting' || phase === 'advancing' || phase === 'submitting'

  // 整页居中布局（2026-06-07 用户指令）：eyebrow/标题/进度/题目卡/控制区同轴
  return (
    <section>
      <header className="flex items-center justify-center gap-4">
        <p className="eyebrow mb-0">
          <span className="eyebrow-dot" aria-hidden="true" />
          IELTS · 分模块练习 · {meta.label}
        </p>
      </header>

      {phase === 'intro' ? (
        <div className="text-center">
          <h1 className="mt-0 text-center">
            {meta.label} · {meta.topic}
          </h1>
          <p>{meta.intro}</p>
          <p className="muted">
            {questions == null
              ? '题目加载中…'
              : `共 ${questions.length} 题：考官朗读题目 → 自动开始录音 → Next 保留本题进下一题，
            末题 Get Review 出整个 Part 的一份报告。`}
          </p>
          <button
            type="button"
            className="btn-primary mt-4.5 px-7 py-3 text-base"
            onClick={begin}
            disabled={questions == null}
          >
            Start
          </button>
        </div>
      ) : (
        <>
          <h1 className="mt-0 text-center">
            {meta.label} · {meta.topic}
          </h1>
          <p className="mb-3.5 mt-1 text-center font-mono text-[13px] font-semibold leading-none tracking-[0.08em] text-accent">
            Question {qIndex + 1} / {questions.length}
          </p>
          <QuestionCard q={question} intro={meta.intro} />

          <div className="flex flex-col items-center gap-4.5 py-6">
            {phase === 'reading' && (
              <p className="my-1 flex items-center gap-2.5 font-sans text-[15px] leading-[1.4] text-ink-strong">
                <span
                  className="h-2.5 w-2.5 animate-reading-pulse rounded-full bg-accent-bright motion-reduce:animate-none"
                  aria-hidden="true"
                />
                {partParam(subMode) === 'p2'
                  ? '考官朗读中…（朗读结束进入 1 分钟准备）'
                  : '考官朗读中…（朗读结束自动开始录音）'}
              </p>
            )}

            {phase === 'prep' && (
              <div className="flex flex-col items-center gap-3.5">
                <p className="m-0 font-mono text-xs font-semibold uppercase leading-none tracking-[0.08em] text-accent">
                  Preparation
                </p>
                <span className="font-mono text-[26px] font-bold leading-none text-ink-strong">
                  {prepLeft != null ? `${prepLeft}s` : '…'}
                </span>
                <p className="muted m-0">备题中——这段时间不录音，可在心里按 bullets 列要点。</p>
                <div className={REC_ACTIONS}>
                  <button type="button" className="btn-primary" onClick={startNow}>
                    I'm ready
                  </button>
                  <button type="button" className="btn-ghost shrink-0" onClick={giveUp}>
                    Give Up
                  </button>
                </div>
              </div>
            )}

            {(phase === 'recording' || phase === 'paused') && (
              <>
                <div className="flex items-center gap-3.5">
                  <span
                    className={`h-2.5 w-2.5 rounded-full bg-[#dc2626] ${
                      phase === 'paused'
                        ? 'opacity-40'
                        : 'animate-blink motion-reduce:animate-none'
                    }`}
                    aria-hidden="true"
                  />
                  <span className="min-w-14 font-mono text-xl font-semibold leading-none text-ink-strong">
                    {formatElapsed(elapsed)}
                  </span>
                  <div className="flex h-9 items-center gap-[5px]" aria-hidden="true">
                    {LEVEL_BAR_SCALES.map((s, i) => (
                      <span
                        key={i}
                        className="h-full w-1.5 origin-center rounded-full bg-accent-bright transition-transform duration-100 ease-linear"
                        style={{
                          transform: `scaleY(${
                            phase === 'paused'
                              ? 0.15
                              : 0.15 + Math.min(1, level * s * 2.2) * 0.85
                          })`,
                        }}
                      />
                    ))}
                  </div>
                  {phase === 'paused' && <span className="muted">Paused</span>}
                </div>
                {partParam(subMode) === 'p2' && elapsed >= LONG_TURN_HINT_S && (
                  <p className="muted m-0">
                    已讲约 2 分钟（官方长谈上限）——可以收尾了，说完点 Get Review。
                  </p>
                )}
                <div className={REC_ACTIONS}>
                  {phase === 'recording' ? (
                    <button type="button" className="btn-ghost" onClick={pause}>
                      Pause
                    </button>
                  ) : (
                    <button type="button" className="btn-ghost" onClick={resume}>
                      Resume
                    </button>
                  )}
                  {isLast ? (
                    <button type="button" className="btn-primary" onClick={getReview}>
                      Get Review →
                    </button>
                  ) : (
                    <button type="button" className="btn-primary" onClick={next}>
                      Next →
                    </button>
                  )}
                  <button
                    type="button"
                    className="btn-ghost shrink-0"
                    onClick={giveUp}
                    disabled={busy}
                  >
                    Give Up
                  </button>
                </div>
              </>
            )}

            {busy && (
              <p className="muted">
                {phase === 'submitting' ? 'Submitting… 提交整个 Part 并触发评测' : '处理中…'}
              </p>
            )}

            {phase === 'error' && (
              <div className={REC_ACTIONS}>
                <button type="button" className="btn-primary" onClick={retry}>
                  Retry
                </button>
                {/* header 的 Give Up 已并入操作行——error 态保留同位置出口 */}
                <button type="button" className="btn-ghost shrink-0" onClick={giveUp}>
                  Give Up
                </button>
              </div>
            )}

            {error && <p className="form-error">{error}</p>}
          </div>
        </>
      )}
    </section>
  )
}

// 题目卡：普通题直接读题；P2 cue card = 话题 + bullets。
// 卡片居中（max-w + mx-auto），卡内文字保持左对齐可读性。
function QuestionCard({ q, intro }) {
  return (
    <div className="mx-auto mb-7 mt-5 max-w-[640px] rounded-xl border border-line border-l-[3px] border-l-accent-bright px-6 py-5 shadow-[0_1px_2px_rgba(10,10,10,0.02)]">
      <p className="mb-2.5 mt-0 text-sm">{intro}</p>
      <p className="mb-2.5 mt-1.5 font-display text-[22px] text-ink-strong">{q.text}</p>
      {q.bullets && (
        <ul className="prompt-list">
          {q.bullets.map((b, i) => (
            <li key={i}>{b}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

function formatElapsed(seconds) {
  const s = Math.floor(seconds)
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}
