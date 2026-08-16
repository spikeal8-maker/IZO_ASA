// Единая верхняя шапка приложения.
//
// Отличается от TopBarV3 тем, что не зависит от обёртки .iv3: собственные
// токены лежат в izoTopBar.css, поэтому её можно ставить на страницы без
// полноэкранной сетки app-shell — тарифы, правовые документы, админку.
//
// Состав задаётся данными, а не разметкой: центральная зона получает список
// разделов, правая — список действий. Это позволяет держать одну шапку с
// одинаковой высотой и брендом на страницах с разным содержимым.

import './izoTopBar.css'

export type TopBarItem = {
  id: string
  label: string
  href?: string
  onClick?: () => void
  active?: boolean
  /** Скрывать подпись на узких экранах, оставляя кнопку нажимаемой. */
  compact?: boolean
  /** Оформить как основное действие (например, «Войти»). */
  cta?: boolean
}

function Item({ item }: { item: TopBarItem }) {
  const className = [
    item.active ? 'is-active' : '',
    item.cta ? 'izo-topbar-cta' : '',
  ].filter(Boolean).join(' ')
  const label = <span className={item.compact ? 'izo-topbar-hide-sm' : undefined}>{item.label}</span>

  if (item.href && !item.onClick) {
    return <a className={`izo-topbar-link ${className}`.trim()} href={item.href}>{label}</a>
  }
  return (
    <button type="button" className={className || undefined} onClick={item.onClick} title={item.label}>
      {label}
    </button>
  )
}

export default function IzoTopBar({
  sections = [],
  actions = [],
  brandHref = '/',
}: {
  sections?: TopBarItem[]
  actions?: TopBarItem[]
  brandHref?: string
}) {
  return (
    <header className="izo-topbar">
      <a className="izo-topbar-brand" href={brandHref} aria-label="ИЗО АСА — на главную">
        <span className="izo-topbar-mark" aria-hidden="true" />
        <span>ИЗО <span className="izo-topbar-accent">АСА</span></span>
      </a>

      {sections.length > 0 && (
        <nav className="izo-topbar-middle" aria-label="Разделы">
          {sections.map((item) => <Item key={item.id} item={item} />)}
        </nav>
      )}

      {sections.length === 0 && <span className="izo-topbar-middle" />}

      {actions.length > 0 && (
        <div className="izo-topbar-actions">
          {actions.map((item) => <Item key={item.id} item={item} />)}
        </div>
      )}
    </header>
  )
}
