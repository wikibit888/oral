import { useEffect, useState } from 'react'

// Live 会话波形（Batch 4 用户决策：默认不显示实时转写——语音训练靠听不靠读，
// AI 说话时出音频响应波形，用户说话切麦电平；Transcript 开关可切回气泡）。
//
// source 决定电平来源：
//   'examiner' → playerRef.current.level()（24k 播放链 AnalyserNode 实时电平）
//   'mic'      → micLevelRef.current（PcmRecorder onFrame 的 RMS，Live.jsx 维护）
//   'idle'     → 0（PTT 松开期 / 未连接）
// 历史滚动：80ms 采样进环形数组，最新在右——「随真实音量跳动」的实感。
// refs 引用稳定，effect 仅随 source 重启（换说话方时清波形属预期）。
const BAR_COUNT = 28
const FLOOR = 0.06 // 静默时的底高，保持波形条可见

export default function VoiceWave({ source, playerRef, micLevelRef }) {
  const [levels, setLevels] = useState(() => Array(BAR_COUNT).fill(0))

  // 切到 idle 清波形：渲染期重置（项目惯例「adjusting state when props
  // change」，effect 内不做同步 setState）
  const [prevSource, setPrevSource] = useState(source)
  if (prevSource !== source) {
    setPrevSource(source)
    if (source === 'idle') setLevels(Array(BAR_COUNT).fill(0))
  }

  useEffect(() => {
    if (source === 'idle') return
    const read = () =>
      source === 'examiner'
        ? (playerRef.current?.level() ?? 0)
        : (micLevelRef.current ?? 0)
    const id = setInterval(() => {
      const v = Math.min(1, read())
      setLevels((prev) => [...prev.slice(1), v])
    }, 80)
    return () => clearInterval(id)
  }, [source, playerRef, micLevelRef])

  const speaking = source !== 'idle'
  const label = source === 'examiner' ? 'Examiner' : source === 'mic' ? 'You' : 'Standby'

  return (
    <div className="flex flex-col items-center gap-4" aria-hidden="true">
      <p className="m-0 flex items-center gap-2 font-mono text-xs font-semibold uppercase tracking-[0.14em] text-ink">
        <span
          className={`h-2 w-2 rounded-full transition-colors duration-300 ${
            speaking
              ? 'animate-reading-pulse bg-accent-bright motion-reduce:animate-none'
              : 'bg-line'
          }`}
        />
        {label}
      </p>
      <div className="flex h-24 items-center gap-[5px]">
        {levels.map((v, i) => (
          <span
            key={i}
            className={`h-full w-1.5 origin-center rounded-full transition-transform duration-100 ease-linear ${
              speaking ? 'bg-accent-bright' : 'bg-line'
            }`}
            style={{ transform: `scaleY(${FLOOR + Math.min(1, v) * (1 - FLOOR)})` }}
          />
        ))}
      </div>
    </div>
  )
}
