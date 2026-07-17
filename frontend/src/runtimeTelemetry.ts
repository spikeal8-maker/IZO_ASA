export type RuntimeRegion = 'root' | 'studio-form' | 'preview' | 'history' | 'gallery-picker' | 'global'

import { FRONTEND_RELEASE_ID } from './releaseIdentity'

const API = import.meta.env.VITE_API_BASE_URL || '/api'
const sent = new Set<string>()

function hash(value: string): string {
  let result = 2166136261
  for (let index = 0; index < value.length; index += 1) {
    result ^= value.charCodeAt(index)
    result = Math.imul(result, 16777619)
  }
  return (result >>> 0).toString(16).padStart(8, '0')
}

function releaseLabel(): string {
  return FRONTEND_RELEASE_ID
}

function studioMode(): string {
  const hashMode = window.location.hash.replace(/^#/, '')
  return hashMode.slice(0, 48) || 'default'
}

export function reportRuntimeError(region: RuntimeRegion, error: unknown): string {
  const kind = error instanceof Error ? error.name || 'Error' : 'UnknownError'
  const signature = hash(`${releaseLabel()}|${region}|${kind}|${window.location.pathname}`)
  const incidentId = `${Date.now().toString(36)}-${signature.slice(0, 6)}`
  if (sent.has(signature)) return incidentId
  sent.add(signature)
  const payload = {
    incident_id: incidentId,
    signature,
    region,
    route: window.location.pathname.slice(0, 160),
    mode: studioMode(),
    release: releaseLabel().slice(0, 80),
    kind: kind.slice(0, 80),
  }
  try {
    const body = JSON.stringify(payload)
    if (navigator.sendBeacon) {
      navigator.sendBeacon(`${API}/client-errors`, new Blob([body], { type: 'application/json' }))
    } else {
      void fetch(`${API}/client-errors`, { method: 'POST', credentials: 'include', keepalive: true, headers: { 'Content-Type': 'application/json' }, body })
    }
  } catch {
    // Telemetry must never become another application failure.
  }
  return incidentId
}

export function installGlobalRuntimeTelemetry(): () => void {
  const onError = (event: ErrorEvent) => reportRuntimeError('global', event.error || new Error(event.message || 'window_error'))
  const onRejection = (event: PromiseRejectionEvent) => reportRuntimeError('global', event.reason)
  window.addEventListener('error', onError)
  window.addEventListener('unhandledrejection', onRejection)
  return () => {
    window.removeEventListener('error', onError)
    window.removeEventListener('unhandledrejection', onRejection)
  }
}
