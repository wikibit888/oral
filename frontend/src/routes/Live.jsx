import { useEffect, useReducer, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { scenarioLabel } from '../lib/modes.js'
import { PcmRecorder } from '../lib/audio/recorder.js'
import { PcmPlayer } from '../lib/audio/player.js'
import { rmsLevel16 } from '../lib/audio/level.js'
import VoiceWave from '../components/VoiceWave.jsx'
import {
  PART_STAGES,
  appendDelta,
  buildLiveUrl,
  createFrameBatcher,
  formatLatency,
  normalizeTurn,
  parseEvent,
  partStage,
  pttReducer,
  validateLiveParams,
} from '../lib/live.js'
import { createNudgeTimer } from '../lib/nudge.js'

// 气泡（Transcript 模式）/ 徽章 共享样式
const BUBBLE_BASE = 'max-w-[76%] rounded-[14px] border px-3.5 py-2.5'
const BUBBLE_ROLE =
  'font-mono text-[11px] font-semibold uppercase leading-none tracking-[0.08em] text-ink'
const BADGE_BASE = 'rounded-full border px-2.5 py-1.5 font-mono text-xs font-semibold leading-none'

// F6 实时会话页（雅思 A + 情景共用；handoff 001 联调范围）：
//   mic 16k PCM 裸帧（合批 ~200ms）→ WS 上行；下行 24k PCM 播放队列 + 事件流；
//   `interrupted` → 立即清空播放队列（barge-in 闭环）；
//   End → 发 `end_session` → 关 WS → 跳 /report/{session_id}（后端自动触发 judge）。
// 轮次模式（handoff 004，后端 PR #14）：natural = Live 内建 VAD 自动断轮；
//   ptt = VAD 关，按住推帧、松开「先 flush 合批器再发 turn_end」，考官只在
//   turn_end 后应答，`turn_complete` 解锁下一次按键；切换走重连（连接参数）。
//   考官每轮首帧后下发 latency_ms → 头部延迟徽章（natural 含 VAD 判停标 ≈）。
// 方式 A 导演（handoff 005，009 终版模型驱动：转场宣告走考官语音，事件值
//   不变）：建链自动开考——part_change 驱动顶部 Part 进度条（p2_* 合并
//   Part 2）；p2_prep 期浮层 = cue card + 60s 倒计时 + 笔记 + I'm ready；
//   done = 考官说完收尾句——等收尾语音**播完**（player 队列排空）自动走
//   End 流程跳报告（模型触发结束自动收束；手动 End 仍可抢先，endingRef 防双触发）。
// 波形模式（Batch 4 用户决策）：默认隐藏实时转写——语音训练靠听不靠读；
//   考官说话出播放电平波形、用户说话切麦电平（VoiceWave），Transcript 开关
//   可切回气泡流；转写数据照常累积（报告不受影响）。
// 沉默分级探询（handoff 011，仅 scenario）：turn_complete + 播放排空起表，
//   沉默 ~10s/12s/15s 分级上行 nudge（AI 语音介入），人声/播音/teaching 重置，
//   PTT 只发 stage 1 且阈值翻倍——逻辑全在 lib/nudge.js，生命周期随连接 effect。
// Live 挂 / error 事件 → 直接报错不降级（CLAUDE.md 架构铁律）。
export default function Live() {
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const mode = params.get('mode')
  const caseId = params.get('case')
  const turnMode = normalizeTurn(params.get('turn'))
  const paramError = validateLiveParams({ mode, caseId })

  // connecting → live → ending；error 终态（Retry 重连）
  const [status, setStatus] = useState('connecting')
  const [error, setError] = useState(null)
  const [transcript, setTranscript] = useState([])
  const [examinerSpeaking, setExaminerSpeaking] = useState(false)
  const [latencyMs, setLatencyMs] = useState(null) // 最近一轮考官应答延迟
  const [attempt, setAttempt] = useState(0) // Retry bump 重启连接 effect
  // 波形/气泡显示开关（会话内偏好，重连不重置）：默认波形（不看转写）
  const [showTranscript, setShowTranscript] = useState(false)
  // PTT 轮次状态机：idle | pressed | waiting（见 lib/live.js pttReducer）
  const [ptt, dispatchPtt] = useReducer(pttReducer, 'idle')
  // 方式 A 导演状态（handoff 005）：scenario 无 part 事件恒 null（不出进度条）
  const [part, setPart] = useState(null)
  const [cueCard, setCueCard] = useState(null) // present_cue_card 的 card
  const [prepLeft, setPrepLeft] = useState(null) // 备题剩余秒；null=不在备题
  const [notes, setNotes] = useState('')
  const [readySent, setReadySent] = useState(false)

  const wsRef = useRef(null)
  const recRef = useRef(null)
  const batcherRef = useRef(null)
  const sessionRef = useRef(null)
  const endingRef = useRef(false)
  // 方式 A 自动收束：done 已到标记 + 最新 endSession 的 ref（连接 effect 闭包
  // 只持 ref，不持建链那一刻的旧闭包）
  const doneRef = useRef(false)
  const endSessionRef = useRef(() => {})
  const transcriptEndRef = useRef(null)
  // worklet onFrame 在 React 渲染外回调，按住与否走 ref 不走 state
  const pttPressedRef = useRef(false)
  // 波形电平源（VoiceWave 80ms 轮询，不走 state 防高频重渲）
  const playerRef = useRef(null)
  const micLevelRef = useRef(0)
  // 沉默探询计时器（handoff 011，仅 scenario 非空）：End 时经 ref 停表
  const nudgeRef = useRef(null)

  // 连接身份（参数或 Retry 变化）→ 渲染期重置 UI 状态
  // （react.dev「adjusting state when props change」，effect 里不做同步 setState）
  const connKey = `${mode}|${caseId}|${turnMode}|${attempt}`
  const [prevKey, setPrevKey] = useState(connKey)
  if (prevKey !== connKey) {
    setPrevKey(connKey)
    setStatus('connecting')
    setError(null)
    setTranscript([])
    setExaminerSpeaking(false)
    setLatencyMs(null)
    dispatchPtt('reset')
    setPart(null)
    setCueCard(null)
    setPrepLeft(null)
    setNotes('')
    setReadySent(false)
  }

  // 备题倒计时：start_prep_timer 起跳，每秒递减到 0 即停（断轮以后端
  // part_change 为准——计时器只是 UI 展示，0 后等后端推进，不本地切态）
  useEffect(() => {
    if (prepLeft == null || prepLeft <= 0) return
    const id = setInterval(
      () => setPrepLeft((s) => (s == null || s <= 1 ? 0 : s - 1)),
      1000,
    )
    return () => clearInterval(id)
  }, [prepLeft])

  // 转写流自动滚到最新（仅气泡模式；波形模式无滚动区）
  useEffect(() => {
    if (showTranscript) transcriptEndRef.current?.scrollIntoView({ block: 'end' })
  }, [transcript, showTranscript])

  useEffect(() => {
    if (paramError) return
    // StrictMode 双挂载安全：一切资源都在本闭包内建、cleanup 内拆
    let alive = true
    let errored = false
    endingRef.current = false
    doneRef.current = false
    sessionRef.current = null
    pttPressedRef.current = false
    micLevelRef.current = 0

    // 方式 A 自动收束：考试 done 且收尾语音播完 → 自动走 End 流程跳报告
    // （后端 turn_complete 时收尾音频还在本地缓冲，只有 player 知道何时播完）；
    // endingRef 防与手动 End 双触发
    const maybeAutoEnd = () => {
      if (doneRef.current && !endingRef.current) endSessionRef.current()
    }
    const player = new PcmPlayer({
      onIdle: () => {
        if (!alive) return
        setExaminerSpeaking(false)
        nudge?.playbackIdle() // 排空 = 沉默倒计时续起（nudge 在下方创建，事件回调晚于初始化）
        maybeAutoEnd()
      },
    })
    playerRef.current = player
    const ws = new WebSocket(buildLiveUrl({ mode, caseId, turn: turnMode }))
    ws.binaryType = 'arraybuffer'
    wsRef.current = ws
    const batcher = createFrameBatcher((int16) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(int16.buffer)
    })
    batcherRef.current = batcher
    // 沉默分级探询（handoff 011）：仅 scenario 挂载；turn 切换走重连，本 effect
    // 重建即拿到新 ptt 标志。方式 A 恒 null（后端对 ielts_a 的 nudge 也忽略，双保险）
    const nudge =
      mode === 'scenario'
        ? createNudgeTimer({
            ptt: turnMode === 'ptt',
            send: (msg) => {
              if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg))
            },
          })
        : null
    nudgeRef.current = nudge

    const cleanup = () => {
      const rec = recRef.current
      recRef.current = null
      batcherRef.current = null
      if (playerRef.current === player) playerRef.current = null
      if (nudgeRef.current === nudge) nudgeRef.current = null
      nudge?.stop()
      rec?.stop().catch(() => {})
      player.close().catch(() => {})
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) ws.close()
    }

    const fail = (msg) => {
      if (!alive || errored) return
      errored = true
      // 错误即死链：先撂倒 alive 再 cleanup——close()→flush() 会触发 onIdle，
      // doneRef 已置位时会经 maybeAutoEnd 把错误屏自动导航走（review W3）
      alive = false
      setError(msg)
      setStatus('error')
      cleanup()
    }

    ws.onopen = async () => {
      // 建链成功才开 mic；帧经合批上行。PTT 模式松开期间不上行（mic 持续
      // 采集不重建图，只在 batcher 入口闸门）——后端 VAD 已关，静默帧也会
      // 被当作用户音频 tee 进切片，必须在源头挡住。
      // 电平在闸门前算：波形的麦电平不受 PTT 上行闸门影响（显示层另行判源）。
      const rec = new PcmRecorder({
        onFrame: (int16) => {
          const level = rmsLevel16(int16)
          micLevelRef.current = level
          // 人声喂给沉默探询（PTT 松开期也喂：本地出声=没卡住，不该探询；
          // echoCancellation 已开，AI 播音回灌不会被当成人声）
          nudge?.voice(level)
          if (turnMode === 'ptt' && !pttPressedRef.current) return
          batcher.push(int16)
        },
      })
      try {
        await rec.start()
        if (!alive) {
          rec.stop().catch(() => {})
          return
        }
        recRef.current = rec
      } catch {
        fail('无法访问麦克风：请允许麦克风权限后 Retry。')
      }
    }

    ws.onmessage = (e) => {
      if (!alive) return
      if (e.data instanceof ArrayBuffer) {
        player.enqueue(e.data) // 24k 考官音频
        setExaminerSpeaking(true)
        nudge?.playbackStart() // AI 开口 = 暂停沉默倒计时
        return
      }
      const ev = parseEvent(e.data)
      if (!ev) return
      switch (ev.type) {
        case 'session_started':
          sessionRef.current = ev.session_id
          setStatus('live')
          break
        case 'transcript_delta':
          setTranscript((t) => appendDelta(t, ev))
          break
        case 'interrupted':
          player.flush() // barge-in：立即清空 24k 播放队列
          break
        case 'turn_complete':
          setExaminerSpeaking(false)
          dispatchPtt('turn_complete') // PTT：考官应答完毕，解锁下一次按键
          nudge?.turnComplete() // 轮到用户：沉默倒计时 armed（排空后起表）
          break
        case 'latency_ms':
          // 考官每轮首帧音频后下发（一轮一次；考官先开口的轮次不发）
          if (typeof ev.value === 'number') setLatencyMs(ev.value)
          break
        case 'part_change':
          setPart(ev.part)
          if (ev.part !== 'p2_prep') setPrepLeft(null) // 离开备题：停倒计时
          if (ev.part === 'done') {
            // 考试结束：等收尾语音播完自动收束；音频已排空（罕见）则立即
            doneRef.current = true
            if (!player.speaking) maybeAutoEnd()
          }
          break
        case 'present_cue_card':
          if (ev.card) setCueCard(ev.card)
          break
        case 'start_prep_timer':
          if (typeof ev.seconds === 'number') setPrepLeft(ev.seconds)
          break
        case 'teaching':
          // 求助卡片 UI 是 handoff 010（待做）；011 先消费其「用户在求助」语义：
          // 全量重置沉默探询（仅 scenario 会收到）
          nudge?.teaching()
          break
        case 'error':
          fail(ev.message ?? '实时会话出错。') // 后端中文文案直出（handoff 001）
          break
        default:
        // 契约外事件忽略——前向兼容 examiner_speaking 等后续事件
      }
    }

    // ws.onerror 不设 handler（handoff 003 定夺）：浏览器 error 事件不携带
    // 可用信息且必伴随 close，onclose 统一兜底，双 handler 反而易出双报错。
    // error 事件后服务端会关连接：errored 已置位则不覆盖文案
    ws.onclose = () => {
      if (!alive || endingRef.current) return
      fail('连接已断开——Live 不可用时直接报错，不降级（可 Retry 重连）。')
    }

    return () => {
      alive = false
      cleanup()
    }
  }, [mode, caseId, turnMode, attempt, paramError])

  // End：发 end_session（后端自动触发课后 judge）→ 跳报告轮询；
  // 方式 A done 后由 maybeAutoEnd 自动调用（同一流程，无分叉）
  const endSession = () => {
    endingRef.current = true
    setStatus('ending')
    nudgeRef.current?.stop() // End 即停表（报告跳转前不再探询，handoff 011）
    const ws = wsRef.current
    // 先排空合批器：不足 3200 样本的尾音（≤200ms）还压在批里，不发就会被
    // 后端 tee 永久漏掉——每次 End 都系统性截掉最后一段用户语音（review W1）
    batcherRef.current?.flush()
    try {
      ws?.send(JSON.stringify({ type: 'end_session' }))
    } catch {
      // 发送失败也继续收尾——会话音频已在后端
    }
    recRef.current?.stop().catch(() => {})
    recRef.current = null
    ws?.close()
    const id = sessionRef.current
    if (id) {
      navigate(`/report/${id}`)
    } else {
      setError('未收到 session_started，拿不到报告地址——请 Retry 重新会话。')
      setStatus('error')
    }
  }

  // 自动收束调用的是**最新渲染**的 endSession（闭包含 navigate/state setter）：
  // 每次渲染后刷新 ref，连接 effect 里经 endSessionRef 间接调用、不持旧闭包
  useEffect(() => {
    endSessionRef.current = endSession
  })

  const retry = () => setAttempt((n) => n + 1)

  // PTT 按下：开始上行音频帧（pttPressedRef 是 onFrame 的闸门）
  const pttDown = () => {
    if (status !== 'live' || ptt !== 'idle') return
    pttPressedRef.current = true
    dispatchPtt('press')
  }

  // PTT 松开：时序硬约束（handoff 004）——先排空合批器再发 turn_end，
  // 反序会把按住末尾 ≤200ms 尾音留在批里，turn_end 先到、断轮点漂移。
  const pttUp = () => {
    if (ptt !== 'pressed') return
    pttPressedRef.current = false
    batcherRef.current?.flush()
    const ws = wsRef.current
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'turn_end' }))
    }
    dispatchPtt('release') // → waiting，等 turn_complete 解锁
  }

  // 键盘按住支持：Space/Enter keydown 按下（忽略长按 repeat）、keyup 松开
  const pttKeyDown = (e) => {
    if ((e.key === ' ' || e.key === 'Enter') && !e.repeat) {
      e.preventDefault()
      pttDown()
    }
  }
  const pttKeyUp = (e) => {
    if (e.key === ' ' || e.key === 'Enter') {
      e.preventDefault()
      pttUp()
    }
  }

  // 轮次模式切换 = 连接参数变化，走重连（FRONTEND §5 turn=ptt|natural）；
  // connKey 含 turnMode，setParams 后旧连接整体拆除、新参数重建
  const switchTurn = (next) => {
    if (next === turnMode || status === 'ending') return
    const q = new URLSearchParams(params)
    q.set('turn', next)
    setParams(q, { replace: true })
  }

  // 「I'm ready」：提前结束备题（与 60s 计时器先到先得）；不本地收浮层，
  // 等后端 part_change p2_talk——误发后端幂等忽略
  const sendReady = () => {
    if (readySent) return
    const ws = wsRef.current
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'ready' }))
      setReadySent(true)
    }
  }

  const stage = partStage(part)
  const examDone = stage === 'done'
  const stageIdx = PART_STAGES.indexOf(stage) // done/null → -1

  // 波形电平源：考官播放音优先；natural 常开麦 / PTT 按住期间显示麦电平
  const waveSource = examinerSpeaking
    ? 'examiner'
    : status === 'live' && (turnMode === 'natural' || ptt === 'pressed')
      ? 'mic'
      : 'idle'

  const title =
    mode === 'scenario' ? `Scenario · ${scenarioLabel(caseId) ?? ''}` : 'IELTS · Mock Exam'

  // 空态/引导文案（两种显示模式共用）
  const hint =
    status !== 'live'
      ? '建立连接中…（需要后端 /ws/live 与 GEMINI_API_KEY）'
      : mode === 'ielts_a'
        ? '已连接——考官将开场提问，听到问题后作答即可。'
        : turnMode === 'ptt'
          ? '已连接——按住 Hold to talk 说话，松开后考官应答。'
          : '已连接——开口说话即可开始对话。'

  // P2 cue card 内联卡（p2_talk 长谈期；两种显示模式都要看到题）
  const inlineCue = part === 'p2_talk' && cueCard && (
    <div className="w-full max-w-[560px] self-center rounded-xl border border-line border-l-[3px] border-l-accent-bright bg-white px-4.5 py-3.5">
      <p className="m-0 font-display text-[19px] text-ink-strong">{cueCard.text}</p>
      {cueCard.bullets?.length > 0 && (
        <ul className="prompt-list mt-2">
          {cueCard.bullets.map((b, i) => (
            <li key={i}>{b}</li>
          ))}
        </ul>
      )}
      {notes && (
        <p className="mb-0 mt-2.5 whitespace-pre-wrap border-t border-dashed border-line pt-2.5 text-[13.5px]">
          {notes}
        </p>
      )}
    </div>
  )

  const doneNote = examDone && (
    <p className="m-0 mt-1.5 self-center rounded-full border border-accent-line bg-accent-soft px-4 py-2 font-sans text-[13.5px] font-semibold leading-normal text-accent">
      考试已结束——正在生成报告，即将跳转…
    </p>
  )

  if (paramError) {
    return (
      <section className="flex min-h-[70svh] flex-col">
        <h1>实时会话</h1>
        <p className="form-error">{paramError}</p>
        <Link className="text-sm" to="/practice">
          Back to Practice
        </Link>
      </section>
    )
  }

  if (status === 'error') {
    return (
      <section className="flex min-h-[70svh] flex-col">
        <h1>{title}</h1>
        <p className="form-error">{error}</p>
        <div className="mt-3 flex items-center gap-3">
          <button type="button" className="btn-primary" onClick={retry}>
            Retry
          </button>
          <Link className="text-sm" to="/practice">
            Back to Practice
          </Link>
        </div>
      </section>
    )
  }

  return (
    <section className="flex min-h-[70svh] flex-col">
      <header className="flex items-center justify-between gap-4">
        <p className="eyebrow mb-0">
          <span className="eyebrow-dot" aria-hidden="true" />
          {title}
        </p>
        <div className="flex items-center gap-2">
          {latencyMs != null && (
            <span
              className={`${BADGE_BASE} border-line bg-white text-ink`}
              title={
                turnMode === 'ptt'
                  ? '考官应答延迟：松开按钮 → 首帧音频'
                  : '考官应答延迟（近似值，含 VAD 判停耗时）'
              }
            >
              {formatLatency(latencyMs, turnMode)}
            </span>
          )}
          {/* 波形 ⇄ 气泡切换（默认波形——靠听不靠读；转写始终在采集） */}
          <button
            type="button"
            onClick={() => setShowTranscript((v) => !v)}
            aria-pressed={showTranscript}
            className={`${BADGE_BASE} cursor-pointer transition-colors duration-150 ${
              showTranscript
                ? 'border-accent-line bg-accent-soft text-accent'
                : 'border-line bg-white text-ink hover:border-accent-bright'
            }`}
          >
            Transcript
          </button>
          <span
            className={`${BADGE_BASE} ${
              status === 'live'
                ? 'border-accent-line bg-accent-soft text-accent'
                : 'border-line text-ink'
            }`}
          >
            {status === 'connecting' && 'Connecting…'}
            {status === 'live' && '● Live'}
            {status === 'ending' && 'Ending…'}
          </span>
        </div>
      </header>

      {(stage != null || examDone) && (
        <nav className="mt-3.5 flex items-center gap-2" aria-label="Exam progress">
          {PART_STAGES.map((s, i) => {
            const active = s === stage
            const past = examDone || (stageIdx >= 0 && i < stageIdx)
            return (
              <span
                key={s}
                className={`rounded-full border px-3 py-1.5 font-mono text-xs font-semibold leading-none tracking-[0.06em] transition-colors duration-300 ${
                  active
                    ? 'border-accent-line bg-accent-soft text-accent'
                    : past
                      ? 'border-line text-ink-strong'
                      : 'border-line text-ink opacity-65'
                }`}
              >
                {s}
                {past && !active && <span className="ml-1 text-accent">✓</span>}
              </span>
            )
          })}
          {examDone && (
            <span className="rounded-full border border-accent-line bg-accent-soft px-3 py-1.5 font-mono text-xs font-semibold leading-none tracking-[0.06em] text-accent">
              Finished
            </span>
          )}
        </nav>
      )}

      <div className="relative my-5 flex flex-1 flex-col">
        {showTranscript ? (
          /* 气泡模式：双人转写流（Transcript 开关打开时） */
          <div className="flex flex-1 flex-col gap-3 overflow-y-auto" aria-live="polite">
            {inlineCue}
            {transcript.length === 0 && <p className="muted">{hint}</p>}
            {transcript.map((b, i) => (
              <div
                key={i}
                className={`${BUBBLE_BASE} ${
                  b.role === 'user'
                    ? 'self-end border-accent-line bg-accent-soft'
                    : 'self-start border-line bg-white'
                }`}
              >
                <span className={BUBBLE_ROLE}>{b.role === 'user' ? 'You' : 'Examiner'}</span>
                <p className="mb-0 mt-1">{b.text}</p>
              </div>
            ))}
            {examinerSpeaking && (
              <p className="m-0 flex items-center gap-2 font-sans text-[13px] leading-none text-ink">
                <span
                  className="h-2.5 w-2.5 animate-reading-pulse rounded-full bg-accent-bright motion-reduce:animate-none"
                  aria-hidden="true"
                />
                Examiner speaking…
              </p>
            )}
            {doneNote}
            <div ref={transcriptEndRef} />
          </div>
        ) : (
          /* 波形模式（默认）：考官说话 = 播放电平；你说话 = 麦电平 */
          <div className="flex flex-1 flex-col items-center justify-center gap-6">
            {inlineCue}
            <VoiceWave source={waveSource} playerRef={playerRef} micLevelRef={micLevelRef} />
            {transcript.length === 0 && <p className="muted m-0 text-center">{hint}</p>}
            {doneNote}
          </div>
        )}

        {part === 'p2_prep' && (
          <div
            className="absolute inset-0 flex animate-rise items-start justify-center overflow-y-auto rounded-xl border border-line bg-white/97 p-4.5 motion-reduce:animate-none"
            role="dialog"
            aria-label="Part 2 preparation"
          >
            <div className="flex w-[min(560px,100%)] flex-col gap-3">
              <div className="flex items-center justify-between gap-3">
                <p className="m-0 font-mono text-xs font-semibold uppercase leading-none tracking-[0.08em] text-accent">
                  Part 2 · Preparation
                </p>
                {prepLeft != null && (
                  <span className="min-w-14 text-right font-mono text-[22px] font-bold leading-none text-ink-strong">
                    {prepLeft}s
                  </span>
                )}
              </div>
              {cueCard && (
                <>
                  <p className="m-0 font-display text-[19px] text-ink-strong">{cueCard.text}</p>
                  {cueCard.bullets?.length > 0 && (
                    <ul className="prompt-list">
                      {cueCard.bullets.map((b, i) => (
                        <li key={i}>{b}</li>
                      ))}
                    </ul>
                  )}
                </>
              )}
              <p className="muted">
                准备中——这段时间你的声音不会进入考试，可放心打草稿、写笔记。
              </p>
              <textarea
                className="resize-y rounded-[10px] border border-line bg-white px-3 py-2.5 font-sans text-[14.5px] leading-[1.6] text-ink-strong transition-colors duration-150 focus:border-accent-bright focus:outline-none focus:ring-2 focus:ring-accent-soft"
                placeholder="Notes…"
                rows={4}
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
              />
              <button
                type="button"
                className="btn-primary self-start"
                onClick={sendReady}
                disabled={readySent}
              >
                {readySent ? 'Starting…' : "I'm ready"}
              </button>
            </div>
          </div>
        )}
      </div>

      <footer className="flex flex-wrap items-center gap-3.5 border-t border-line pt-4">
        {turnMode === 'ptt' && (
          <button
            type="button"
            className={`btn-primary min-w-[148px] touch-none select-none ${
              ptt === 'pressed'
                ? 'bg-accent shadow-[0_0_0_4px_var(--color-accent-soft)]'
                : ptt === 'waiting'
                  ? 'opacity-60'
                  : ''
            }`}
            onPointerDown={pttDown}
            onPointerUp={pttUp}
            onPointerLeave={pttUp}
            onPointerCancel={pttUp}
            onKeyDown={pttKeyDown}
            onKeyUp={pttKeyUp}
            onContextMenu={(e) => e.preventDefault()}
            disabled={status !== 'live' || ptt === 'waiting'}
            aria-pressed={ptt === 'pressed'}
          >
            {ptt === 'pressed'
              ? 'Release to send'
              : ptt === 'waiting'
                ? 'Waiting…'
                : 'Hold to talk'}
          </button>
        )}
        <div
          className="inline-flex overflow-hidden rounded-full border border-line"
          role="group"
          aria-label="Turn mode"
        >
          {['natural', 'ptt'].map((m) => (
            <button
              key={m}
              type="button"
              className={`cursor-pointer border-none px-3.5 py-2 font-mono text-xs font-semibold leading-none transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-50 ${
                turnMode === m ? 'bg-accent-soft text-accent' : 'bg-transparent text-ink'
              }`}
              onClick={() => switchTurn(m)}
              disabled={status === 'ending'}
            >
              {m === 'natural' ? 'Natural' : 'PTT'}
            </button>
          ))}
        </div>
        <button
          type="button"
          className="btn-primary min-w-24"
          onClick={endSession}
          disabled={status !== 'live'}
        >
          End
        </button>
        <span className="muted">
          切换轮次模式会重新开始会话 · End 后自动评测并跳转报告
        </span>
      </footer>
    </section>
  )
}
