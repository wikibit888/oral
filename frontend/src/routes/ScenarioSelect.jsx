import { Link } from 'react-router-dom'
import { MODE_SCENARIO, SCENARIO_CASES } from '../lib/modes.js'
import {
  CARD_ARROW,
  CARD_BASE,
  CARD_BODY,
  CARD_CTA,
  CARD_GRID,
  CARD_HOVER,
  CARD_TITLE,
} from '../components/ModeSelect.jsx'

// F1 情景对话选 case（PRD §7.2）。偏差修正（TODO.frontend F1）：Scenario 是
// **实时会话**路径（CLAUDE.md 架构图 live path），旧版误接录音页已废弃——
// 路由先指向 /live（query 对齐 WS 契约 /ws/live?mode=scenario&case=，
// FRONTEND.md §5），会话页本体 F6 实装。
export default function ScenarioSelect() {
  return (
    <section>
      <h1>情景对话 · 选场景</h1>
      <div className={CARD_GRID}>
        {SCENARIO_CASES.map((c) => (
          <Link
            key={c.value}
            className={`${CARD_BASE} ${CARD_HOVER}`}
            to={`/live?mode=${MODE_SCENARIO}&case=${c.value}`}
          >
            <h2 className={CARD_TITLE}>{c.label}</h2>
            <p className={CARD_BODY}>{c.desc}</p>
            <span className={CARD_CTA}>
              Start <span className={CARD_ARROW}>→</span>
            </span>
          </Link>
        ))}
      </div>
      <p className="muted">情景模式只给诊断式反馈，不出 band、不打总分。</p>
    </section>
  )
}
