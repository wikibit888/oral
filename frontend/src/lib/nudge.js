// 情景沉默分级探询计时器（handoff 011 / docs/SCENARIO_CASE.md D1，仅 scenario 挂载）。
// 阈值与分级判断全在前端——只有前端知道播放队列何时排空、麦克风有没有真实
// 人声；后端只做查表注入 + 8s 防抖（防抖期重复 nudge 被忽略，前端无需精确节流）。
//
// 状态模型（事件驱动，无轮询）：
//   armed（已收 turn_complete，轮到用户）且 AI 播音排空且无人声 → 起倒计时；
//   沉默 ~10s → stage 1（轻提示）→ 再 ~12s → stage 2（句头）→ 再 ~15s →
//   stage 3（给选项）→ 之后停发，用户开口才重置阶梯（spec「可循环或停发」取停发）。
//   重置：真实人声（连续 voiceFrames 帧 ≥ voiceLevel，防单帧爆音/键盘瞬态）
//   清零阶梯，话音落点重起倒计时（卡在句子中间也救）；AI 播音 = 暂停（排空续起，
//   不清阶梯——nudge 自己的语音不该终止升级链）；teaching 事件 = 用户在求助，
//   全量重置；End/卸载 stop() 终态。
// PTT：用户主动控轮、按住才上行，沉默常态化抢话更伤——只发 stage 1 且阈值翻倍。
// 方式 A 不挂载（后端对 ielts_a 的 nudge 也会忽略，双保险）。

// 分级等待毫秒（自上一级起累计；handoff 011 建议值，可调）
export const NUDGE_DELAYS_MS = [10000, 12000, 15000]
// 人声阈值：后端 latency.py SILENCE_THRESHOLD=500（int16 RMS）÷ rmsLevel16
// 满刻度 9000 → 0..1 归一电平；底噪在阈下不重置
export const NUDGE_VOICE_LEVEL = 500 / 9000
// 连续达阈帧数：onFrame ~2.7ms/帧（128 样本 @48k），30 帧 ≈ 80ms 持续发声
// 才算人声——真实音节 100ms+ 轻松达标，键盘瞬态/爆音通常 <50ms 被滤掉
export const NUDGE_VOICE_FRAMES = 30

export function createNudgeTimer({
  send,
  ptt = false,
  delays = NUDGE_DELAYS_MS,
  voiceLevel = NUDGE_VOICE_LEVEL,
  voiceFrames = NUDGE_VOICE_FRAMES,
}) {
  const maxStage = ptt ? 1 : delays.length
  const scale = ptt ? 2 : 1
  let stage = 0 // 已发到的分级；0 = 未发
  let armed = false // 已收 turn_complete（首轮考官开场前不计时）
  let playing = false // AI 播音中（24k 帧到达 → player 排空）
  let speaking = false // 人声进行中（连续达阈帧确认）
  let loud = 0 // 连续达阈帧计数
  let timer = null
  let dead = false

  const cancel = () => {
    if (timer != null) {
      clearTimeout(timer)
      timer = null
    }
  }

  const tryStart = () => {
    if (dead || !armed || playing || speaking || timer != null) return
    if (stage >= maxStage) return
    timer = setTimeout(() => {
      timer = null
      stage += 1
      send({ type: 'nudge', stage })
      tryStart() // AI 不接茬也继续升级；正常路径播音到达即暂停、排空续起
    }, delays[stage] * scale)
  }

  return {
    // turn_complete：轮到用户说话（计时起点条件之一）
    turnComplete() {
      if (dead) return
      armed = true
      tryStart()
    },
    // 24k 音频帧到达：AI 开始播音 → 暂停倒计时（不清阶梯）
    playbackStart() {
      if (dead) return
      playing = true
      cancel()
    },
    // player 队列排空：续起倒计时（重新计满一段，不接续剩余时长）
    playbackIdle() {
      if (dead) return
      playing = false
      tryStart()
    },
    // onFrame 高频调用（~375 次/s）：只在人声上/下沿动 timer，循环内零分配
    voice(level) {
      if (dead) return
      if (level >= voiceLevel) {
        loud += 1
        if (!speaking && loud >= voiceFrames) {
          speaking = true
          stage = 0 // 用户开口 = 重置升级阶梯
          cancel()
        }
      } else {
        loud = 0
        if (speaking) {
          speaking = false
          tryStart() // 话音落点重起倒计时（句中卡壳 10s 后同样救场）
        }
      }
    },
    // teaching 事件（handoff 010 契约）：用户在求助，全量重置
    teaching() {
      if (dead) return
      stage = 0
      loud = 0
      speaking = false
      cancel()
      tryStart()
    },
    // End / 报告跳转 / 连接拆除：终态，之后一切输入 no-op
    stop() {
      dead = true
      cancel()
    },
  }
}
