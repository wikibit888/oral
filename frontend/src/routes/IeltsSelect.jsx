import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { IELTS_PARTS, MODE_IELTS } from '../lib/modes.js'
import {
  CARD_BASE,
  CARD_BODY,
  CARD_GRID,
  CARD_TITLE,
} from '../components/ModeSelect.jsx'

// 进步面板目标差距（PRD §8.2）也读这个 key；单 demo 用户存 localStorage 足够。
const TARGET_BAND_KEY = 'targetBand'
const TARGET_BANDS = [5.0, 5.5, 6.0, 6.5, 7.0, 7.5, 8.0]

// F1 雅思选方式（PRD §7.1）：A 模拟考试（实时，F6/P2 落地前为占位）/ B 分模块录音。
export default function IeltsSelect() {
  const navigate = useNavigate()
  const [target, setTarget] = useState(
    () => localStorage.getItem(TARGET_BAND_KEY) ?? '6.5',
  )

  const startExam = () => {
    localStorage.setItem(TARGET_BAND_KEY, target)
    // 实时会话页（F6 实装）；query 对齐 WS 契约 /ws/live?mode=ielts_a（FRONTEND.md §5）
    navigate('/live?mode=ielts_a')
  }

  return (
    <section>
      <h1>雅思口语 · 选方式</h1>
      <div className={CARD_GRID}>
        <div className={CARD_BASE}>
          <h2 className={CARD_TITLE}>A · 模拟考试</h2>
          <p className={CARD_BODY}>
            P1→P2→P3 一气呵成，考官全程零打断，课后完整四维 band。
          </p>
          <label className="my-3 flex items-center gap-2 text-sm">
            目标 band
            <select
              className="rounded-md border border-line bg-paper px-2 py-1 font-[inherit] text-ink-strong transition-colors duration-150 focus:border-accent-bright focus:outline-none focus:ring-2 focus:ring-accent-soft"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
            >
              {TARGET_BANDS.map((b) => (
                <option key={b} value={b.toFixed(1)}>
                  {b.toFixed(1)}
                </option>
              ))}
            </select>
          </label>
          <button type="button" className="btn-primary" onClick={startExam}>
            Start Mock Exam
          </button>
          <p className="muted mt-3">依赖实时对话（建设中），当前为占位流程。</p>
        </div>
        <div className={CARD_BASE}>
          <h2 className={CARD_TITLE}>B · 分模块练习</h2>
          <p className={CARD_BODY}>
            选一个 Part 多题连练：考官读题 → 逐题录音 → Get Review 出 Part
            级报告，不依赖实时对话。
          </p>
          <ul className="m-0 mt-4 flex list-none flex-col gap-2 p-0">
            {IELTS_PARTS.map((p) => (
              <li key={p.value}>
                <Link
                  className="transition-colors duration-150 hover:text-accent-bright"
                  to={`/record?mode=${MODE_IELTS}&sub_mode=${p.value}`}
                >
                  {p.label} · {p.desc}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  )
}
