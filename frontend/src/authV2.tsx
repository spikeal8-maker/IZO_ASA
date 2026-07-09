// Identity/Auth v2 frontend layer (Phase 13: HttpOnly cookie sessions).
/* eslint-disable react-refresh/only-export-components -- This module intentionally exports cookie-auth helpers and the auth UI; splitting it is a separate refactor. */
//
// Trust model:
// - The trusted session lives in HttpOnly cookies set by the backend on login.
//   The frontend NEVER reads, stores, or logs the session/refresh tokens. They
//   are not accessible to JS and are never written to localStorage/sessionStorage.
// - v2 requests use `credentials: 'include'` so the browser attaches the cookies.
//   They never send X-OneNode-User and never rely on localStorage('onenode_user').
// - Any tokens still present in a login JSON response are IGNORED.
// - installation_id / anonymous_id are device identifiers (NOT auth) and may be
//   persisted in localStorage.
//
// Reload persistence: because the session is a cookie, a page reload keeps the
// user logged in — startup re-validates via GET /api/me-v2 (and an Option-A
// cookie refresh on 401).
import { useCallback, useEffect, useState, useSyncExternalStore } from 'react'
import type { ReactElement } from 'react'
import { createPortal } from 'react-dom'
import { Lock, X } from 'lucide-react'

const API = (import.meta as ImportMeta & { env?: { VITE_API_BASE_URL?: string } }).env?.VITE_API_BASE_URL || '/api'
const INSTALL_KEY = 'onenode_installation_id'
const ANON_KEY = 'onenode_anonymous_id'

export function getInstallationId(): string | null {
  return window.localStorage.getItem(INSTALL_KEY)
}
export function getAnonymousId(): string | null {
  return window.localStorage.getItem(ANON_KEY)
}

type WindowGlobals = Window & {
  Telegram?: { WebApp?: { initData?: string } }
  MAX?: { WebApp?: { webAppData?: string; initData?: string } }
  maxWebApp?: { webAppData?: string; initData?: string }
}

function detectPlatform(): string {
  const w = window as WindowGlobals
  if (w.Telegram?.WebApp?.initData) return 'telegram_mini_app'
  if (w.MAX?.WebApp || w.maxWebApp) return 'max_mini_app'
  return /Mobi|Android|iPhone|iPad/i.test(navigator.userAgent) ? 'web_mobile' : 'web_desktop'
}

export function telegramAvailable(): boolean {
  return !!(window as WindowGlobals).Telegram?.WebApp?.initData
}
export function maxAvailable(): boolean {
  const w = window as WindowGlobals
  return !!(w.MAX?.WebApp?.webAppData || w.MAX?.WebApp?.initData || w.maxWebApp?.webAppData)
}

// Diagnostics return ONLY booleans — never a user id, initData, or WebAppData.
export function telegramDiagnostics(): { hasTelegram: boolean; hasWebApp: boolean; hasInitData: boolean } {
  const tg = (window as WindowGlobals).Telegram
  return { hasTelegram: !!tg, hasWebApp: !!tg?.WebApp, hasInitData: !!tg?.WebApp?.initData }
}

export function maxDiagnostics(): { hasMax: boolean; hasWebApp: boolean; hasWebAppData: boolean; hasInitData: boolean } {
  const w = window as WindowGlobals
  const webApp = w.MAX?.WebApp || w.maxWebApp
  return {
    hasMax: !!w.MAX,
    hasWebApp: !!webApp,
    hasWebAppData: !!(w.MAX?.WebApp?.webAppData || w.maxWebApp?.webAppData),
    hasInitData: !!w.MAX?.WebApp?.initData,
  }
}

// Expose boolean-only diagnostics on window so they can be read from the
// Telegram/MAX in-app console (e.g. `__authDiagV2.max()`). No ids/tokens/raw data.
;(window as unknown as { __authDiagV2?: unknown }).__authDiagV2 = {
  telegram: telegramDiagnostics,
  max: maxDiagnostics,
}

// Best-effort: signal readiness/expand to the Telegram WebView. Never logs initData.
function notifyTelegramReady(): void {
  const tg = (window as Window & { Telegram?: { WebApp?: { ready?: () => void; expand?: () => void } } }).Telegram?.WebApp
  try {
    tg?.ready?.()
    tg?.expand?.()
  } catch {
    /* ignore — non-critical */
  }
}

// v2 API client: cookie auth via credentials:'include'. NEVER sends
// X-OneNode-User and never reads the legacy onenode_user cookie/localStorage.
async function authFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers)
  if (init.body) headers.set('Content-Type', 'application/json')
  return fetch(`${API}${path}`, { ...init, headers, credentials: 'include' })
}

let bootstrapPromise: Promise<void> | null = null

async function doBootstrap(): Promise<void> {
  try {
    const res = await authFetch('/auth/bootstrap-v2', {
      method: 'POST',
      body: JSON.stringify({
        platform: detectPlatform(),
        installation_id: getInstallationId(),
        anonymous_id: getAnonymousId(),
        client: {
          language: navigator.language || null,
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || null,
          app_version: null,
        },
      }),
    })
    if (!res.ok) return
    const data = (await res.json()) as { installation_id?: string; anonymous_id?: string }
    // Device identifiers (NOT auth) — safe to persist.
    if (data.installation_id) window.localStorage.setItem(INSTALL_KEY, data.installation_id)
    if (data.anonymous_id) window.localStorage.setItem(ANON_KEY, data.anonymous_id)
  } catch {
    /* bootstrap is best-effort; never blocks the app */
  }
}

// Single-flight: app startup and the auth panel can both call this safely.
export function bootstrapV2(): Promise<void> {
  if (!bootstrapPromise) bootstrapPromise = doBootstrap()
  return bootstrapPromise
}

// Login sets HttpOnly cookies server-side. Any tokens in the JSON body are ignored.
export async function loginTelegramV2(): Promise<boolean> {
  const w = window as WindowGlobals
  const initData = w.Telegram?.WebApp?.initData // RAW initData only; never initDataUnsafe.user.id
  if (!initData) return false
  const res = await authFetch('/auth/telegram-v2', {
    method: 'POST',
    body: JSON.stringify({
      init_data: initData,
      installation_id: getInstallationId(),
      anonymous_id: getAnonymousId(),
      platform: 'telegram_mini_app',
    }),
  })
  return res.ok // cookies are set by the backend; JSON tokens (if any) are ignored
}

export async function loginMaxV2(): Promise<boolean> {
  const w = window as WindowGlobals
  const webAppData = w.MAX?.WebApp?.webAppData || w.MAX?.WebApp?.initData || w.maxWebApp?.webAppData
  if (!webAppData) return false // never send a raw MAX userId as identity
  const res = await authFetch('/auth/max-v2', {
    method: 'POST',
    body: JSON.stringify({
      web_app_data: webAppData,
      installation_id: getInstallationId(),
      anonymous_id: getAnonymousId(),
      platform: 'max_mini_app',
    }),
  })
  return res.ok
}

export interface AuthCapabilitiesV2 {
  password_login_available: boolean
  password_register_available: boolean
  email_otp_available: boolean
  telegram_bot_login_available: boolean
  max_bot_login_available: boolean
  capabilities_loaded?: boolean
  capabilities_status?: number
}

export async function getAuthCapabilitiesV2(): Promise<AuthCapabilitiesV2> {
  try {
    const res = await authFetch('/auth/capabilities-v2')
    if (!res.ok) throw Object.assign(new Error('capabilities_failed'), { status: res.status })
    const data = (await res.json()) as Partial<AuthCapabilitiesV2> & { bot_login?: Partial<AuthCapabilitiesV2> }
    return {
      password_login_available: data.password_login_available !== false,
      password_register_available: data.password_register_available !== false,
      email_otp_available: !!data.email_otp_available,
      telegram_bot_login_available: !!data.bot_login?.telegram_bot_login_available,
      max_bot_login_available: !!data.bot_login?.max_bot_login_available,
      capabilities_loaded: true,
      capabilities_status: res.status,
    }
  } catch (error) {
    return {
      password_login_available: true,
      password_register_available: true,
      email_otp_available: false,
      telegram_bot_login_available: false,
      max_bot_login_available: false,
      capabilities_loaded: false,
      capabilities_status: typeof (error as { status?: unknown })?.status === 'number' ? (error as { status: number }).status : undefined,
    }
  }
}

export async function startBotLoginV2(provider: 'telegram' | 'max'): Promise<{ ok: true; deep_link: string; poll_interval_ms: number } | { ok: false; reason: string }> {
  try {
    const res = await authFetch('/auth/bot-login/start', {
      method: 'POST',
      body: JSON.stringify({ provider }),
    })
    if (!res.ok) {
      let reason = res.status === 503 ? 'provider_not_configured' : 'bot_login_disabled'
      try {
        const data = (await res.json()) as { detail?: string }
        if (data.detail) reason = data.detail
      } catch {
        /* keep safe reason */
      }
      return { ok: false, reason }
    }
    const data = (await res.json()) as { deep_link: string; poll_interval_ms: number }
    return { ok: true, deep_link: data.deep_link, poll_interval_ms: data.poll_interval_ms }
  } catch {
    return { ok: false, reason: 'network_error' }
  }
}

export async function pollBotLoginStatusV2(): Promise<{ status: 'pending' | 'approved' | 'expired' | 'authenticated' | 'conflict' | 'error' }> {
  const res = await authFetch('/auth/bot-login/status')
  if (!res.ok) {
    // After a successful bot login the backend consumes and clears the temporary
    // challenge cookie. A late poll can then receive 401 even though the real
    // trusted session cookie is already set, so confirm /me-v2 before showing an
    // error to the user.
    const me = await fetchMeV2()
    return me ? { status: 'authenticated' } : { status: 'error' }
  }
  return (await res.json()) as { status: 'pending' | 'approved' | 'expired' | 'authenticated' | 'conflict' }
}

export async function requestEmailCodeV2(email: string): Promise<{ challenge_id: string; debug_code?: string } | null> {
  const res = await authFetch('/auth/email/request-code-v2', {
    method: 'POST',
    body: JSON.stringify({
      email,
      platform: detectPlatform(),
      installation_id: getInstallationId(),
      anonymous_id: getAnonymousId(),
    }),
  })
  if (!res.ok) return null
  return (await res.json()) as { challenge_id: string; debug_code?: string }
}

export interface PasswordResult { ok: boolean; status: number; requiresEmailVerification?: boolean; email?: string }

// Browser email+password. Cookies are set by the backend; no tokens kept in JS.
export async function passwordLoginV2(email: string, password: string): Promise<PasswordResult> {
  const res = await authFetch('/auth/password/login-v2', {
    method: 'POST',
    body: JSON.stringify({ email, password, platform: detectPlatform() }),
  })
  let requiresEmailVerification = false
  let normalizedEmail: string | undefined
  if (!res.ok) {
    try {
      const data = (await res.json()) as { requires_email_verification?: boolean; email?: string }
      requiresEmailVerification = !!data.requires_email_verification
      normalizedEmail = data.email
    } catch {
      /* no structured error body */
    }
  }
  return { ok: res.ok, status: res.status, requiresEmailVerification, email: normalizedEmail }
}

export async function passwordRegisterV2(
  email: string,
  password: string,
  passwordRepeat: string,
): Promise<PasswordResult> {
  const res = await authFetch('/auth/password/register-v2', {
    method: 'POST',
    body: JSON.stringify({
      email,
      password,
      password_repeat: passwordRepeat,
      accepted_terms: true,
      accepted_privacy: true,
      accepted_personal_data: true,
      platform: detectPlatform(),
    }),
  })
  let requiresEmailVerification = false
  if (res.ok) {
    try {
      const data = (await res.json()) as { requires_email_verification?: boolean }
      requiresEmailVerification = !!data.requires_email_verification
    } catch {
      /* body optional — treat as no verification required */
    }
  }
  return { ok: res.ok, status: res.status, requiresEmailVerification }
}

export async function verifyEmailCodeV2(challengeId: string, code: string): Promise<boolean> {
  const res = await authFetch('/auth/email/verify-code-v2', {
    method: 'POST',
    body: JSON.stringify({
      challenge_id: challengeId,
      code,
      platform: detectPlatform(),
      installation_id: getInstallationId(),
      anonymous_id: getAnonymousId(),
    }),
  })
  return res.ok // cookies set by backend; JSON tokens ignored
}

export async function startBotLinkV2(provider: 'telegram' | 'max'): Promise<{ ok: true; deep_link: string; poll_interval_ms: number } | { ok: false; reason: string }> {
  try {
    const res = await authFetch('/auth/link/bot/start', {
      method: 'POST',
      body: JSON.stringify({ provider }),
    })
    if (!res.ok) {
      let reason = res.status === 503 ? 'provider_not_configured' : 'bot_link_failed'
      try {
        const data = (await res.json()) as { detail?: string }
        if (data.detail) reason = data.detail
      } catch {
        /* keep safe reason */
      }
      return { ok: false, reason }
    }
    const data = (await res.json()) as { deep_link: string; poll_interval_ms: number }
    return { ok: true, deep_link: data.deep_link, poll_interval_ms: data.poll_interval_ms }
  } catch {
    return { ok: false, reason: 'network_error' }
  }
}

export async function requestEmailLinkCodeV2(email: string): Promise<{ challenge_id: string; debug_code?: string } | { error: string } | null> {
  const res = await authFetch('/auth/link/email/request-code-v2', {
    method: 'POST',
    body: JSON.stringify({ email }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({})) as { detail?: string }
    return { error: data.detail || 'email_link_failed' }
  }
  return (await res.json()) as { challenge_id: string; debug_code?: string }
}

export async function verifyEmailLinkCodeV2(challengeId: string, code: string): Promise<{ ok: true; reward_tokens?: number } | { ok: false; error: string }> {
  const res = await authFetch('/auth/link/email/verify-code-v2', {
    method: 'POST',
    body: JSON.stringify({ challenge_id: challengeId, code }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({})) as { detail?: string }
    return { ok: false, error: data.detail || 'email_link_failed' }
  }
  const data = await res.json().catch(() => ({})) as { reward_tokens?: number }
  return { ok: true, reward_tokens: data.reward_tokens }
}

export interface MeV2 {
  internal_user_id?: string
  legacy_user_id?: string
  profile?: {
    display_name?: string | null; first_name?: string | null; last_name?: string | null
    public_user_code?: string | null; username?: string | null; email?: string | null; email_verified_at?: string | null; providers?: string[]
    public_about?: string | null; public_website?: string | null; public_focus?: string | null; public_phone?: string | null
    public_links?: Array<{ label?: string | null; url?: string | null }> | null
    language_code?: string | null; timezone?: string | null; city?: string | null; country_code?: string | null
    avatar_url?: string | null; avatar_preset?: string | null; gender?: 'female' | 'male' | null; age?: number | null
  } | null
  account?: {
    role?: string | null; plan?: string | null; token_balance?: number | null
    gallery_enabled?: boolean | null; gallery_access?: boolean | null
    daily_tokens?: number | null; daily_tokens_used?: number | null
    daily_tokens_limit?: number | null; daily_tokens_remaining?: number | null
    gallery_slots?: number | null; gallery_used?: number | null
    gallery_free?: number | null; gallery_full?: boolean | null
    video_enabled?: boolean | null; video_slots?: number | null
    video_used?: number | null; video_free?: number | null
  } | null
  identities?: Array<{ provider?: string; provider_user_id?: string | null; provider_username?: string | null; provider_email?: string | null; provider_first_name?: string | null; provider_last_name?: string | null; provider_avatar_url?: string | null; verified_at?: string | null }>
}

export interface SessionInfoV2 {
  id: string
  provider?: string | null
  platform?: string | null
  ip_address?: string | null
  device?: string | null
  created_at?: string | null
  last_seen_at?: string | null
  expires_at?: string | null
  revoked_at?: string | null
  active?: boolean
  current?: boolean
}

export async function listSessionsV2(): Promise<{ sessions: SessionInfoV2[]; current_session_id?: string } | null> {
  const res = await authFetch('/auth/sessions')
  if (!res.ok) return null
  return (await res.json()) as { sessions: SessionInfoV2[]; current_session_id?: string }
}

export async function revokeSessionV2(sessionId: string): Promise<boolean> {
  const res = await authFetch(`/auth/sessions/${encodeURIComponent(sessionId)}/revoke`, { method: 'POST' })
  return res.ok
}

export async function revokeOtherSessionsV2(): Promise<number> {
  const res = await authFetch('/auth/sessions/revoke-others', { method: 'POST' })
  if (!res.ok) return 0
  const data = await res.json().catch(() => ({})) as { revoked_count?: number }
  return data.revoked_count || 0
}

export interface ActivityV2 {
  account_created_at?: string | null
  last_seen_at?: string | null
  active_sessions?: number
  total_sessions?: number
  total_logins?: number
  logins_by_provider?: Record<string, { count: number; last_at?: string | null }>
  login_methods?: Array<{ provider?: string; last_login_at?: string | null; linked_at?: string | null; verified?: boolean }>
}

export async function getActivityV2(): Promise<ActivityV2 | null> {
  const res = await authFetch('/account/activity-v2')
  if (!res.ok) return null
  return (await res.json()) as ActivityV2
}

let refreshSessionPromise: Promise<boolean> | null = null

export function ensureSessionRefreshedV2(): Promise<boolean> {
  if (!refreshSessionPromise) {
    refreshSessionPromise = authFetch('/auth/session/refresh-v2', { method: 'POST', body: JSON.stringify({}) })
      .then((res) => res.ok)
      .catch(() => false)
      .finally(() => {
        refreshSessionPromise = null
      })
  }
  return refreshSessionPromise
}

// Restore/validate the session purely via cookies. On a 401 (expired access
// session), Option A: try one shared cookie-based refresh, then retry /me-v2 once.
export async function fetchMeV2(): Promise<MeV2 | null> {
  let res = await authFetch('/me-v2')
  if (res.status === 401) {
    const refreshed = await ensureSessionRefreshedV2()
    if (refreshed) res = await authFetch('/me-v2')
  }
  if (!res.ok) return null
  return (await res.json()) as MeV2
}

export async function logoutV2(): Promise<void> {
  try {
    // Empty body: backend reads the session cookie and clears both cookies.
    await authFetch('/auth/session/logout-v2', { method: 'POST', body: JSON.stringify({}) })
  } catch {
    /* ignore network errors on logout */
  }
  // installation_id / anonymous_id are intentionally retained.
}

export async function updateProfileV2(fields: Record<string, unknown>): Promise<MeV2 | null> {
  let res = await authFetch('/me/profile-v2', {
    method: 'PATCH',
    body: JSON.stringify(fields),
  })
  if (res.status === 401) {
    const refreshed = await ensureSessionRefreshedV2()
    if (refreshed) {
      res = await authFetch('/me/profile-v2', {
        method: 'PATCH',
        body: JSON.stringify(fields),
      })
    }
  }
  if (!res.ok) return null
  return (await res.json()) as MeV2
}

export async function updateProfileV2Detailed(fields: Record<string, unknown>): Promise<{ ok: true; data: MeV2 } | { ok: false; detail: string; status: number }> {
  let res = await authFetch('/me/profile-v2', {
    method: 'PATCH',
    body: JSON.stringify(fields),
  })
  if (res.status === 401) {
    const refreshed = await ensureSessionRefreshedV2()
    if (refreshed) {
      res = await authFetch('/me/profile-v2', {
        method: 'PATCH',
        body: JSON.stringify(fields),
      })
    }
  }
  if (!res.ok) {
    const payload = await res.json().catch(() => ({})) as { detail?: unknown }
    const detail = typeof payload.detail === 'string' ? payload.detail : 'Не удалось сохранить профиль'
    return { ok: false, detail, status: res.status }
  }
  return { ok: true, data: (await res.json()) as MeV2 }
}

// ---------------------------------------------------------------------------
// Shared auth-v2 status store (so App.tsx can lock generation reactively).
// Holds NO tokens — only a coarse status derived from /api/me-v2 over cookies.
// ---------------------------------------------------------------------------
export type AuthStatusV2 = 'loading' | 'anon' | 'authed'
let authStatus: AuthStatusV2 = 'loading'
let authMe: MeV2 | null = null
const authListeners = new Set<() => void>()
function emitAuth(): void {
  authListeners.forEach((l) => l())
}
function setAuthState(status: AuthStatusV2, me: MeV2 | null): void {
  authStatus = status
  authMe = me
  emitAuth()
}
function subscribeAuth(cb: () => void): () => void {
  authListeners.add(cb)
  return () => {
    authListeners.delete(cb)
  }
}
function getAuthStatus(): AuthStatusV2 {
  return authStatus
}

export function useAuthV2(): { status: AuthStatusV2; me: MeV2 | null } {
  const status = useSyncExternalStore(subscribeAuth, getAuthStatus, getAuthStatus)
  return { status, me: authMe }
}

let initAuthPromise: Promise<void> | null = null
// Single-flight startup: bootstrap, then restore the session from the cookie.
// installation_id/anonymous_id are NOT auth; only a 200 from /api/me-v2 authenticates.
export function initAuthV2(): Promise<void> {
  if (!initAuthPromise) {
    initAuthPromise = (async () => {
      await bootstrapV2()
      let me = await fetchMeV2()
      if (!me) {
        const ok = (await loginTelegramV2()) || (await loginMaxV2())
        me = ok ? await fetchMeV2() : null
      }
      setAuthState(me ? 'authed' : 'anon', me)
    })().catch(() => setAuthState('anon', null))
  }
  return initAuthPromise
}

export async function refreshAuthStateV2(): Promise<MeV2 | null> {
  const me = await fetchMeV2()
  setAuthState(me ? 'authed' : 'anon', me)
  return me
}

// Modal login surface opened by the locked generation CTA. Cookie-only auth; no
// tokens stored in JS. role="dialog", closes on X / overlay / Esc.
export function AuthV2Modal({ open, onClose }: { open: boolean; onClose: () => void }): ReactElement | null {
  const [tab, setTab] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [passwordRepeat, setPasswordRepeat] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  // Post-registration email verification (OTP) and browser-to-bot login challenge.
  const [phase, setPhase] = useState<'form' | 'verify' | 'bot'>('form')
  const [challengeId, setChallengeId] = useState('')
  const [code, setCode] = useState('')
  const [debugCode, setDebugCode] = useState<string | undefined>(undefined)
  const [resendIn, setResendIn] = useState(0)
  const [botProvider, setBotProvider] = useState<'telegram' | 'max' | ''>('')
  const [botDeepLink, setBotDeepLink] = useState('')
  const [botPollMs, setBotPollMs] = useState(2000)
  const [authCaps, setAuthCaps] = useState<AuthCapabilitiesV2>({
    password_login_available: true,
    password_register_available: true,
    email_otp_available: false,
    telegram_bot_login_available: false,
    max_bot_login_available: false,
    capabilities_loaded: undefined,
  })
  const handleClose = useCallback(() => {
    setPhase('form'); setCode(''); setChallengeId(''); setDebugCode(undefined); setResendIn(0); setError('')
    setBotProvider(''); setBotDeepLink(''); setBotPollMs(2000)
    onClose()
  }, [onClose])

  useEffect(() => {
    if (!open) return
    notifyTelegramReady() // ready()/expand() inside a Telegram WebView; no-op elsewhere
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    // Lock background scroll while the modal is open.
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = prevOverflow
    }
  }, [open, onClose])

  useEffect(() => {
    if (!open) return
    let cancelled = false
    void getAuthCapabilitiesV2().then((caps) => {
      if (!cancelled) setAuthCaps(caps)
    })
    return () => {
      cancelled = true
    }
  }, [open])

  useEffect(() => {
    if (tab === 'register' && authCaps.password_register_available === false) {
      queueMicrotask(() => setTab('login'))
    }
  }, [tab, authCaps.password_register_available])

  // Resend cooldown countdown (matches backend EMAIL_OTP_REQUEST_COOLDOWN_SECONDS = 60s).
  useEffect(() => {
    if (resendIn <= 0) return
    const t = setTimeout(() => setResendIn((s) => s - 1), 1000)
    return () => clearTimeout(t)
  }, [resendIn])

  useEffect(() => {
    if (!open || phase !== 'bot') return
    let stopped = false
    let polling = false
    let timer = 0
    const tick = async () => {
      if (polling || stopped) return
      polling = true
      const result = await pollBotLoginStatusV2()
      polling = false
      if (stopped) return
      if (result.status === 'authenticated') {
        stopped = true
        window.clearInterval(timer)
        const me = await refreshAuthStateV2()
        if (me) handleClose()
        else setError('Вход подтверждён, но браузер не сохранил сессию. Обновите страницу и попробуйте снова.')
      } else if (result.status === 'expired') {
        stopped = true
        window.clearInterval(timer)
        setError('Ссылка входа устарела. Попробуйте снова.')
      } else if (result.status === 'error') {
        const me = await refreshAuthStateV2()
        if (me) {
          stopped = true
          window.clearInterval(timer)
          handleClose()
        } else {
          setError('Не удалось проверить вход. Попробуйте снова.')
        }
      }
    }
    timer = window.setInterval(tick, botPollMs)
    void tick()
    return () => {
      stopped = true
      window.clearInterval(timer)
    }
  }, [open, phase, botPollMs, handleClose])

  if (!open) return null
  const tgAvail = telegramAvailable()
  const maxAvail = maxAvailable()
  const isMiniApp = tgAvail || maxAvail
  const showTelegramBotLogin = !isMiniApp && authCaps.telegram_bot_login_available
  const showMaxBotLogin = !isMiniApp && authCaps.max_bot_login_available
  const hasProviderActions = showTelegramBotLogin || showMaxBotLogin || tgAvail || maxAvail

  const beginEmailVerification = async (targetEmail: string) => {
    const normalized = targetEmail.trim()
    const codeRes = await requestEmailCodeV2(normalized)
    setChallengeId(codeRes?.challenge_id || '')
    setDebugCode(codeRes?.debug_code)
    setResendIn(60)
    setPhase('verify')
    if (!codeRes) setError('Код не отправлен — нажмите «Отправить код ещё раз».')
  }

  const onLogin = async () => {
    setError(''); setBusy(true)
    const result = await passwordLoginV2(email.trim(), password)
    setBusy(false)
    if (result.requiresEmailVerification) {
      await beginEmailVerification(result.email || email)
      return
    }
    if (!result.ok) { setError('Неверная почта или пароль'); return }
    await refreshAuthStateV2()
    onClose()
  }
  const onRegister = async () => {
    setError('')
    if (password.length < 8) { setError('Пароль должен быть не короче 8 символов'); return }
    if (password.length > 128) { setError('Пароль не должен быть длиннее 128 символов'); return }
    if (password !== passwordRepeat) { setError('Пароли не совпадают'); return }
    setBusy(true)
    const result = await passwordRegisterV2(email.trim(), password, passwordRepeat)
    setBusy(false)
    if (!result.ok) {
      if (result.status === 409) { setError('Аккаунт уже существует. Перейдите во вкладку «Вход».'); return }
      if (result.status === 400 || result.status === 422) { setError('Проверьте email, пароль и условия регистрации.'); return }
      setError('Не удалось создать аккаунт. Попробуйте позже.'); return
    }
    if (result.requiresEmailVerification) {
      // Account+password created, but NO trusted session yet — confirm email first.
      await beginEmailVerification(email)
      return
    }
    await refreshAuthStateV2()
    handleClose()
  }
  const onVerifyEmail = async () => {
    setError(''); setBusy(true)
    const ok = await verifyEmailCodeV2(challengeId, code.trim())
    setBusy(false)
    if (!ok) { setError('Неверный или просроченный код.'); return }
    await refreshAuthStateV2() // trusted session set by backend on verify
    handleClose()
  }
  const onResendCode = async () => {
    if (resendIn > 0) return
    setError('')
    const codeRes = await requestEmailCodeV2(email.trim())
    if (!codeRes) { setError('Не удалось отправить код. Попробуйте позже.'); return }
    setChallengeId(codeRes.challenge_id)
    setDebugCode(codeRes.debug_code)
    setResendIn(60)
  }
  const onTelegram = async () => {
    setError('')
    if (await loginTelegramV2()) { await refreshAuthStateV2(); onClose() }
    else setError('Telegram доступен в мини-приложении')
  }
  const onMax = async () => {
    setError('')
    if (await loginMaxV2()) { await refreshAuthStateV2(); onClose() }
    else setError('MAX доступен в мини-приложении')
  }
  const onBotLogin = async (provider: 'telegram' | 'max') => {
    setError('')
    setBusy(true)
    const started = await startBotLoginV2(provider)
    setBusy(false)
    if (!started.ok) {
      const labels: Record<string, string> = {
        provider_not_configured: 'Этот способ входа сейчас недоступен.',
        bot_login_disabled: 'Этот способ входа сейчас недоступен.',
        network_error: 'Сеть недоступна. Проверьте соединение и попробуйте снова.',
        expired: 'Ссылка входа устарела. Попробуйте снова.',
      }
      setError(labels[started.reason] || 'Не удалось начать вход через бота. Попробуйте позже.')
      return
    }
    setBotProvider(provider)
    setBotDeepLink(started.deep_link)
    setBotPollMs(started.poll_interval_ms || 2000)
    setPhase('bot')
    window.open(started.deep_link, '_blank', 'noopener,noreferrer')
  }

  return createPortal(
    <div className="auth-modal-overlay" onClick={handleClose}>
      <div className="auth-modal" role="dialog" aria-modal="true" aria-labelledby="auth-modal-title" onClick={(e) => e.stopPropagation()}>
        <button className="auth-modal-close" aria-label="Закрыть" onClick={handleClose}><X size={20} /></button>
        <h2 id="auth-modal-title"><Lock size={18} /> Войдите, чтобы генерировать</h2>
        <p className="auth-modal-sub">Аккаунт создаётся автоматически после первого входа</p>
        {phase === 'form' && (
          <div className="auth-modal-tabs">
            <button className={`auth-modal-tab ${tab === 'login' ? 'active' : ''}`} onClick={() => { setTab('login'); setError('') }}>Вход</button>
            {authCaps.password_register_available !== false && (
              <button className={`auth-modal-tab ${tab === 'register' ? 'active' : ''}`} onClick={() => { setTab('register'); setError('') }}>Регистрация</button>
            )}
          </div>
        )}
        {authCaps.capabilities_loaded === false && <p className="auth-v2-error">Сервер авторизации недоступен. Обновите страницу или обратитесь к администратору.</p>}
        {error && <p className="auth-v2-error">{error}</p>}
        {phase === 'bot' ? (
          <>
            <p className="auth-modal-sub">Подтвердите вход в {botProvider === 'telegram' ? 'Telegram' : 'MAX'}-боте. После подтверждения это окно закроется автоматически.</p>
            <a className="generate small-action" href={botDeepLink} target="_blank" rel="noreferrer">Открыть бота</a>
            <button className="secondary" onClick={() => { setPhase('form'); setError('') }}>Попробовать снова</button>
          </>
        ) : phase === 'verify' ? (
          <>
            <p className="auth-modal-sub">Мы отправили код на <b>{email.trim()}</b>. Введите его, чтобы подтвердить email.</p>
            <label>Код из письма<input inputMode="numeric" value={code} placeholder="------" onChange={(e) => setCode(e.target.value)} /></label>
            {debugCode && <small className="auth-v2-debug">debug code: {debugCode}</small>}
            <button className="generate small-action" onClick={onVerifyEmail} disabled={!code.trim() || busy}>Подтвердить email</button>
            <button className="secondary" onClick={onResendCode} disabled={resendIn > 0}>{resendIn > 0 ? `Отправить код ещё раз (${resendIn}с)` : 'Отправить код ещё раз'}</button>
            <button className="auth-modal-back" onClick={() => { setPhase('form'); setError('') }}>← Назад</button>
          </>
        ) : tab === 'login' ? (
          <>
            <label>Email<input type="email" value={email} placeholder="you@example.com" onChange={(e) => setEmail(e.target.value)} /></label>
            <label>Пароль<input type="password" value={password} placeholder="········" onChange={(e) => setPassword(e.target.value)} /></label>
            <p className="auth-modal-hint">Введите пароль от аккаунта.</p>
            <button className="generate small-action" onClick={onLogin} disabled={!email.trim() || !password || busy}>Войти</button>
          </>
        ) : (
          <>
            <label>Email<input type="email" value={email} placeholder="you@example.com" onChange={(e) => setEmail(e.target.value)} /></label>
            <label>Пароль<input type="password" value={password} placeholder="········" onChange={(e) => setPassword(e.target.value)} /></label>
            <p className="auth-modal-hint">Минимум 8 символов.</p>
            <label>Повторите пароль<input type="password" value={passwordRepeat} placeholder="········" onChange={(e) => setPasswordRepeat(e.target.value)} /></label>
            <p className="auth-modal-consent">Нажимая кнопку, вы принимаете Пользовательское соглашение, Политику конфиденциальности и согласие на обработку персональных данных.</p>
            <button className="generate small-action" onClick={onRegister} disabled={!email.trim() || !password || !passwordRepeat || busy}>Создать аккаунт и принять условия</button>
          </>
        )}
        {hasProviderActions && (
          <div className="auth-modal-providers">
            {showTelegramBotLogin && (
              <button className="secondary" onClick={() => onBotLogin('telegram')} disabled={busy}>
                Войти через Telegram-бота
              </button>
            )}
            {showMaxBotLogin && (
              <button className="secondary" onClick={() => onBotLogin('max')} disabled={busy}>
                Войти через MAX
              </button>
            )}
            {tgAvail && <button className="secondary" onClick={onTelegram}>Войти через Telegram</button>}
            {maxAvail && <button className="secondary" onClick={onMax}>Войти через MAX</button>}
          </div>
        )}
      </div>
    </div>,
    document.body,
  )
}
