// 报告页处理态的轮询决策（纯函数，DOM-free 可测）。F2 起处理态并入
// /report/{id} 单路由双状态（原 F4 独立处理页已删，R7 留跳转兜底）。
// 契约：GET /reports/{id} 的 status ∈ uploaded → processing → done | failed，
// processing 期间附 stage ∈ transcribe → signals → judge（SCHEMA §6）。
// failed 是系统错误终态，文案「处理失败，请重试」（不是「请重录」—— 录音本身没问题）。

export const POLL_INTERVAL_MS = 2500

// status → 下一步动作：continue（继续轮询）/ done（切报告态）/ failed（终态文案）
// / unknown（契约外，当错误展示，防后端新增状态时前端死轮询）。
// 现行契约（SCHEMA §5.1，后端 PR #16 枚举迁移，2026-06-07 联调发现）：status ∈
// live(实时会话中) | recording(方式 B 录音中) | processing | completed | failed。
// 两代并存纵深防御（同 `ready` 先例）：done/ready ≡ completed、uploaded ≡
// 排队中——旧库行 / 后端回滚时前端不挂。
export function classifyStatus(status) {
  if (status === 'completed' || status === 'done' || status === 'ready') return 'done'
  if (status === 'failed') return 'failed'
  if (
    status === 'live' ||
    status === 'recording' ||
    status === 'uploaded' ||
    status === 'processing'
  )
    return 'continue'
  return 'unknown'
}

// 评测流水线分步（R4：契约已含 stage，做真分步进度，不再降级 spinner）。
// label 英文术语 / desc 中文解释（FRONTEND.md §4 文案规则）。
export const STAGES = [
  { key: 'transcribe', label: 'Transcribe', desc: '语音转写' },
  { key: 'signals', label: 'Signals', desc: '客观信号' },
  { key: 'judge', label: 'Judge', desc: '评分诊断' },
]

// {status, stage} → 当前活跃步下标。uploaded（排队，未进流水线）与 stage
// 缺失/契约外（旧后端不回 stage）都归 -1，由调用方降级为 STATUS_TEXT 整体文案。
export function stageIndex(status, stage) {
  if (status !== 'processing') return -1
  return STAGES.findIndex((s) => s.key === stage)
}

// stage 缺位时的整体文案兜底
export const STATUS_TEXT = {
  uploaded: '已上传，排队等待评测…',
  live: '会话进行中，结束后开始评测…',
  recording: '会话进行中，结束后开始评测…',
  processing: '评测中：转写 → 客观信号 → 评分诊断…',
}
