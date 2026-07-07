import { lazy, Suspense } from 'react'

const NewStudio = lazy(() => import('./newUi'))
const LegacyApp = lazy(() => import('./LegacyApp'))

function isNewStudioRoute(path: string) {
  if (path === '/' || path === '') return true
  if (path === '/new' || path === '/new/' || path === '/paint' || path.startsWith('/paint/')) return true
  if (path === '/feed' || path.startsWith('/feed/') || path === '/lenta' || path.startsWith('/lenta/')) return true
  if (path.startsWith('/new/gallery') || path.startsWith('/new/profile')) return false
  if (path === '/legacy' || path.startsWith('/legacy/')) return false
  return path.startsWith('/new/')
}

function App() {
  const path = window.location.pathname
  const Target = isNewStudioRoute(path) ? NewStudio : LegacyApp

  return (
    <Suspense fallback={<div className="app-loading">Загружаем интерфейс...</div>}>
      <Target />
    </Suspense>
  )
}

export default App
