import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import ReportView from '../components/report/ReportView.jsx'
import {
  ieltsModuleReport,
  ieltsReport,
  scenarioReport,
  unscorableReport,
} from '../fixtures/reportFixtures.js'
import { errorText, getReport } from '../lib/api.js'
import { classifyStatus, POLL_INTERVAL_MS, STAGES, stageIndex, STATUS_TEXT } from '../lib/polling.js'

// F2：/report/{id} 单路由双状态（处理态 + 报告态，不做独立处理页）。
//   loading（首查中，只显示中性骨架——Library 进历史报告直接切报告态，不闪处理态）
//   → processing（流水线分步进度 + 报告骨架，2.5s 轮询；原 F4 轮询逻辑迁入）
//   → done 报告态 | failed 终态 | error（404/后端没起/未知状态，可 Retry）。
// demo-* 直出 fixture，零后端可预览（F2 验收入口）。
const DEMOS = {
  'demo-ielts': ieltsReport,
  'demo-ielts-b': ieltsModuleReport, // 方式 B：无 band 有诊断；也是 F3 mock Get Review 的落点
  'demo-scenario': scenarioReport,
  'demo-unscorable': unscorableReport,
}

const initial = (key) => ({
  key,
  phase: 'loading', // loading | processing | done | failed | error
  status: null,
  stage: null,
  report: null,
  error: null,
})

export default function Report() {
  const { sessionId } = useParams()
  const demo = DEMOS[sessionId]
  const [state, setState] = useState(() => initial(sessionId))
  const [attempt, setAttempt] = useState(0) // Retry 按钮 bump 它重启轮询
  // 路由参数变更时在渲染期重置（react.dev「adjusting state when props change」）
  if (state.key !== sessionId) setState(initial(sessionId))

  useEffect(() => {
    if (DEMOS[sessionId]) return // demo 渲染期直出，不打后端
    // AbortController：卸载/重启轮询时真正取消在途 fetch（不只是丢弃结果），
    // 防止慢请求压住下一轮、或卸载后才返回的响应触发 setState（review W1）。
    const ctrl = new AbortController()
    let timer
    const tick = async () => {
      try {
        const res = await getReport(sessionId, { signal: ctrl.signal })
        if (ctrl.signal.aborted) return
        switch (classifyStatus(res.status)) {
          case 'done':
            setState({ key: sessionId, phase: 'done', status: res.status, stage: null, report: res.report, error: null })
            return
          case 'failed':
            setState({ key: sessionId, phase: 'failed', status: res.status, stage: null, report: null, error: null })
            return
          case 'unknown':
            setState({
              key: sessionId,
              phase: 'error',
              status: res.status,
              stage: null,
              report: null,
              error: `后端返回未知状态「${res.status}」，请升级前端或检查后端版本。`,
            })
            return
          default:
            // 首查就拿到 continue 才进处理态——Library 打开已完成报告不闪处理态
            setState({
              key: sessionId,
              phase: 'processing',
              status: res.status,
              stage: res.stage ?? null,
              report: null,
              error: null,
            })
            timer = setTimeout(tick, POLL_INTERVAL_MS)
        }
      } catch (e) {
        if (ctrl.signal.aborted) return // abort 本身不是错误，静默退出
        // 404 = id 不存在；502/504 = 后端没起。停下来给 Retry，不盲目死轮询。
        setState({ key: sessionId, phase: 'error', status: null, stage: null, report: null, error: errorText(e) })
      }
    }
    tick()
    return () => {
      ctrl.abort()
      clearTimeout(timer)
    }
  }, [sessionId, attempt])

  // Retry：重置回 loading + bump attempt 重启轮询 effect
  const retry = () => {
    setState(initial(sessionId))
    setAttempt((n) => n + 1)
  }

  if (demo) return <ReportView report={demo} />

  if (state.phase === 'error') {
    return (
      <section>
        <h1>诊断报告</h1>
        <p className="form-error">{state.error}</p>
        <div className="mt-3 flex items-center gap-3">
          <button type="button" className="btn-primary" onClick={retry}>
            Retry
          </button>
          <Link className="text-sm" to="/">
            Home
          </Link>
        </div>
      </section>
    )
  }

  if (state.phase === 'failed') {
    return (
      <section>
        <h1>处理失败</h1>
        <p>处理失败，请重试。（系统处理出错，不是你的录音有问题）</p>
        <div className="mt-3 flex items-center gap-3">
          <button type="button" className="btn-primary" onClick={retry}>
            Retry
          </button>
          <Link className="text-sm" to="/">
            Home
          </Link>
        </div>
      </section>
    )
  }

  if (state.phase === 'done' && state.report) {
    return <ReportView report={state.report} />
  }

  // loading：中性骨架（不闪流水线）；processing：流水线分步进度 + 骨架
  return (
    <section>
      <h1>诊断报告</h1>
      {state.phase === 'processing' && <Pipeline status={state.status} stage={state.stage} />}
      <ReportSkeleton />
      <p className="muted">session: {sessionId} · 离开本页不影响处理，可稍后回来</p>
    </section>
  )
}

// 评测流水线分步进度（R4 真分步）：stage 在契约内高亮当前步；
// uploaded / stage 缺失（旧后端不回 stage）降级为 STATUS_TEXT 整体文案。
function Pipeline({ status, stage }) {
  const idx = stageIndex(status, stage)
  return (
    <div>
      <ol className="mb-2.5 mt-5 flex list-none flex-wrap gap-6 p-0">
        {STAGES.map((s, i) => {
          const phase = idx < 0 ? 'pending' : i < idx ? 'done' : i === idx ? 'active' : 'pending'
          return (
            <li
              key={s.key}
              className={`flex items-center gap-2 transition-opacity duration-300 ${
                phase === 'pending' ? 'opacity-45' : 'opacity-100'
              }`}
            >
              <span
                className={`h-2.5 w-2.5 rounded-full ${
                  phase === 'done'
                    ? 'bg-accent'
                    : phase === 'active'
                      ? 'animate-pipe-pulse bg-accent-bright motion-reduce:animate-none'
                      : 'bg-line'
                }`}
                aria-hidden="true"
              />
              <span className="font-sans text-sm font-semibold leading-none text-ink-strong">
                {s.label}
              </span>
              <span className="font-sans text-xs leading-none text-ink">{s.desc}</span>
            </li>
          )
        })}
      </ol>
      {idx < 0 && <p className="text-base text-ink-strong">{STATUS_TEXT[status] ?? '查询中…'}</p>}
    </div>
  )
}

// 骨架灰条：微光扫过动画（shimmer），reduced-motion 静止
const SKELETON_BAR =
  'h-3 rounded-md bg-[linear-gradient(90deg,#ececec_25%,#f8f8f8_50%,#ececec_75%)] bg-[length:200%_100%] animate-shimmer motion-reduce:animate-none'

// 报告骨架：占位 Practice Summary / Analysis 等分段的灰条，处理态可见报告轮廓
function ReportSkeleton() {
  return (
    <div className="mt-4.5" aria-hidden="true">
      {[0, 1, 2].map((i) => (
        <div key={i} className="flex flex-col gap-2.5 border-t border-line py-4.5">
          <span className={`${SKELETON_BAR} w-[30%]`} />
          <span className={`${SKELETON_BAR} w-[90%]`} />
          <span className={`${SKELETON_BAR} w-[75%]`} />
        </div>
      ))}
    </div>
  )
}
