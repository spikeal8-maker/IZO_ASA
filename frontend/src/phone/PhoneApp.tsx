import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AudioLines,
  Box,
  Image as ImageIcon,
  Menu,
  MessageCircle,
  RefreshCw,
  Sparkles,
  Video,
  WifiOff,
  X,
} from 'lucide-react'

import { loadPhonePlatform, PhoneApiError } from './api.ts'
import {
  isPhonePlatformManifest,
  type PhonePlatformManifest,
  type PhoneWorkspace,
  type PhoneWorkspaceId,
} from './contracts.ts'
import { phoneWorkspaceFromPath } from './routes.ts'
import { loadPhoneJobs, type PhoneJob } from './core/jobs.ts'
import PhoneChatWorkspace from './features/chat/PhoneChatWorkspace.tsx'
import PhoneAudioWorkspace from './features/audio/PhoneAudioWorkspace.tsx'
import PhoneImageWorkspace from './features/image/PhoneImageWorkspace.tsx'
import PhoneVideoWorkspace from './features/video/PhoneVideoWorkspace.tsx'
import './phoneShell.css'


const MANIFEST_CACHE_KEY = 'izo.phone.platform.v1'
const LAST_ROUTE_KEY = 'izo.phone.last-route.v1'

type MePayload = {
  profile?: { display_name?: string | null; avatar_url?: string | null }
  account?: {
    token_balance?: number | null
    daily_tokens?: number | null
    daily_tokens_limit?: number | null
    daily_tokens_used?: number | null
    daily_tokens_remaining?: number | null
  }
}

const workspaceIcons: Record<PhoneWorkspaceId, typeof ImageIcon> = {
  image: ImageIcon,
  video: Video,
  chat: MessageCircle,
  audio: AudioLines,
  '3d': Box,
}

function cachedManifest(): PhonePlatformManifest | null {
  try {
    const value: unknown = JSON.parse(sessionStorage.getItem(MANIFEST_CACHE_KEY) || 'null')
    return isPhonePlatformManifest(value) ? value : null
  } catch {
    return null
  }
}

function lastPhoneRoute(): string | null {
  const route = localStorage.getItem(LAST_ROUTE_KEY) || ''
  return phoneWorkspaceFromPath(route) ? route : null
}

function navigate(path: string, replace = false) {
  if (replace) window.history.replaceState({}, '', path)
  else window.history.pushState({}, '', path)
  window.dispatchEvent(new PopStateEvent('popstate'))
}

function PhoneBrand() {
  return (
    <a className="phone-brand" href="/phone/image" aria-label="ИЗО АСА">
      <span aria-hidden="true"><Sparkles /></span>
      <b>ИЗО <em>АСА</em></b>
    </a>
  )
}

function PhoneMenuSheet({
  workspaces,
  onClose,
  onSelect,
}: {
  workspaces: PhoneWorkspace[]
  onClose: () => void
  onSelect: (workspace: PhoneWorkspace) => void
}) {
  const [drag, setDrag] = useState(0)
  const dragStart = useRef<{ pointerId: number; y: number } | null>(null)

  const resetDrag = () => { dragStart.current = null; setDrag(0) }

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [onClose])

  return (
    <div className="phone-sheet-backdrop" role="presentation" onPointerDown={(event) => {
      if (event.target === event.currentTarget) onClose()
    }}>
      <section
        className="phone-menu-sheet"
        role="dialog"
        aria-modal="true"
        aria-label="Разделы ИЗО АСА"
        style={{ transform: `translateY(${drag}px)` }}
      >
        <div className="phone-menu-drag-surface"
        onPointerDown={(event) => {
          if (!event.isPrimary || event.button !== 0 || dragStart.current !== null
            || !(event.target instanceof Element)
            || event.target.closest('button, a, input, select, textarea, [role="button"]')) return
          dragStart.current = { pointerId: event.pointerId, y: event.clientY }
          event.currentTarget.setPointerCapture(event.pointerId)
        }}
        onPointerMove={(event) => {
          if (dragStart.current?.pointerId === event.pointerId) setDrag(Math.max(0, event.clientY - dragStart.current.y))
        }}
        onPointerUp={(event) => {
          if (dragStart.current?.pointerId !== event.pointerId) return
          const distance = event.clientY - dragStart.current.y
          resetDrag()
          if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
          if (distance > 72) onClose()
        }}
        onPointerCancel={resetDrag}
        onLostPointerCapture={resetDrag}
      >
        <div className="phone-sheet-handle" aria-hidden="true" />
        <header><div><small>Все возможности</small><h2>Меню</h2></div><button type="button" onClick={onClose} aria-label="Закрыть меню"><X /></button></header>
        </div>
        <div className="phone-menu-grid">
          {workspaces.map((workspace) => {
            const Icon = workspaceIcons[workspace.id]
            return (
              <button
                type="button"
                key={workspace.id}
                disabled={!workspace.enabled}
                onClick={() => onSelect(workspace)}
              >
                <span><Icon /></span>
                <b>{workspace.label}</b>
                <small>{workspace.enabled ? 'Открыть' : workspace.stage === 'partial' ? 'Готовим' : 'Скоро'}</small>
              </button>
            )
          })}
        </div>
      </section>
    </div>
  )
}

function PhoneWorkspacePanel({ workspace, offline }: { workspace: PhoneWorkspace; offline: boolean }) {
  const Icon = workspaceIcons[workspace.id]
  return (
    <section className="phone-workspace-panel" data-phone-workspace={workspace.id}>
      <div className="phone-workspace-preview">
        <div className="phone-workspace-preview-glow" />
        <span><Icon /></span>
        <h1>{workspace.label}</h1>
        <p>{workspace.enabled ? 'Рабочая область подключается к общим данным проекта.' : 'Раздел появится после проверки качества и экономики.'}</p>
      </div>
      <div className="phone-workspace-card">
        <small>{offline ? 'Без подключения доступны только сохранённые данные' : 'Мобильная платформа ИЗО АСА'}</small>
        <b>{workspace.enabled ? 'Интерфейс готов к подключению функций' : 'Функция пока выключена'}</b>
        <p>{workspace.operations.length ? workspace.operations.join(' · ') : 'Возможности появятся после provider-проверки'}</p>
      </div>
    </section>
  )
}

export default function PhoneApp() {
  const [manifest, setManifest] = useState<PhonePlatformManifest | null>(() => cachedManifest())
  const [me, setMe] = useState<MePayload | null>(null)
  const [path, setPath] = useState(window.location.pathname)
  const [loading, setLoading] = useState(!manifest)
  const [error, setError] = useState<PhoneApiError | null>(null)
  const [offline, setOffline] = useState(!navigator.onLine)
  const [menuOpen, setMenuOpen] = useState(false)
  const [activeJobs, setActiveJobs] = useState<PhoneJob[]>([])

  const refresh = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    setError(null)
    try {
      const platform = await loadPhonePlatform(signal)
      setManifest(platform)
      sessionStorage.setItem(MANIFEST_CACHE_KEY, JSON.stringify(platform))
      setOffline(false)
      fetch('/api/me-v2', { credentials: 'include', headers: { Accept: 'application/json' } })
        .then(async (response) => response.ok ? response.json() as Promise<MePayload> : null)
        .then((payload) => { if (payload) setMe(payload) })
        .catch(() => undefined)
      loadPhoneJobs(true, signal).then(setActiveJobs).catch(() => undefined)
    } catch (caught) {
      const failure = caught instanceof PhoneApiError ? caught : new PhoneApiError(0, 'Нет соединения с сервером.')
      setError(failure)
      setOffline(true)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    const timer = window.setTimeout(() => { void refresh(controller.signal) }, 0)
    return () => { window.clearTimeout(timer); controller.abort() }
  }, [refresh])
  useEffect(() => {
    const syncPath = () => setPath(window.location.pathname)
    const online = () => { setOffline(false); void refresh() }
    const offlineNow = () => setOffline(true)
    window.addEventListener('popstate', syncPath)
    window.addEventListener('online', online)
    window.addEventListener('offline', offlineNow)
    return () => {
      window.removeEventListener('popstate', syncPath)
      window.removeEventListener('online', online)
      window.removeEventListener('offline', offlineNow)
    }
  }, [refresh])

  useEffect(() => {
    if (!manifest) return
    if (path === '/phone' || path === '/phone/') {
      navigate(lastPhoneRoute() || manifest.defaultRoute, true)
    }
  }, [manifest, path])

  const currentId = phoneWorkspaceFromPath(path)
  const current = useMemo(
    () => manifest?.workspaces.find((workspace) => workspace.id === currentId) || null,
    [currentId, manifest],
  )
  const primary = manifest?.workspaces.filter((workspace) => workspace.navigation === 'primary') || []
  const dailyLimit = Number(me?.account?.daily_tokens_limit ?? me?.account?.daily_tokens ?? 0)
  const daily = Math.max(0, Number(me?.account?.daily_tokens_remaining ?? dailyLimit - Number(me?.account?.daily_tokens_used ?? 0)))
  const mainTokens = Math.max(0, Number(me?.account?.token_balance ?? 0))

  const selectWorkspace = (workspace: PhoneWorkspace) => {
    if (!workspace.enabled) return
    localStorage.setItem(LAST_ROUTE_KEY, workspace.route)
    setMenuOpen(false)
    navigate(workspace.route)
  }

  if (loading && !manifest) {
    return <main className="phone-app phone-state"><PhoneBrand /><div className="phone-state-spinner" /><b>Открываем ИЗО АСА</b></main>
  }
  if (!manifest) {
    const unauthorized = error?.status === 401
    return (
      <main className="phone-app phone-state">
        <PhoneBrand />
        {offline ? <WifiOff /> : <X />}
        <h1>{unauthorized ? 'Нужно войти' : 'Сервис временно недоступен'}</h1>
        <p>{unauthorized ? 'Авторизуйтесь в основном приложении и вернитесь в мобильный раздел.' : 'Попробуйте ещё раз. Ваши материалы и задания не удалены.'}</p>
        <button type="button" onClick={() => unauthorized ? window.location.assign('/') : void refresh()}>{unauthorized ? 'Перейти ко входу' : <><RefreshCw /> Повторить</>}</button>
      </main>
    )
  }

  return (
    <main className="phone-app">
      <header className="phone-topbar">
        <PhoneBrand />
        <nav aria-label="Основные разделы"><a href="/feed">Лента</a><a href="/gallery">Галерея</a></nav>
        <button className="phone-balance" type="button" onClick={() => window.location.assign('/profile')} aria-label="Открыть профиль и баланс">
          <span className="daily">☀ {daily}</span><span className="main">♦ {mainTokens}</span>
          {me?.profile?.avatar_url ? <img src={me.profile.avatar_url} alt="" /> : <span className="avatar">{(me?.profile?.display_name || 'И').slice(0, 1)}</span>}
        </button>
      </header>

      {offline && <div className="phone-offline" role="status"><WifiOff /> Нет сети — показываем сохранённое</div>}
      {error && manifest && !offline && <div className="phone-warning" role="status">Не удалось обновить настройки <button type="button" onClick={() => void refresh()}>Повторить</button></div>}

      <div className="phone-content">
        {current?.id === 'image' ? <PhoneImageWorkspace offline={offline} /> : current?.id === 'video' ? <PhoneVideoWorkspace offline={offline} /> : current?.id === 'chat' ? <PhoneChatWorkspace offline={offline} /> : current?.id === 'audio' ? <PhoneAudioWorkspace offline={offline} /> : current ? <PhoneWorkspacePanel workspace={current} offline={offline} /> : (
          <section className="phone-not-found"><h1>Такого раздела нет</h1><button type="button" onClick={() => navigate(manifest.defaultRoute, true)}>Открыть картинки</button></section>
        )}
      </div>

      <nav className="phone-bottom-nav" aria-label="Рабочие разделы">
        {primary.slice(0, 2).map((workspace) => {
          const Icon = workspaceIcons[workspace.id]
          return <button type="button" key={workspace.id} disabled={!workspace.enabled} aria-current={currentId === workspace.id ? 'page' : undefined} onClick={() => selectWorkspace(workspace)}><Icon /><span>{workspace.shortLabel}</span></button>
        })}
        <button className="phone-menu-button" type="button" aria-label="Меню" aria-expanded={menuOpen} onClick={() => setMenuOpen(true)}><Menu />{activeJobs.length > 0 && <b aria-hidden="true">{activeJobs.length}</b>}<span>Меню</span></button>
        {primary.slice(2).map((workspace) => {
          const Icon = workspaceIcons[workspace.id]
          return <button type="button" key={workspace.id} disabled={!workspace.enabled} aria-current={currentId === workspace.id ? 'page' : undefined} onClick={() => selectWorkspace(workspace)}><Icon /><span>{workspace.shortLabel}</span></button>
        })}
      </nav>

      {menuOpen && <PhoneMenuSheet workspaces={manifest.workspaces} onClose={() => setMenuOpen(false)} onSelect={selectWorkspace} />}
      <div className="phone-notification-host" aria-live="polite" aria-atomic="true" />
    </main>
  )
}
