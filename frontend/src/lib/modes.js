// Mode / sub-mode constants mirroring the backend contract — the exact strings
// app/api/recordings.py validates (VALID_MODES / VALID_SUB_MODES /
// VALID_SCENARIO_CASES, read-only contract). modes.test.js pins them so any
// drift fails loudly instead of as a silent 422.

// 顶层 mode 串（后端 VALID_MODES）。组装 query / 分支判断一律引用常量，
// 不写裸字符串——裸串拼错只会表现为运行时 422 / 渲染错分支（review W4）。
export const MODE_IELTS = 'ielts'
export const MODE_SCENARIO = 'scenario'

export const IELTS_PARTS = [
  { value: 'module_p1', label: 'Part 1', desc: '日常问答 · 短答热身' },
  { value: 'module_p2', label: 'Part 2', desc: 'cue card 长谈 · 评测金矿' },
  { value: 'module_p3', label: 'Part 3', desc: '抽象讨论 · 深入追问' },
]

// 雅思方式 A（模拟考试，实时）的 sub_mode
export const SUB_MODE_EXAM = 'exam'

// label 简洁英文 / desc 中文说明（FRONTEND.md §4，handoff 006）
export const SCENARIO_CASES = [
  { value: 'ordering', label: 'Ordering Food', desc: '餐厅点单：说清需求、礼貌请求' },
  { value: 'meeting', label: 'Work Meeting', desc: '职场会议：有效表达观点' },
]

// case 值 → 展示名（Live 页标题等）；契约外回退原值
export function scenarioLabel(caseId) {
  return SCENARIO_CASES.find((c) => c.value === caseId)?.label ?? caseId
}
