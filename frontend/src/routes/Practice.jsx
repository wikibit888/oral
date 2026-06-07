import ModeSelect from '../components/ModeSelect.jsx'

// /practice（F1）：Practice 选项卡点击进入的模式选择页；hover 下拉可跳过本页
// 直达 /ielts、/scenario（FRONTEND.md §1）。内容与首页块② 一致（共用 ModeSelect）。
export default function Practice() {
  return (
    <section>
      <p className="eyebrow">
        <span className="eyebrow-dot" aria-hidden="true" />
        练习模式
      </p>
      <h1>选择练习模式</h1>
      <ModeSelect />
    </section>
  )
}
