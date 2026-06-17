import { useState } from 'react'
import { coachCardPreview } from '../lib/live.js'

// 会话内教练卡片（仅 scenario Dialog 视图）：静默挂在 You 气泡下方，默认折叠、
// 点击展开（用户决策 2026-06-17）。中性灰底——最不抢对话气泡的戏。
//   teaching   = 中文求助：你说/你问「中文」→ 英文 + 例句（bulb 图标）
//   correction = 语法纠错：错误类型 + 你说 ~~错~~ → 改成 对（pencil 图标）
// 数据来自下行 teaching / correction 事件（lib/live.js coachCardFromEvent）。

function CardIcon({ variant }) {
  // 16px 描边图标，沿用 RecordSelect 的 viewBox 20 / currentColor 风格
  return (
    <svg className="h-4 w-4 shrink-0 text-accent" viewBox="0 0 20 20" fill="none" aria-hidden="true">
      {variant === 'teaching' ? (
        <>
          <circle cx="10" cy="8" r="4.3" stroke="currentColor" strokeWidth="1.5" />
          <path
            d="M8 13.4h4M8.7 15.4h2.6"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
          />
        </>
      ) : (
        <path
          d="M4 16l.8-3L12 5.8l2.2 2.2L7 15.2 4 16zM11.4 6.5l2.1 2.1"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      )}
    </svg>
  )
}

export default function CoachCard({ card }) {
  const [open, setOpen] = useState(false)
  const teaching = card.variant === 'teaching'
  const label = teaching ? 'Language help' : 'Grammar fix'

  return (
    <div className="max-w-[66%] self-end overflow-hidden rounded-[11px] border border-line bg-paper-soft">
      <button
        type="button"
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <CardIcon variant={card.variant} />
        <span className="shrink-0 font-mono text-[11px] font-semibold uppercase tracking-[0.03em] text-ink">
          {label}
        </span>
        <span className="truncate text-[13px] text-ink-strong">{coachCardPreview(card)}</span>
        <svg
          className={`ml-auto h-4 w-4 shrink-0 text-ink transition-transform duration-150 ${open ? 'rotate-90' : ''}`}
          viewBox="0 0 20 20"
          fill="none"
          aria-hidden="true"
        >
          <path
            d="M7.5 5l5 5-5 5"
            stroke="currentColor"
            strokeWidth="1.7"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>

      {open && (
        <div className="border-t border-line px-3 pb-2.5 pt-2">
          {teaching ? <TeachingBody card={card} /> : <CorrectionBody card={card} />}
        </div>
      )}
    </div>
  )
}

function TeachingBody({ card }) {
  const ask = card.kind === 'explicit_ask'
  return (
    <>
      {card.chinese && (
        <p className="m-0 text-[12.5px] text-ink">
          {ask ? '你问' : '你说'} <span className="text-ink-strong">“{card.chinese}”</span>
        </p>
      )}
      {card.english && (
        <p className="m-0 mt-1.5 text-[15px] font-semibold text-accent">{card.english}</p>
      )}
      {card.example && (
        <p className="m-0 mt-1.5 rounded-lg border border-line bg-white px-2.5 py-1.5 font-mono text-[12.5px] leading-relaxed text-ink">
          e.g. {card.example}
        </p>
      )}
    </>
  )
}

function CorrectionBody({ card }) {
  return (
    <>
      {card.note && (
        <span className="inline-block rounded-md border border-line bg-white px-2 py-0.5 font-mono text-[11px] text-ink">
          {card.note}
        </span>
      )}
      {card.original && (
        <p className="m-0 mt-1.5 text-[13px] text-ink">
          你说 <s>{card.original}</s>
        </p>
      )}
      {card.fixed && (
        <p className="m-0 mt-1 text-[15px] font-semibold text-accent">改成 {card.fixed}</p>
      )}
    </>
  )
}
