import { lazy, Suspense } from 'react'

const NewStudio = lazy(() => import('./newUi'))
const LegacyApp = lazy(() => import('./LegacyApp'))

function isNewStudioRoute(path: string) {
  if (path === '/' || path === '/new' || path === '/new/' || path === '/paint' || path.startsWith('/paint/')) return true
  if (path === '/profile' || path.startsWith('/profile/') || path.startsWith('/new/profile')) return true
  if (path === '/old' || path === '/legacy' || path === '/v1') return false
  if (path === '/feed' || path.startsWith('/feed/') || path === '/gallery' || path.startsWith('/gallery/')) return false
  if (path.startsWith('/new/gallery') || path.startsWith('/new/profile')) return false
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

