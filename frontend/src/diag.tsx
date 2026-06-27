// Safe live-delivery diagnostics. Gated behind ?diag=1 or #diag.
// Shows ONLY booleans / coarse categories / build labels — never initData,
// WebAppData, user ids, tokens, cookies, or the full query/hash.
import { useEffect, useState } from 'react'
import type { ReactElement } from 'react'
import { useAuthV2 } from './authV2'

// Bump this string on every frontend deploy so you can confirm which bundle is live.
export const APP_BUILD_LABEL = '20C.3-2026-06-27'

export function isDiagMode(): boolean {
  try {
    const params = new URLSearchParams(window.location.search)
    return params.get('diag') === '1' || window.location.hash.includes('diag')
  } catch {
    return false
  }
}

type TgWin = Window & {
  Telegram?: { WebApp?: { initData?: string; ready?: unknown; expand?: unknown } }
  MAX?: { WebApp?: { webAppData?: string; initData?: string } }
  maxWebApp?: { webAppData?: string; initData?: string }
}

function telegramBooleans() {
  const w = window as TgWin
  const wa = w.Telegram?.WebApp
  return {
    hasTelegram: !!w.Telegram,
    hasTelegramWebApp: !!wa,
    hasTelegramInitData: !!wa?.initData,
    initDataLengthCategory: (wa?.initData?.length ?? 0) > 0 ? 'nonzero' : 'zero',
    readyCallable: typeof wa?.ready === 'function',
    expandCallable: typeof wa?.expand === 'function',
  }
}

function maxBooleans() {
  const w = window as TgWin
  const webApp = w.MAX?.WebApp || w.maxWebApp
  const haystack = (window.location.hash + window.location.search).toLowerCase()
  return {
    hasMaxGlobal: !!w.MAX,
    hasWebAppGlobal: !!webApp,
    hasMaxWebAppData: !!(w.MAX?.WebApp?.webAppData || w.maxWebApp?.webAppData),
    hasMaxInitData: !!w.MAX?.WebApp?.initData,
    hasHashWebAppDataParam: /(?:^|[#?&])(?:tgwebappdata|webappdata|web_app_data)=/.test(haystack),
    userAgentMaxLike: /max/i.test(navigator.userAgent),
    mobile: /Mobi|Android|iPhone|iPad/i.test(navigator.userAgent),
  }
}

function deliveryBooleans() {
  let viteClient = false
  try {
    viteClient = !!document.querySelector('script[src="/@vite/client"]')
  } catch {
    /* ignore */
  }
  const hot = (import.meta as ImportMeta & { hot?: unknown }).hot
  return {
    origin: window.location.origin,
    path: window.location.pathname, // path only — never full query/hash
    hasSearch: window.location.search.length > 0,
    hasHash: window.location.hash.length > 0,
    isViteDevClientPresent: viteClient,
    hasHmrClient: typeof hot !== 'undefined',
  }
}

export function DiagPanel(): ReactElement {
  const { status } = useAuthV2()
  const [backend, setBackend] = useState<Record<string, unknown> | null>(null)
  useEffect(() => {
    let alive = true
    fetch('/api/version', { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => alive && setBackend(d))
      .catch(() => alive && setBackend(null))
    return () => {
      alive = false
    }
  }, [])

  const rows: Array<[string, unknown]> = [
    ['frontend.build', APP_BUILD_LABEL],
    ['backend.build', backend?.build ?? '—'],
    ['backend.auth_v2', backend?.auth_v2 ?? '—'],
    ['backend.generation_protected', backend?.generation_protected ?? '—'],
    ['auth.state', status],
    ...Object.entries(deliveryBooleans()),
    ...Object.entries(telegramBooleans()).map(([k, v]) => [`tg.${k}`, v] as [string, unknown]),
    ...Object.entries(maxBooleans()).map(([k, v]) => [`max.${k}`, v] as [string, unknown]),
  ]

  return (
    <div className="diag-panel" role="region" aria-label="diagnostics">
      <strong>DIAG</strong>
      <table>
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k}>
              <td>{k}</td>
              <td>{String(v)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
