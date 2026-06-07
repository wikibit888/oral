import { Link } from 'react-router-dom'

// 模式卡共享样式（导航页 + 雅思/情景选择页同款）：
// 链接卡带 hover 上浮 + 翡翠描边 + 投影；纯展示卡（div）只取骨架。
export const CARD_GRID = 'my-5 grid grid-cols-[repeat(auto-fit,minmax(280px,1fr))] gap-5'
export const CARD_BASE =
  'relative block rounded-[18px] border border-line bg-paper px-7 pb-6 pt-6.5 text-inherit no-underline shadow-[0_1px_2px_rgba(10,10,10,0.03)]'
export const CARD_HOVER =
  'group transition-[border-color,transform,box-shadow] duration-300 ease-out hover:-translate-y-[3px] hover:border-accent-bright hover:shadow-[0_12px_32px_-16px_rgba(13,156,110,0.35)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent'
export const CARD_TITLE = 'mb-1 mt-0 font-display text-[27px] font-normal text-ink-strong'
export const CARD_TAG =
  'mb-3 mt-0 font-mono text-xs uppercase leading-[1.4] tracking-[0.08em] text-accent'
export const CARD_BODY = 'mb-3.5 mt-0 text-sm leading-[1.75]'
export const CARD_CTA =
  'inline-flex items-center gap-1.5 text-sm font-semibold text-ink-strong'
export const CARD_ARROW =
  'text-accent transition-transform duration-300 group-hover:translate-x-1'

// 模式选择卡 —— 首页块② 与 /practice 共用（F1「首页两块改造」抽出）。
// IELTS → 选方式 A/B；Scenario → 选 case。CTA 简洁英文（FRONTEND.md §4）。
export default function ModeSelect() {
  return (
    <div className={CARD_GRID}>
      <Link className={`${CARD_BASE} ${CARD_HOVER}`} to="/ielts">
        <span className="absolute right-7 top-6.5 font-mono text-[13px] leading-none text-accent">
          01
        </span>
        <h3 className={CARD_TITLE}>雅思口语</h3>
        <p className={CARD_TAG}>IELTS Speaking</p>
        <p className={CARD_BODY}>
          模拟考试（实时）或分 Part 录音练习。课后出官方四维 band + 诊断报告。
        </p>
        <span className={CARD_CTA}>
          Select <span className={CARD_ARROW}>→</span>
        </span>
      </Link>
      <Link className={`${CARD_BASE} ${CARD_HOVER}`} to="/scenario">
        <span className="absolute right-7 top-6.5 font-mono text-[13px] leading-none text-accent">
          02
        </span>
        <h3 className={CARD_TITLE}>情景对话</h3>
        <p className={CARD_TAG}>Real-life Scenarios</p>
        <p className={CARD_BODY}>
          点餐、会议等真实场景，零压力开口。课后诊断式反馈，不打分。
        </p>
        <span className={CARD_CTA}>
          Select <span className={CARD_ARROW}>→</span>
        </span>
      </Link>
    </div>
  )
}
