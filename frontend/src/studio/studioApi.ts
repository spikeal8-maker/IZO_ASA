// ARCH-FE-STUDIO-001A: studio API layer extracted from newUi.tsx. URL helpers,
// the trusted-session fetch wrappers and public error-text sanitizers. Behaviour
// and API contracts are unchanged. This module must not import newUi.tsx.
import { ensureSessionRefreshedV2 } from '../authV2'

export const API = import.meta.env.VITE_API_BASE_URL || '/api'
// Origin API-сервера для относительных media-URL из ответов backend
// (в проде API='/api' → origin пуст и URL остаются относительными).
export const API_ORIGIN = API.endsWith('/api') ? API.slice(0, -'/api'.length) : ''

export function apiUrl(path: unknown): string {
  if (typeof path !== 'string' || !path) return ''
  return path.startsWith('/') ? `${API_ORIGIN}${path}` : path
}

export function userMediaUrl(path: string | null | undefined): string | null {
  if (!path) return null
  return path.startsWith('/media/') ? apiUrl(path) : path
}

// Auth: только trusted cookie session (credentials: include). Никаких legacy
// заголовков, кук или клиентских идентификаторов — см. docs/new-ui-v2-plan.md.
export async function apiFetch(path: string, init: RequestInit = {}) {
  const request = () => fetch(`${API}${path}`, { ...init, credentials: 'include' })
  let response = await request()
  if (response.status === 401 && await ensureSessionRefreshedV2()) response = await request()
  return response
}

export async function verifyPrivateImage(path: string): Promise<void> {
  const request = () => fetch(apiUrl(path), { credentials: 'include' })
  let response = await request()
  if (response.status === 401 && await ensureSessionRefreshedV2()) response = await request()
  if (!response.ok) throw new Error(`Image unavailable: ${response.status}`)
  await response.body?.cancel().catch(() => undefined)
}

export const PRIVATE_ERROR_DETAILS = /(?:openai|openrouter|comfy\s*ui|coffee\s*ui|api[\s_-]*key|provider|endpoint|traceback|stack trace|insufficient[_\s-]*(?:credits?|quota)|billing|authentication failed|connection refused|econnrefused)/i

export function publicErrorText(message: string, fallback: string): string {
  const normalized = message.trim()
  if (!normalized || PRIVATE_ERROR_DETAILS.test(normalized)) return fallback
  return normalized
}

export function apiErrorText(detail: unknown, fallback: string): string {
  if (typeof detail === 'string' && detail.trim()) return publicErrorText(detail, fallback)
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => item && typeof item === 'object' && 'msg' in item ? String(item.msg || '') : '')
      .filter(Boolean)
    if (messages.length) return publicErrorText(messages.join('. '), fallback)
  }
  if (detail && typeof detail === 'object') {
    const value = detail as { code?: unknown; field?: unknown; message?: unknown }
    if (typeof value.message === 'string' && value.message.trim()) return publicErrorText(value.message, fallback)
    const field = typeof value.field === 'string' ? value.field : 'изображение'
    if (value.code === 'input_media_missing') return `Файл для поля «${field}» больше не найден. Выберите изображение заново.`
    if (value.code === 'input_media_unavailable') return `Изображение для поля «${field}» недоступно. Выберите свой файл или изображение из галереи.`
  }
  return fallback
}
