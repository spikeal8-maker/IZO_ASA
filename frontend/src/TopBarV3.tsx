// Единый верхний бар нового интерфейса (визуальный источник:
// izo-aca-new-responsive-page 14). Используется на /new, /feed, /gallery,
// /profile. Навигация между страницами — полной загрузкой (window.location),
// а переключение режимов внутри генератора — через onSelectMode.
//
// Разметка и классы намеренно совпадают с прототипом, чтобы работал scoped CSS
// из newStudioV3.css (обёртка .iv3). Никаких legacy-auth: только колбэки.

export type V3Mode = 'text' | 'i2i' | 'edit' | 'paint' | 'face' | 'video'
export type V3Section = V3Mode | 'feed' | 'gallery' | 'profile' | 'admin'

const MODE_TABS: Array<{ id: V3Mode; label: string; hint: string; gated?: boolean }> = [
  { id: 'text', label: 'По тексту', hint: 'Изображение по тексту' },
  { id: 'i2i', label: 'По фото', hint: 'Изменить изображение по фото' },
  { id: 'edit', label: 'Сборка', hint: 'Собрать изображение из нескольких фото' },
  { id: 'face', label: 'Лицо', hint: 'Замена лица' },
  { id: 'paint', label: 'Редактор', hint: 'Правки изображения' },
  { id: 'video', label: 'Видео', hint: 'Генерация видео', gated: true },
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
  videoEnabled,
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
  videoEnabled?: boolean
}) {
  const selectMode = (mode: V3Mode) => {
    if (onSelectMode) onSelectMode(mode)
    else goto(mode === 'paint' ? '/paint' : '/')
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
        {MODE_TABS.map((t) => {
          const disabled = Boolean(t.gated && !videoEnabled)
          return (
            <button
              key={t.id}
              type="button"
              className={`tab${active === t.id ? ' active' : ''}${disabled ? ' disabled' : ''}`}
              aria-disabled={disabled || undefined}
              aria-label={t.hint}
              title={t.hint}
              onClick={() => {
                if (disabled) return
                selectMode(t.id)
              }}
            >
              {t.label}
            </button>
          )
        })}
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
        <button
          className={`account-button${active === 'profile' ? ' active' : ''}`}
          type="button"
          aria-label="Профиль и настройки"
          title={authed ? (userLabel || 'Профиль и настройки') : 'Войти'}
          onClick={onOpenProfile || (() => goto('/profile'))}
        >
          <span className="settings-glyph" aria-hidden="true">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <path d="M12 8.2a3.8 3.8 0 1 1 0 7.6 3.8 3.8 0 0 1 0-7.6Z" stroke="currentColor" strokeWidth="1.8" />
              <path d="M19.2 13.5c.1-.5.1-1 .1-1.5s0-1-.1-1.5l2-1.5-1.9-3.2-2.4 1a8 8 0 0 0-2.5-1.4L14 2.8h-4l-.4 2.6a8 8 0 0 0-2.5 1.4l-2.4-1L2.8 9l2 1.5c-.1.5-.1 1-.1 1.5s0 1 .1 1.5l-2 1.5 1.9 3.2 2.4-1a8 8 0 0 0 2.5 1.4l.4 2.6h4l.4-2.6a8 8 0 0 0 2.5-1.4l2.4 1 1.9-3.2-2-1.5Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
            </svg>
          </span>
          {userLabel && <span className="user-label">{userLabel}</span>}
          <span className={`user-glyph${authed ? ' authed' : ''}`} aria-hidden="true">
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
      </div>
    </header>
  )
}
