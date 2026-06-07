// Shared route-shell placeholder. Each F0 route renders one of these so the
// nav flow is walkable now; later F-tasks replace the page body with real UI.
export default function Placeholder({ task, title, children }) {
  return (
    <section>
      <span className="inline-block rounded border border-accent-line bg-accent-soft px-2 py-1 font-mono text-xs leading-none text-accent">
        {task}
      </span>
      <h1>{title}</h1>
      {children}
    </section>
  )
}
