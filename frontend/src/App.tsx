import { lazy, Suspense, useEffect, useState } from 'react'
import { appShellSeo, applyClientSeo } from './seo'
import { getAuthStateV2, initAuthV2, useAuthV2 } from './authV2'
import { bindStudioDraftOwner, captureStudioDraftOwner, prepareStudioHandoffs, type StudioHandoffRequest } from './studio/studioDraft'
import { apiFetch } from './studio/studioApi'

bindStudioDraftOwner(() => {
  const { status, me, identityRevision } = getAuthStateV2()
  const userId = typeof me?.internal_user_id === 'string' ? me.internal_user_id.trim() : ''
  if (status === 'loading' || (status === 'authed' && !userId)) return null
  return { owner: status === 'authed' ? `account:${userId}` : 'anonymous', generation: identityRevision }
})

async function resolveStudioHandoff(request: StudioHandoffRequest, signal: AbortSignal): Promise<unknown> {
  const id = encodeURIComponent(request.id)
  const path = request.source === 'gallery' ? `/gallery/${id}/use-as`
    : request.source === 'uploaded' ? `/gallery/sources/${id}/use-as` : `/feed/publications/${id}/use-as`
  const response = await apiFetch(path, { method: 'POST', cache: 'no-store', signal, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ target: request.target }) })
  if (!response.ok) throw new Error('Handoff unavailable')
  return response.json()
}

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
  useAuthV2()
  const studioRoute = isNewStudioRoute(path)
  const studioOwner = studioRoute ? captureStudioDraftOwner() : null
  const studioOwnerName = studioOwner?.owner
  const studioGeneration = studioOwner?.generation
  const [preparedOwner, setPreparedOwner] = useState<string | null>(null)
  const ownerKey = studioOwner ? `${studioOwner.owner}:${studioOwner.generation}` : null
  useEffect(() => {
    if (studioOwnerName === undefined || studioGeneration === undefined) return undefined
    let cancelled = false
    void prepareStudioHandoffs({ owner: studioOwnerName, generation: studioGeneration }, resolveStudioHandoff).then(() => {
      if (!cancelled) setPreparedOwner(`${studioOwnerName}:${studioGeneration}`)
    })
    return () => { cancelled = true }
  }, [studioOwnerName, studioGeneration])
  useEffect(() => {
    if (studioRoute) void initAuthV2()
  }, [studioRoute])
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

  if (studioRoute && (!studioOwner || preparedOwner !== ownerKey)) {
    return <div className="app-loading">Проверяем аккаунт...</div>
  }

  return (
    <Suspense fallback={<div className="app-loading">Загружаем интерфейс...</div>}>
      <Target key={studioOwner ? `${studioOwner.owner}:${studioOwner.generation}` : undefined} />
    </Suspense>
  )
}

export default App

