// 报告页处理态的轮询决策（纯函数，DOM-free 可测）。F2 起处理态并入
// /report/{id} 单路由双状态（原 F4 独立处理页已删，R7 留跳转兜底）。
// 契约：GET /reports/{id} 的 status ∈ uploaded → processing → done | failed，
// processing 期间附 stage ∈ transcribe → signals → judge（SCHEMA §6）。
// failed 是系统错误终态，文案「处理失败，请重试」（不是「请重录」—— 录音本身没问题）。

// 处理态轮询间隔。首轮 tick 立即触发（零首延迟，见 Report.jsx），故此值只决定
// 「报告就绪 → 前端发现」的尾延迟上界：1200ms 把上界从 2.5s 压到 ~1.2s。后端只是
// SQLite 单主键查（reports.py），此 QPS 无压力；更小则空轮询边际递增、收益不抵。
export const POLL_INTERVAL_MS = 1200

// 处理态轮询的墙钟上限：超过仍 processing 即判定「卡住」（上游挂死 / 进程重启掐断
// 后台 finalize），停轮询、切 stalled 态给用户 Retry，而不是无限转圈（故障定位 #17）。
// 取 180s：必须安全大于后端最坏重试总时长（judge_timeout_ms=30s × 约 5 次 ≈ 150s + 退避），
// 否则会把"慢但仍在重试中"的合法路径误判 stalled。即便误判，后端 /retry 也对同一 session
// 在途去重、不会 double-finalize（纵深防御）。正常报告 ≤5s，此上限只为兜底真·卡死。
export const MAX_PROCESSING_MS = 180_000

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
