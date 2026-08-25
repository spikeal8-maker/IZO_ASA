import type { ReactNode } from 'react'
import { ADMIN_MODELS_PAGES, adminModelsPageDefinition, type AdminModelsPage } from './adminModelsRoutes'

export function AdminModelsNavigation({
  active,
  onNavigate,
  status,
  showTabs = true,
  showHeader = true,
}: {
  active: AdminModelsPage
  onNavigate: (page: AdminModelsPage) => void
  status?: ReactNode
  showTabs?: boolean
  showHeader?: boolean
}) {
  const page = adminModelsPageDefinition(active)
  return <>
    {showTabs && <nav className="page-tabs" aria-label="Разделы моделей" role="tablist">
      {ADMIN_MODELS_PAGES.map((item) => <button
        key={item.id}
        type="button"
        role="tab"
        aria-selected={active === item.id}
        className={active === item.id ? 'active' : ''}
        onClick={() => onNavigate(item.id)}
      >{item.label}</button>)}
      {status}
    </nav>}
    {showHeader && <header className="models-page-head">
      <div>
        <h1>{page.title}</h1>
        <p>{page.description}</p>
      </div>
      {!showTabs && status && <div className="models-page-head-status">{status}</div>}
    </header>}
    {!showHeader && status && <div className="models-page-embedded-status">{status}</div>}
  </>
}
