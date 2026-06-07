// F6 实时会话的纯函数层（DOM-free 可测）。WS 契约：FRONTEND.md §5 /
// SCHEMA §6.1 / handoff 001 —— /ws/live?mode=ielts_a|scenario&case&turn。

// query 校验：后端同样校验并回 error 事件，但前端提前挡住能少建一条废连接
export function validateLiveParams({ mode, caseId }) {
  if (mode !== 'ielts_a' && mode !== 'scenario') {
    return 'mode 参数缺失或非法（ielts_a | scenario）——请从 Practice 入口进入。'
  }
  if (mode === 'scenario' && !caseId) {
    return 'scenario 模式必须带 case 参数（ordering | meeting）——请从场景选择页进入。'
  }
  return null
}

// turn 模式归一化：合法值 ptt | natural（SCHEMA §6.1，后端默认 natural）；
// URL 上的非法/缺失值一律落 natural，不报错——turn 是 UI 开关不是入口参数
export function normalizeTurn(value) {
  return value === 'ptt' ? 'ptt' : 'natural'
}

// WS 地址：走 vite 代理（/ws → :8000，ws:true），生产同源直连
export function buildLiveUrl({ mode, caseId, turn }, loc = window.location) {
  const proto = loc.protocol === 'https:' ? 'wss' : 'ws'
  const q = new URLSearchParams({ mode })
  if (caseId) q.set('case', caseId)
  if (turn) q.set('turn', turn)
  return `${proto}://${loc.host}/ws/live?${q.toString()}`
}

// 下行 text 帧 → 事件对象；非 JSON / 无 type 一律 null（忽略不致崩）
export function parseEvent(data) {
  try {
    const ev = JSON.parse(data)
    return typeof ev?.type === 'string' ? ev : null
  } catch {
    return null
  }
}

// transcript_delta 合并：同 role 连续增量并入同一气泡，role 切换开新气泡
// （双人转写流，FRONTEND.md §2 会话页）
export function appendDelta(list, { role, text }) {
  const last = list[list.length - 1]
  if (last && last.role === role) {
    return [...list.slice(0, -1), { role, text: last.text + text }]
  }
  return [...list, { role, text }]
}

// 方式 A 导演 part_change（handoff 005 / IELTS.md §2，009 终版模型驱动：
// 转场宣告由考官语音承担，仍处原 part，契约值只有 p1/p2_*/p3/done）→
// 进度条阶段：p2_prep / p2_talk / p2_followup 合并显示 "Part 2"；done =
// 考试收尾（考官说结束语，前端引导点 End）；契约外值 null（前向兼容忽略）。
export const PART_STAGES = ['Part 1', 'Part 2', 'Part 3']

export function partStage(part) {
  if (part === 'p1') return 'Part 1'
  if (part === 'p2_prep' || part === 'p2_talk' || part === 'p2_followup') return 'Part 2'
  if (part === 'p3') return 'Part 3'
  if (part === 'done') return 'done'
  return null
}

// PTT 显式轮次状态机（handoff 004 / FRONTEND §3）：
//   idle --press--> pressed --release--> waiting --turn_complete--> idle
// waiting = 已发 turn_end、等考官应答完毕（turn_complete）才解锁下一次按键；
// 非法迁移一律原状返回（如 idle 收 release、waiting 收 press），按键乱序不脏状态。
// release 的时序约束在组件侧：先 batcher.flush() 再发 turn_end——反序会把按住
// 末尾 ≤200ms 尾音留在批里，turn_end 先到、尾音后到，后端断轮点漂移（004 契约）。
export function pttReducer(state, action) {
  switch (action) {
    case 'press':
      return state === 'idle' ? 'pressed' : state
    case 'release':
      return state === 'pressed' ? 'waiting' : state
    case 'turn_complete':
      return state === 'waiting' ? 'idle' : state
    case 'reset': // 重连/换模式：无条件回 idle
      return 'idle'
    default:
      return state
  }
}

// 延迟徽章文案（FRONTEND §3 / handoff 004）：后端每轮考官首帧后发
// {type:"latency_ms", value:<int>}。ptt 以 turn_end 为锚是精确测量；
// natural 含 VAD 判停耗时（参考量级 ~2300ms vs ptt ~900ms），标 ≈ 近似。
export function formatLatency(value, turn) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  const ms = `${Math.round(value)} ms`
  return turn === 'ptt' ? ms : `≈ ${ms}`
}

// 上行帧合批：worklet 帧 ~128 样本/帧（@16k 降采样后约 40 样本 ≈ 80 字节），
// 直发会打出 ~375 msg/s 的碎包——攒到 ≥batchSamples（默认 3200 ≈ 200ms）再发。
export function createFrameBatcher(send, batchSamples = 3200) {
  let chunks = []
  let total = 0
  return {
    push(int16) {
      chunks.push(int16)
      total += int16.length
      if (total < batchSamples) return
      this.flush()
    },
    flush() {
      if (total === 0) return
      const merged = new Int16Array(total)
      let off = 0
      for (const c of chunks) {
        merged.set(c, off)
        off += c.length
      }
      chunks = []
      total = 0
      send(merged)
    },
  }
}
