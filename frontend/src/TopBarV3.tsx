// Единый верхний бар нового интерфейса (визуальный источник:
// izo-aca-new-responsive-page 14). Используется на /new, /feed, /gallery,
// /profile. Навигация между страницами — полной загрузкой (window.location),
// а переключение режимов внутри генератора — через onSelectMode.
//
// Разметка и классы намеренно совпадают с прототипом, чтобы работал scoped CSS
// из newStudioV3.css (обёртка .iv3). Никаких legacy-auth: только колбэки.

import { Gem, LogIn, SunMedium } from 'lucide-react'

export type V3Mode = 'text' | 'i2i' | 'edit' | 'paint' | 'video'
export type V3Section = V3Mode | 'feed' | 'gallery' | 'profile' | 'admin'

const MODE_TABS: Array<{ id: V3Mode; label: string; hint: string }> = [
  { id: 'text', label: 'По тексту', hint: 'Изображение по тексту' },
  { id: 'i2i', label: 'По фото', hint: 'Изменить изображение по фото' },
  { id: 'edit', label: 'Сборка', hint: 'Собрать изображение из нескольких фото' },
  { id: 'paint', label: 'Редактор', hint: 'Правки изображения' },
  { id: 'video', label: 'Видео', hint: 'Генерация видео' },
]

function goto(path: string) {
  if (window.location.pathname !== path) window.location.href = path
}

export default function TopBarV3({
  active,
  onSelectMode,
  onOpenFeed,
  onOpenGallery,
  onOpenHelp,
  onOpenAdmin,
  onOpenProfile,
  authed,
  isAdmin,
  avatarUrl,
  userLabel,
  initials,
  dailyTokensRemaining,
  dailyTokensLimit,
  tokenBalance,
}: {
  active: V3Section
  onSelectMode?: (mode: V3Mode) => void
  onOpenFeed?: () => void
  onOpenGallery?: () => void
  onOpenHelp?: () => void
  onOpenAdmin?: () => void
  onOpenProfile?: () => void
  authed?: boolean
  isAdmin?: boolean
  avatarUrl?: string | null
  userLabel?: string | null
  initials?: string | null
  dailyTokensRemaining?: number | null
  dailyTokensLimit?: number | null
  tokenBalance?: number | null
}) {
  const dailyRemaining = Math.max(0, Math.floor(Number(dailyTokensRemaining) || 0))
  const dailyLimit = Math.max(0, Math.floor(Number(dailyTokensLimit) || 0))
  const balance = Math.max(0, Math.floor(Number(tokenBalance) || 0))
  const selectMode = (mode: V3Mode) => {
    if (onSelectMode) onSelectMode(mode)
    else goto(mode === 'paint' ? '/paint' : mode === 'video' ? '/video' : '/')
  }
  return (
    <header className="topbar">
      <div className="brand-zone">
        <div className="brand" aria-label="ИЗО АСА">
          <span className="brand-mark" aria-hidden="true"></span>
          <span>ИЗО <span className="brand-accent">АСА</span></span>
        </div>
        <button
          className={`feed-button${active === 'feed' ? ' active' : ''}`}
          type="button"
          onClick={onOpenFeed || (() => goto('/feed'))}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M12 3.5l1.8 4.6 4.7 1.8-4.7 1.8-1.8 4.8-1.8-4.8-4.7-1.8 4.7-1.8L12 3.5Z" fill="currentColor" />
          </svg>
          <span className="feed-label">Лента</span>
        </button>
      </div>

      <nav className="mode-tabs" aria-label="Режимы генератора">
        {MODE_TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            className={`tab${active === t.id ? ' active' : ''}`}
            aria-label={t.hint}
            title={t.hint}
            onClick={() => selectMode(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <div className="top-actions">
        <button
          className={`top-button${active === 'gallery' ? ' active' : ''}`}
          type="button"
          aria-label="Галерея"
          onClick={onOpenGallery || (() => goto('/gallery'))}
        >
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <rect x="4" y="5" width="16" height="14" rx="2" stroke="currentColor" strokeWidth="1.8" />
            <path d="m7 16 4.1-4.1 2.7 2.7 1.5-1.5L18 16" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
            <circle cx="16.4" cy="8.7" r="1.35" fill="currentColor" />
          </svg>
          Галерея
        </button>
        <button
          className={`top-button${active === 'admin' ? ' active' : ''}`}
          type="button"
          aria-label={isAdmin ? 'Админ' : 'Помощь'}
          title={isAdmin ? 'Админ' : 'Помощь'}
          onClick={isAdmin ? (onOpenAdmin || (() => goto('/admin'))) : (onOpenHelp || (() => goto('/')))}
        >
          {isAdmin ? (
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M12 3.5 19 6v5.5c0 4.2-2.8 7.7-7 9-4.2-1.3-7-4.8-7-9V6l7-2.5Z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
              <path d="M9.2 12.1 11.1 14l3.9-4.2" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          ) : (
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <circle cx="12" cy="12" r="8.7" stroke="currentColor" strokeWidth="1.7" />
              <path d="M9.6 9.2a2.55 2.55 0 1 1 4.7 1.45c-.95.9-2.05 1.42-2.05 3.05" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" />
              <path d="M12.25 17.35h.01" stroke="currentColor" strokeWidth="2.8" strokeLinecap="round" />
            </svg>
          )}
          {isAdmin ? 'Админ' : 'Помощь'}
        </button>
        {authed ? (
          <button
            className={`top-token-summary${active === 'profile' ? ' active' : ''}`}
            type="button"
            aria-label={`Дневные токены: ${dailyRemaining} из ${dailyLimit}. Основной баланс: ${balance} токенов`}
            title={userLabel || 'Профиль и баланс токенов'}
            onClick={onOpenProfile || (() => goto('/profile'))}
          >
            <span className="top-token-item daily">
              <SunMedium size={15} aria-hidden="true" />
              <span className="top-token-copy"><b>{dailyRemaining}/{dailyLimit}</b><small>Дневные</small></span>
            </span>
            <span className="top-token-divider" aria-hidden="true" />
            <span className="top-token-item balance">
              <Gem size={14} aria-hidden="true" />
              <span className="top-token-copy"><b>{balance}</b><small>Премиум</small></span>
            </span>
            <span className="top-token-avatar" aria-hidden="true">
              {avatarUrl ? (
                <img src={avatarUrl} alt="" />
              ) : initials ? (
                <span className="user-initials">{initials}</span>
              ) : (
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                  <circle cx="12" cy="8.5" r="3.6" stroke="currentColor" strokeWidth="1.8" />
                  <path d="M5.5 19.5a6.5 6.5 0 0 1 13 0" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                </svg>
              )}
            </span>
          </button>
        ) : (
          <button
            className={`account-button${active === 'profile' ? ' active' : ''}`}
            type="button"
            aria-label="Войти"
            title="Войти"
            onClick={onOpenProfile || (() => goto('/profile'))}
          >
            <span className="settings-glyph" aria-hidden="true"><LogIn size={17} /></span>
            <span className="user-label">Войти</span>
            <span className="user-glyph" aria-hidden="true">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                <circle cx="12" cy="8.5" r="3.6" stroke="currentColor" strokeWidth="1.8" />
                <path d="M5.5 19.5a6.5 6.5 0 0 1 13 0" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
              </svg>
            </span>
          </button>
        )}
      </div>
    </header>
  )
}
