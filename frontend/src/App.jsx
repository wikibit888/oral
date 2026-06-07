import { Navigate, NavLink, Route, Routes, useLocation, useParams } from 'react-router-dom'
import Home from './routes/Home.jsx'
import Practice from './routes/Practice.jsx'
import IeltsSelect from './routes/IeltsSelect.jsx'
import ScenarioSelect from './routes/ScenarioSelect.jsx'
import Record from './routes/Record.jsx'
import Report from './routes/Report.jsx'
import Library from './routes/Library.jsx'
import Review from './routes/Review.jsx'
import Live from './routes/Live.jsx'
import NotFound from './routes/NotFound.jsx'

// 沉浸态路由：实时会话页 / 录音页进行中隐藏顶栏，只留页内 End / Give Up 出口
// —— 保沉浸感，防误点导航丢掉 Live 会话（FRONTEND.md §1）。
const IMMERSIVE_PREFIXES = ['/live', '/record']

// 顶栏导航链接：active 态走 NavLink 函数形式拼 Tailwind 工具类
const navLinkCls = ({ isActive }) =>
  `inline-block rounded-lg px-3.5 py-2 font-sans text-sm font-semibold leading-none no-underline transition-colors duration-150 ${
    isActive ? 'text-accent' : 'text-ink hover:bg-accent-soft hover:text-ink-strong'
  }`

const dropLinkCls = ({ isActive }) =>
  `rounded-md px-3 py-2.5 font-sans text-sm font-medium leading-none no-underline transition-colors duration-150 ${
    isActive ? 'text-accent' : 'text-ink hover:bg-accent-soft hover:text-ink-strong'
  }`

// 顶部导航（F1）：Practice（hover 下拉 IELTS / Scenario 直达下一级）/ Library / Review。
// 导航选项卡一律简洁英文（FRONTEND.md §4）。
function TopNav() {
  return (
    <nav className="flex items-center gap-1">
      {/* hover / focus-within 展开下拉（键盘 Tab 同样可达，FRONTEND.md §1） */}
      <div className="group relative">
        <NavLink to="/practice" className={navLinkCls}>
          Practice
        </NavLink>
        <div className="invisible absolute left-0 top-full z-20 flex min-w-[150px] translate-y-1 flex-col rounded-[10px] border border-line bg-white/95 p-1.5 opacity-0 shadow-[0_8px_24px_rgba(0,0,0,0.08)] backdrop-blur-sm transition-[opacity,transform,visibility] duration-150 group-focus-within:visible group-focus-within:translate-y-0 group-focus-within:opacity-100 group-hover:visible group-hover:translate-y-0 group-hover:opacity-100">
          <NavLink to="/ielts" className={dropLinkCls}>
            IELTS
          </NavLink>
          <NavLink to="/scenario" className={dropLinkCls}>
            Scenario
          </NavLink>
        </div>
      </div>
      <NavLink to="/library" className={navLinkCls}>
        Library
      </NavLink>
      <NavLink to="/review" className={navLinkCls}>
        Review
      </NavLink>
    </nav>
  )
}

// 旧 /processing/:id 内链兜底（R7）：处理态已并入报告页单路由。
function ProcessingRedirect() {
  const { sessionId } = useParams()
  return <Navigate to={`/report/${sessionId}`} replace />
}

export default function App() {
  const { pathname } = useLocation()
  const immersive = IMMERSIVE_PREFIXES.some((p) => pathname.startsWith(p))

  return (
    <div className="flex min-h-svh flex-col">
      {!immersive && (
        <header className="sticky top-0 z-10 flex items-center justify-between border-b border-line bg-white/85 px-5 py-3.5 backdrop-blur-lg md:px-8 md:py-4">
          {/* 编辑风句点：站名后缀一枚翡翠绿点 */}
          <NavLink
            to="/"
            className="font-display text-[22px] tracking-[0.01em] text-ink-strong no-underline after:text-accent-bright after:content-['.']"
          >
            AI口语伴读
          </NavLink>
          <TopNav />
        </header>
      )}
      <main className="mx-auto w-full max-w-[980px] flex-1 px-5 pb-10 pt-6 md:px-8 md:pb-12 md:pt-8">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/practice" element={<Practice />} />
          <Route path="/ielts" element={<IeltsSelect />} />
          <Route path="/scenario" element={<ScenarioSelect />} />
          <Route path="/record" element={<Record />} />
          <Route path="/report/:sessionId" element={<Report />} />
          <Route path="/library" element={<Library />} />
          <Route path="/review" element={<Review />} />
          <Route path="/live" element={<Live />} />
          {/* 路由重构兜底（R7）：Processing 并入 /report/{id}；Progress 更名 Review */}
          <Route path="/processing/:sessionId" element={<ProcessingRedirect />} />
          <Route path="/progress" element={<Navigate to="/review" replace />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
    </div>
  )
}
