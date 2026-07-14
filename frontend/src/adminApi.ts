import { ensureSessionRefreshedV2, refreshAuthStateV2 } from './authV2'

const API = (import.meta as ImportMeta & { env?: { VITE_API_BASE_URL?: string } }).env?.VITE_API_BASE_URL || '/api'

export type AdminRecord = Record<string, unknown>

export async function adminFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers)
  const request = () => fetch(`${API}${path}`, { ...init, headers, credentials: 'include' })
  let response = await request()
  if (response.status === 401 && !path.includes('/auth/session/refresh-v2')) {
    const refreshed = await ensureSessionRefreshedV2()
    if (refreshed) {
      await refreshAuthStateV2().catch(() => null)
      response = await request()
    }
  }
  return response
}

export async function adminGet<T>(path: string): Promise<T | null> {
  const response = await adminFetch(path)
  if (!response.ok) return null
  return await response.json() as T
}

export async function adminPost<T>(path: string, body: unknown): Promise<T | null> {
  const response = await adminFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) return null
  return await response.json() as T
}
