import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { MODE_IELTS } from '../lib/modes.js'
import {
  PART_META,
  fetchTopics,
  flattenSelectedQuestions,
  partParam,
  topicSelectState,
} from '../lib/questions.js'
import { errorText } from '../lib/api.js'

// F1 选题页（handoff 016）：方式 B 进录音前先选题。按 topic 分组列该 Part **全量**题目
// （GET /questions/topics?part=）；每话题可整组全选（话题级 checkbox，半选 indeterminate）
// 或单题勾选。选完把已选题按原序带进 /record（route state），Record 用它替代随机抽样。
// 每个 Part 只显示自己的题（按 sub_mode 映射 part）。**无 Use All、无 Part 徽标**——
// 话题级 checkbox 即占原 Part 徽标位（对齐用户截图批注）。
export default function RecordSelect() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const mode = params.get('mode')
  const subMode = params.get('sub_mode')
  const part = partParam(subMode)
  const validEntry = mode === MODE_IELTS && part != null
  const meta = PART_META[part]

  const [data, setData] = useState(null) // {part, topics} | null(加载中)
  const [loadError, setLoadError] = useState(null)
  const [loadAttempt, setLoadAttempt] = useState(0)
  const [selected, setSelected] = useState(() => new Set())

  // 加载身份变化（换 Part / Retry）渲染期重置（同 Record.jsx 的 props-change 重置模式）
  const loadKey = `${subMode}|${loadAttempt}`
  const [prevLoadKey, setPrevLoadKey] = useState(loadKey)
  if (prevLoadKey !== loadKey) {
    setPrevLoadKey(loadKey)
    setData(null)
    setLoadError(null)
    setSelected(new Set())
  }

  useEffect(() => {
    if (!validEntry) return
    let alive = true
    fetchTopics(subMode).then(
      (d) => {
        if (alive) setData(d)
      },
      (e) => {
        if (alive) setLoadError(errorText(e))
      },
    )
    return () => {
      alive = false
    }
  }, [validEntry, subMode, loadAttempt])

  const toggleQuestion = (id) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  // 话题级全选/取消：全勾→清掉本话题所有题；否则补齐
  const toggleTopic = (topic) => {
    setSelected((prev) => {
      const next = new Set(prev)
      const ids = topic.questions.map((q) => q.id)
      const allOn = ids.every((id) => next.has(id))
      ids.forEach((id) => (allOn ? next.delete(id) : next.add(id)))
      return next
    })
  }

  const start = () => {
    const questions = flattenSelectedQuestions(data.topics, selected)
    // 已选题随 route state 带进 /record（query 留 mode/sub_mode 保 validEntry 与刷新降级）
    navigate(`/record?mode=${mode}&sub_mode=${subMode}`, { state: { questions } })
  }

  if (!validEntry || !meta) {
    return (
      <section>
        <h1>选择题目</h1>
        <p>
          未选定 Part——请从 <Link to="/ielts">IELTS 选方式</Link> 进入。
        </p>
      </section>
    )
  }

  if (loadError) {
    return (
      <section>
        <h1 className="mt-0">{meta.label} · 选择题目</h1>
        <p className="form-error">{loadError}</p>
        <div className="mt-3 flex items-center gap-3">
          <button type="button" className="btn-primary" onClick={() => setLoadAttempt((n) => n + 1)}>
            Retry
          </button>
          <Link className="text-sm" to="/ielts">
            Back
          </Link>
        </div>
      </section>
    )
  }

  const total = selected.size

  return (
    <section className="pb-24">
      <header>
        <p className="eyebrow">
          <span className="eyebrow-dot" aria-hidden="true" />
          IELTS · 分模块练习 · {meta.label}
        </p>
        <h1 className="mt-0">{meta.label} · 选择题目</h1>
        <p className="muted">勾选要练习的题目——可按话题整组选，或单题选；每个 Part 只列自己的题。</p>
      </header>

      {data == null ? (
        <p className="muted">题目加载中…</p>
      ) : (
        <div className="flex flex-col gap-4">
          {data.topics.map((topic) => {
            const state = topicSelectState(topic, selected)
            return (
              <div
                key={topic.topic_id}
                className="rounded-xl border border-line shadow-[0_1px_2px_rgba(10,10,10,0.02)]"
              >
                {/* 话题头：话题级 checkbox（占原 Part 徽标位）+ 标题 + 题数；半选 indeterminate */}
                <label className="flex cursor-pointer items-center gap-3 border-b border-line px-5 py-3.5">
                  <input
                    type="checkbox"
                    className="h-4.5 w-4.5 shrink-0 accent-accent-bright"
                    checked={state === 'all'}
                    ref={(el) => {
                      if (el) el.indeterminate = state === 'some'
                    }}
                    onChange={() => toggleTopic(topic)}
                  />
                  <span className="font-display text-[17px] text-ink-strong">{topic.title}</span>
                  <span className="muted ml-auto font-mono text-xs">{topic.questions.length}q</span>
                </label>
                <ul className="m-0 flex list-none flex-col p-0">
                  {topic.questions.map((q, i) => (
                    <li key={q.id} className="border-b border-line/60 last:border-b-0">
                      <label className="flex cursor-pointer items-start gap-3 px-5 py-3">
                        <input
                          type="checkbox"
                          className="mt-1 h-4 w-4 shrink-0 accent-accent-bright"
                          checked={selected.has(q.id)}
                          onChange={() => toggleQuestion(q.id)}
                        />
                        <span className="muted mt-0.5 shrink-0 font-mono text-xs">{i + 1}.</span>
                        <span className="text-[15px] leading-[1.5] text-ink-strong">
                          {q.text}
                          {q.bullets && (
                            <ul className="prompt-list mt-1.5">
                              {q.bullets.map((b, j) => (
                                <li key={j}>{b}</li>
                              ))}
                            </ul>
                          )}
                        </span>
                      </label>
                    </li>
                  ))}
                </ul>
              </div>
            )
          })}
        </div>
      )}

      {/* 底部操作条：已选计数 + Start Recording（无 Use All） */}
      <div className="fixed inset-x-0 bottom-0 z-20 border-t border-line bg-white/90 backdrop-blur-lg">
        <div className="mx-auto flex max-w-[980px] items-center justify-between gap-4 px-5 py-3.5 md:px-8">
          <span className="muted text-sm">{total > 0 ? `已选 ${total} 题` : '未选题'}</span>
          <div className="flex items-center gap-3">
            <Link className="text-sm" to="/ielts">
              Back
            </Link>
            <button type="button" className="btn-primary" onClick={start} disabled={total === 0}>
              Start Recording →
            </button>
          </div>
        </div>
      </div>
    </section>
  )
}
