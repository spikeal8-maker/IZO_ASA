/** Persist-first OpenRouter key actions. Never log, return, or cache raw keys. */
type Requester = (path: string, init?: RequestInit) => Promise<Response>
type KeyAction = { saved: boolean; message: string }

export async function saveOpenRouterKeyAction(request: Requester, input: string): Promise<KeyAction> {
  const key = input.trim()
  if (!key.startsWith('sk-or-') || key.length < 12) {
    return { saved: false, message: 'Нужен ключ OpenRouter формата sk-or-…' }
  }
  try {
    const response = await request('/admin/openrouter/key', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key }),
    })
    const body = await response.json().catch(() => null) as { ok?: boolean; keySaved?: boolean; detail?: string } | null
    if (!response.ok || !body?.ok || body?.keySaved !== true) {
      return { saved: false, message: `Ключ не сохранён: ${body?.detail || 'HTTP ' + response.status}. Поле оставлено для исправления.` }
    }
    return { saved: true, message: 'Ключ сохранён в защищённом хранилище. Проверка OpenRouter выполняется отдельно.' }
  } catch {
    return { saved: false, message: 'Соединение с админкой недоступно. Ключ не подтверждён, поле оставлено.' }
  }
}

export async function checkOpenRouterKeyAction(request: Requester): Promise<string> {
  try {
    const response = await request('/admin/openrouter/key/check', { method: 'POST' })
    const status = await response.json().catch(() => null) as { liveVerified?: boolean; error?: string; state?: string } | null
    return status?.liveVerified ? 'OpenRouter подтвердил ключ через /api/v1/key'
      : `Проверка не пройдена: ${status?.error || status?.state || 'HTTP ' + response.status}. Ключ не удалён.`
  } catch {
    return 'Проверка соединения недоступна. Сохранённый ключ не удалён.'
  }
}
