import { lazy, Suspense, useEffect } from 'react'
import { appShellSeo, applyClientSeo } from './seo'

const NewStudio = lazy(() => import('./newUi'))
const LegacyApp = lazy(() => import('./LegacyApp'))
const AdminApp = lazy(() => import('./AdminApp'))
const PaymentResultPage = lazy(() => import('./PaymentResultPage'))
const CommercePage = lazy(() => import('./CommercePage'))
const PhoneApp = lazy(() => import('./phone/PhoneApp'))

function isNewStudioRoute(path: string) {
  if (path === '/') return true
  if (path === '/paint' || path.startsWith('/paint/')) return true
  if (path === '/video' || path.startsWith('/video/')) return true
  if (path === '/audio' || path.startsWith('/audio/')) return true
  if (path === '/3d' || path.startsWith('/3d/')) return true
  if (path === '/chat' || path.startsWith('/chat/')) return true
  if (path === '/profile' || path.startsWith('/profile/')) return true
  return false
}

function canonicalNewPath(path: string) {
  if (path === '/new' || path === '/new/') return '/'
  if (path === '/new/profile' || path.startsWith('/new/profile/')) return path.replace(/^\/new/, '')
  if (path === '/new/paint' || path.startsWith('/new/paint/')) return path.replace(/^\/new/, '')
  if (path === '/new/video' || path.startsWith('/new/video/')) return path.replace(/^\/new/, '')
  if (path === '/new/gallery' || path.startsWith('/new/gallery/')) return path.replace(/^\/new/, '')
  return '/'
}

function isLegacyRoute(path: string) {
  return path === '/old' || path === '/legacy' || path === '/v1'
}

function isAdminRoute(path: string) {
  return path === '/admin' || path.startsWith('/admin/')
}

function isPaymentRoute(path: string) {
  if (path === '/payment/result' || path === '/payment/result/') return true
  return (path === '/payment' || path === '/payment/') && new URLSearchParams(window.location.search).has('payment_id')
}

function isCommerceRoute(path: string) {
  const publicDocuments = ['/offer', '/privacy', '/consent', '/terms', '/payment', '/refunds', '/contacts', '/cookies']
  return path === '/tariffs' || path === '/tariffs/' || path === '/legal' || path === '/legal/' || path.startsWith('/legal/') || publicDocuments.includes(path.replace(/\/$/, ''))
}

function isStaticFeedRoute(path: string) {
  return path === '/feed' || path.startsWith('/feed/')
}

function isStaticGalleryRoute(path: string) {
  return path === '/gallery' || path.startsWith('/gallery/')
}

function isPhoneRoute(path: string) {
  return path === '/phone' || path === '/phone/' || path.startsWith('/phone/')
}

function NotFound() {
  return <div className="app-loading">Страница не найдена</div>
}

function App() {
  const path = window.location.pathname
  const legacyNewRoute = path === '/new' || path.startsWith('/new/')
  useEffect(() => {
    if (legacyNewRoute) {
      window.location.replace(`${canonicalNewPath(path)}${window.location.search}${window.location.hash}`)
      return
    }
    applyClientSeo(appShellSeo(path))
  }, [legacyNewRoute, path])

  if (legacyNewRoute) {
    return <div className="app-loading">Открываем генератор...</div>
  }

  if (isStaticFeedRoute(path)) {
    return <div className="app-loading">Загружаем ленту...</div>
  }
  if (isStaticGalleryRoute(path)) {
    return <div className="app-loading">Загружаем галерею...</div>
  }

  const Target = isPhoneRoute(path) ? PhoneApp : isPaymentRoute(path) ? PaymentResultPage : isCommerceRoute(path) ? CommercePage : isNewStudioRoute(path) ? NewStudio : isAdminRoute(path) ? AdminApp : (isLegacyRoute(path) ? LegacyApp : null)

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

