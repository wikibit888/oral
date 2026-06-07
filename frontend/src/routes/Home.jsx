import { Link } from 'react-router-dom'
import ModeSelect from '../components/ModeSelect.jsx'

// 声波装饰条：口语产品的均衡器律动（纯 CSS 动画，reduced-motion 关闭）
const WAVE_BARS = [
  { delay: '0s', opacity: 'opacity-40' },
  { delay: '0.22s', opacity: 'opacity-65' },
  { delay: '0.44s', opacity: '' },
  { delay: '0.66s', opacity: 'opacity-65' },
  { delay: '0.88s', opacity: 'opacity-40' },
]

// 入场动画：编辑风逐段上浮（reveal），motion-reduce 直接静止。
// 注意：animation-delay 走 style prop —— Tailwind 静态扫描提不到插值出来的
// arbitrary class。
const REVEAL = 'animate-rise motion-reduce:animate-none'

// F1 模式选择 — PRD §9 流程图第一层：雅思 / 情景对话。
// 导航页设计：黑白 + 翡翠绿编辑风（骨架参考 joespeaking.com）——
// 块① hero 介绍（衬线大标题 + 价值主张 + CTA 锚点），块② 两张模式卡入口。
export default function Home() {
  return (
    <div>
      <section className="relative pb-[52px] pt-9 md:pb-[72px] md:pt-16">
        <div
          className="absolute right-2.5 top-[110px] hidden h-[72px] items-center gap-2 md:flex"
          aria-hidden="true"
        >
          {WAVE_BARS.map((bar, i) => (
            <span
              key={i}
              className={`h-full w-[7px] animate-equalize rounded-full bg-accent-bright motion-reduce:animate-none ${bar.opacity}`}
              style={{ animationDelay: bar.delay }}
            />
          ))}
        </div>
        <p className={`eyebrow ${REVEAL}`} style={{ animationDelay: '0.08s' }}>
          <span className="eyebrow-dot" aria-hidden="true" />
          AI 口语教练 · 随时在线
        </p>
        <h1
          className={`mb-6 mt-0 font-display text-[clamp(44px,7.5vw,76px)] font-normal leading-[1.12] text-ink-strong [&_em]:text-accent ${REVEAL}`}
          style={{ animationDelay: '0.08s' }}
        >
          随时开口，
          <br />
          零压力练&nbsp;<em>Speaking</em>
        </h1>
        <p
          className={`mb-[34px] max-w-[560px] text-[17px] leading-[1.85] ${REVEAL}`}
          style={{ animationDelay: '0.16s' }}
        >
          介于「Duolingo 没有真实口语」和「真人外教贵且有压力」之间——
          和 AI 考官沉浸式实时对话，课后拿到逐句诊断报告，每一次开口都被认真对待。
        </p>
        <div className={`mb-10 md:mb-14 ${REVEAL}`} style={{ animationDelay: '0.24s' }}>
          <a className="btn-dark" href="#modes">
            Start Practicing <span className="arrow">↓</span>
          </a>
        </div>
        <ul
          className={`m-0 grid max-w-[720px] list-none grid-cols-1 gap-4 border-t border-line p-0 pt-6.5 text-sm md:grid-cols-3 md:gap-6 ${REVEAL}`}
          style={{ animationDelay: '0.32s' }}
        >
          {[
            ['实时对话', '真实开口说，不是点选择题'],
            ['课后诊断', '逐句报告 + IELTS 四维 band'],
            ['进步曲线', '每次练习入库，提升看得见'],
          ].map(([title, desc]) => (
            <li key={title} className="flex flex-col gap-1">
              <strong className="flex items-center gap-2 text-[15px] text-ink-strong before:h-0.5 before:w-3.5 before:rounded-xs before:bg-accent-bright before:content-['']">
                {title}
              </strong>
              {desc}
            </li>
          ))}
        </ul>
      </section>

      <section
        className={`scroll-mt-18 border-t border-line pb-10 pt-13 ${REVEAL}`}
        style={{ animationDelay: '0.42s' }}
        id="modes"
      >
        <p className="eyebrow">
          <span className="eyebrow-dot" aria-hidden="true" />
          练习模式
        </p>
        <h2 className="mb-7 mt-0 font-display text-4xl font-normal text-ink-strong">
          选择练习模式
        </h2>
        {/* 块②与 /practice 共用 ModeSelect（F1 首页两块改造） */}
        <ModeSelect />
        <p className="mt-9 text-[12.5px] text-ink opacity-75">
          <span>dev · F2 报告示例：</span>
          <Link to="/report/demo-ielts">雅思A</Link>
          {' · '}
          <Link to="/report/demo-ielts-b">雅思B</Link>
          {' · '}
          <Link to="/report/demo-scenario">情景</Link>
          {' · '}
          <Link to="/report/demo-unscorable">不可评</Link>
        </p>
      </section>
    </div>
  )
}
