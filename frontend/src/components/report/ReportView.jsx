import BandRadar from './BandRadar.jsx'
import { DIMENSION_META, fmtNum, isIelts, isUnscorable, formatDuration } from '../../lib/report.js'

// 报告页共享小样式：引用条（mono 底纹）/ 节内小标题 / 翡翠建议行
const QUOTE_LIST = 'my-2 list-none p-0'
const QUOTE_ITEM = 'my-1 rounded bg-code-bg px-2 py-1 font-mono text-[13px] leading-normal'
const SUB_H3 = 'mb-1.5 mt-4 text-sm font-semibold text-ink-strong'
const SUGGESTION = 'my-1.5 text-accent'

// 优先级徽章配色（severity 三档，色值沿用原 #dc2626/#d97706/#059669 体系）
const SEV_BASE = 'rounded px-[7px] py-[3px] font-mono text-[11px] uppercase leading-none'
const SEV_KIND = {
  high: 'bg-[rgba(220,38,38,0.12)] text-[#dc2626]',
  medium: 'bg-[rgba(217,119,6,0.12)] text-[#d97706]',
  low: 'bg-[rgba(5,150,105,0.12)] text-[#059669]',
}

// Presentational report renderer. Takes one Report object (app/report.py shape)
// and draws every section. Band blocks (overall + radar + per-dimension) render
// only for IELTS; Scenario reports (dimensions/overall_band null) skip them but
// keep the shared diagnostics. Pure + fixture-driven (TODO.frontend F2).
// 标签语言（handoff 013，用户确认 2026-06-07）：章节标题中文，评分术语保留
// 英文（IELTS Band Scores / Overall Band / Fossilization / 四维 label）；
// severity 徽章是数据枚举不翻译。
// 按内容显隐（handoff 014）：rewrites 空列表整节不渲染（按数据不按 mode——
// 情景恒空、雅思 unscorable 同样受益）；summary 非空才出末尾「总结」节
// （仅情景非 null；雅思恒 null，情景 judge 漏填降级 null）。
export default function ReportView({ report }) {
  const ielts = isIelts(report)
  const { practice_summary: summary, dimensions, overall_band, diagnostics: dx } = report

  return (
    <div>
      <h1>诊断报告</h1>

      <Section title="练习概况">
        <div className="flex flex-wrap gap-4">
          <Stat label="开口时长" value={formatDuration(summary.speaking_time_s)} />
          <Stat label="会话数" value={summary.sessions} />
          <Stat label="录音数" value={summary.recordings} />
        </div>
      </Section>

      {/* 雅思不可评分支（G3）：band 区整体缺席，给出原因 + 重录指引；
          诊断层照常渲染（可能为空结构）。情景对话 unscorable=false 不进这里。 */}
      {isUnscorable(report) && (
        <div className="my-5 rounded-xl border border-[rgba(217,119,6,0.35)] bg-[rgba(217,119,6,0.07)] px-5 py-4">
          <strong className="text-[#b45309]">无法评分</strong>
          <p className="mb-0 mt-1.5">
            {report.unscorable_reason ??
              '本次录音无法可靠评分（静音 / 非英语 / 录音问题），请重录后再提交。'}
          </p>
        </div>
      )}

      {ielts && (
        <Section title="IELTS Band Scores">
          <div className="flex flex-wrap items-center gap-6">
            <div className="flex flex-col items-center">
              <span className="text-[56px] font-bold leading-none text-accent">
                {fmtNum(overall_band)}
              </span>
              <span className="mt-1.5 font-mono text-xs leading-none">Overall Band</span>
            </div>
            <div className="min-w-[280px] flex-1">
              <BandRadar dimensions={dimensions} />
            </div>
          </div>
          <div className="mt-4 grid grid-cols-[repeat(auto-fit,minmax(300px,1fr))] gap-3">
            {DIMENSION_META.map(({ key, label }) => (
              <DimensionCard key={key} label={label} dim={dimensions[key]} />
            ))}
          </div>
        </Section>
      )}

      <Section title="综合分析">
        <h3 className={SUB_H3}>口头禅 / 高频用语</h3>
        <ul className="m-0 flex list-none flex-wrap gap-2 p-0">
          {dx.common_patterns.map((p, i) => (
            <li key={i} className="rounded-2xl border border-line px-3 py-1 text-[13px]">
              {p.pattern} <span className="font-semibold text-accent">×{p.count}</span>
            </li>
          ))}
        </ul>
        <h3 className={SUB_H3}>句式分析</h3>
        <p className="my-1.5">{dx.syntactic_analysis.observation}</p>
        <p className={SUGGESTION}>建议：{dx.syntactic_analysis.suggestion}</p>
      </Section>

      <Section title="高频错误">
        <span className="mb-2.5 inline-block rounded-2xl border border-accent-line bg-accent-soft px-3 py-1 text-[13px] text-accent">
          词汇多样性 {fmtNum(dx.vocabulary_diversity_pct)}%
        </span>
        <ul className="m-0 list-none p-0">
          {dx.frequent_errors.map((e, i) => (
            <li key={i} className="flex items-center gap-2.5 border-b border-line py-1.5">
              <span className="rounded bg-code-bg px-2 py-0.5 text-xs">{e.category}</span>
              <span className="flex-1">{e.desc}</span>
              <span className="font-semibold text-accent">×{e.count}</span>
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Fossilization 与自我更正">
        <div className="grid grid-cols-[repeat(auto-fit,minmax(260px,1fr))] gap-5">
          <div>
            <h3 className={SUB_H3}>Fossilization</h3>
            {dx.fossilized_errors.map((f, i) => (
              <div key={i}>
                <p className="my-1.5">{f.desc}</p>
                <ul className={QUOTE_LIST}>
                  {f.occurrences.map((o, j) => (
                    <li key={j} className={QUOTE_ITEM}>
                      “{o}”
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
          <div>
            <h3 className={SUB_H3}>自我更正</h3>
            <ul className="list-none p-0 text-sm">
              {dx.self_corrections.map((c, i) => (
                <li key={i} className="py-1">
                  <s>{c.initial}</s> → <strong>{c.corrected}</strong>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </Section>

      <Section title="优先改进项">
        {/* preflight 重置了 list-style——序号/圆点列表显式声明 */}
        <ol className="list-decimal pl-4.5">
          {dx.top_priorities.map((p, i) => (
            <li key={i} className="mb-4">
              <div className="flex items-center gap-2">
                <span className={`${SEV_BASE} ${SEV_KIND[p.severity] ?? ''}`}>{p.severity}</span>
                <strong>{p.title}</strong>
              </div>
              <p className="my-1.5">{p.explanation}</p>
              <ul className={QUOTE_LIST}>
                {p.examples.map((ex, j) => (
                  <li key={j} className={QUOTE_ITEM}>
                    “{ex}”
                  </li>
                ))}
              </ul>
              <p className={SUGGESTION}>快速修正：{p.quick_fix}</p>
            </li>
          ))}
        </ol>
      </Section>

      {/* 改写示范按内容显隐（handoff 014）：情景恒为空列表（会话内 grammar_note
          纠错已承担逐句纠正）、雅思 unscorable 也是空——按数据判断不按 mode */}
      {(dx.rewrites?.length ?? 0) > 0 && (
        <Section title="改写示范">
          <div className="flex flex-col gap-3">
            {dx.rewrites.map((r, i) => (
              <div key={i} className="border-l-[3px] border-accent py-1 pl-3">
                <p className="my-1.5 text-ink">原句：{r.original}</p>
                <p className="my-1.5 font-semibold text-ink-strong">改写：{r.rewrite}</p>
                <p className="my-1.5 text-[13px] text-ink">理由：{r.reason}</p>
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* 总结（handoff 014）：仅情景非空（先亮点 → 主要问题 → 提升方向，judge
          产出中文段落）；雅思恒 null、情景 judge 漏填降级 null —— 整节不渲染 */}
      {dx.summary && (
        <Section title="总结">
          <p className="my-1.5">{dx.summary}</p>
        </Section>
      )}
    </div>
  )
}

function Section({ title, children }) {
  return (
    <section className="border-t border-line py-5">
      <h2 className="mb-3 mt-0 text-lg font-semibold text-ink-strong">{title}</h2>
      {children}
    </section>
  )
}

function Stat({ label, value }) {
  return (
    <div className="flex min-w-[96px] flex-col items-center rounded-lg border border-line px-5 py-3.5 shadow-[0_1px_2px_rgba(10,10,10,0.02)]">
      <span className="text-2xl font-semibold text-ink-strong">{value}</span>
      <span className="mt-1 text-xs">{label}</span>
    </div>
  )
}

function DimensionCard({ label, dim }) {
  if (!dim) return null // judge 输出缺维时跳过该卡，不炸整页
  return (
    <div className="rounded-lg border border-line p-3.5 shadow-[0_1px_2px_rgba(10,10,10,0.02)]">
      <div className="flex items-baseline justify-between">
        <span className="font-semibold text-ink-strong">{label}</span>
        <span className="text-[22px] font-bold text-accent">{fmtNum(dim.band)}</span>
      </div>
      <p className="my-1.5 text-sm">{dim.descriptor_match}</p>
      <ul className={QUOTE_LIST}>
        {(dim.evidence ?? []).map((e, i) => (
          <li key={i} className={QUOTE_ITEM}>
            “{e}”
          </li>
        ))}
      </ul>
      <ul className="mb-0 mt-2 list-disc pl-4.5 text-sm">
        {(dim.suggestions ?? []).map((s, i) => (
          <li key={i}>{s}</li>
        ))}
      </ul>
    </div>
  )
}
