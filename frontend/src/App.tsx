import { lazy, Suspense } from 'react'

const NewStudio = lazy(() => import('./newUi'))
const LegacyApp = lazy(() => import('./LegacyApp'))

function isNewStudioRoute(path: string) {
  if (path === '/' || path === '/new' || path === '/new/') return true
  if (path === '/paint' || path.startsWith('/paint/')) return true
  if (path === '/profile' || path.startsWith('/profile/')) return true
  if (path === '/new/profile' || path.startsWith('/new/profile/')) return true
  return false
}

function isLegacyRoute(path: string) {
  return path === '/old' || path === '/legacy' || path === '/v1'
}

function isAdminRoute(path: string) {
  return path === '/admin' || path.startsWith('/admin/')
}

function isStaticFeedRoute(path: string) {
  return path === '/feed' || path.startsWith('/feed/')
}

function isStaticGalleryRoute(path: string) {
  return path === '/gallery' || path.startsWith('/gallery/')
}

function NotFound() {
  return <div className="app-loading">Страница не найдена</div>
}

function App() {
  const path = window.location.pathname
  if (isStaticFeedRoute(path)) {
    return <div className="app-loading">Загружаем ленту...</div>
  }
  if (isStaticGalleryRoute(path)) {
    return <div className="app-loading">Загружаем галерею...</div>
  }

  const Target = isNewStudioRoute(path) ? NewStudio : (isLegacyRoute(path) || isAdminRoute(path) ? LegacyApp : null)

  if (!Target) {
    return <NotFound />
  }

  return (
    <Suspense fallback={<div className="app-loading">Загружаем интерфейс...</div>}>
      <Target />
    </Suspense>
  )
}

export default App

