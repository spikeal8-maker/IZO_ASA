import type { ReactNode } from 'react'
import { ADMIN_MODELS_PAGES, adminModelsPageDefinition, type AdminModelsPage } from './adminModelsRoutes'

export function AdminModelsNavigation({
  active,
  onNavigate,
  status,
}: {
  active: AdminModelsPage
  onNavigate: (page: AdminModelsPage) => void
  status?: ReactNode
}) {
  const page = adminModelsPageDefinition(active)
  return <>
    <nav className="page-tabs" aria-label="Разделы моделей" role="tablist">
      {ADMIN_MODELS_PAGES.map((item) => <button
        key={item.id}
        type="button"
        role="tab"
        aria-selected={active === item.id}
        className={active === item.id ? 'active' : ''}
        onClick={() => onNavigate(item.id)}
      >{item.label}</button>)}
      {status}
    </nav>
    <header className="models-page-head">
      <div>
        <h1>{page.title}</h1>
        <p>{page.description}</p>
      </div>
    </header>
  </>
}
