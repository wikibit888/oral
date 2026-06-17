import { useRef, useState } from 'react'
import { API_BASE } from '../../lib/api.js'
import { dialogAiLabel } from '../../lib/report.js'

// report 末尾「对话回看」卡片（Req1）：整场人机对话——AI 靠左、You 靠右，
// 每条带文字；有录音的回合可点击回放（用户原声 / 考官原声，纯静态文件）。
// 雅思方式 A + 情景 live 会话才有数据；方式 B / 无回合时整卡不渲染（ReportView 守门）。
const BUBBLE = 'max-w-[76%] rounded-[14px] border px-3.5 py-2.5'
const ROLE = 'font-mono text-[11px] font-semibold uppercase leading-none tracking-[0.08em] text-ink'
const PLAY_BTN =
  'shrink-0 cursor-pointer rounded-full border border-accent-line bg-accent-soft px-2.5 py-1 font-mono text-[11px] font-semibold leading-none text-accent transition-colors duration-150 hover:border-accent-bright'

export default function DialogCard({ turns, mode, scenarioCase }) {
  const audioRef = useRef(null)
  const [playing, setPlaying] = useState(null) // 正在播的 turn_id
  const aiLabel = dialogAiLabel(mode, scenarioCase)

  const play = (turn) => {
    const el = audioRef.current
    if (!el || !turn.audio_url) return
    if (playing === turn.turn_id && !el.paused) {
      el.pause()
      setPlaying(null)
      return
    }
    el.src = `${API_BASE}${turn.audio_url}`
    el.play()
      .then(() => setPlaying(turn.turn_id))
      .catch(() => setPlaying(null)) // 文件缺失/格式问题：静默退回，不炸报告页
  }

  return (
    <section className="border-t border-line py-5">
      <h2 className="mb-3 mt-0 text-lg font-semibold text-ink-strong">对话回看</h2>
      <audio ref={audioRef} onEnded={() => setPlaying(null)} className="hidden" />
      <div className="flex flex-col gap-3">
        {turns.map((t) => {
          const user = t.role === 'user'
          return (
            <div
              key={t.turn_id}
              className={`${BUBBLE} ${
                user ? 'self-end border-accent-line bg-accent-soft' : 'self-start border-line bg-white'
              }`}
            >
              <div className="flex items-center justify-between gap-3">
                <span className={ROLE}>{user ? 'You' : aiLabel}</span>
                {t.audio_url && (
                  <button type="button" className={PLAY_BTN} onClick={() => play(t)}>
                    {playing === t.turn_id ? 'Pause' : 'Play'}
                  </button>
                )}
              </div>
              {t.text && <p className="mb-0 mt-1">{t.text}</p>}
            </div>
          )
        })}
      </div>
    </section>
  )
}
