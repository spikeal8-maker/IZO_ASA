type KeyResult = { ok?: boolean; keySaved?: boolean; keyRemoved?: boolean; keyVerified?: boolean; environmentOverride?: boolean; key?: { configured?: boolean; ok?: boolean; storeAvailable?: boolean } }
type Fetcher = (path: string, init?: RequestInit) => Promise<Response>
export type KeyAction = { saved: boolean; verified: boolean; message: string }

export async function saveOpenrouterKey(fetcher: Fetcher, key: string): Promise<KeyAction> {
  const failed = { saved: false, verified: false, message: 'Не удалось подтвердить сохранение ключа. Введённое значение оставлено для повторной попытки.' }
  try {
    const response = await fetcher('/admin/openrouter/key', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key: key.trim() }) })
    const result = await response.json() as KeyResult
    if (!response.ok || result?.ok !== true || result.keySaved !== true) return failed
    const verified = result.keyVerified === true
    const message = result.environmentOverride ? 'Ключ сохранён. Сейчас используется ключ из настроек окружения.' : verified ? 'Ключ OpenRouter сохранён и проверен' : 'Ключ сохранён, но проверка OpenRouter пока не подтверждена.'
    return { saved: true, verified, message }
  } catch { return failed }
}

export async function checkOpenrouterKey(fetcher: Fetcher): Promise<string> {
  try {
    const response = await fetcher('/admin/openrouter/key', { method: 'GET' })
    const result = await response.json() as KeyResult
    if (!response.ok || result?.ok !== true) return 'Не удалось проверить ключ OpenRouter.'
    if (result.key?.storeAvailable === false) return 'Хранилище ключа недоступно.'
    if (result.key?.configured === false) return 'Ключ OpenRouter не настроен.'
    if (result.key?.configured !== true) return 'Не удалось проверить ключ OpenRouter.'
    return result.keyVerified === true ? 'Ключ OpenRouter проверен.' : 'Ключ сохранён, но OpenRouter не подтвердил проверку.'
  } catch { return 'Не удалось проверить ключ OpenRouter.' }
}

export async function deleteOpenrouterKey(fetcher: Fetcher): Promise<string> {
  try {
    const response = await fetcher('/admin/openrouter/key', { method: 'DELETE' })
    const result = await response.json() as KeyResult
    if (!response.ok || result?.ok !== true || result.keyRemoved !== true) return 'Не удалось подтвердить удаление ключа.'
    return result.environmentOverride ? 'UI-ключ удалён. Ключ из настроек окружения остаётся активным.' : 'UI-ключ OpenRouter удалён.'
  } catch { return 'Не удалось подтвердить удаление ключа.' }
}

export function openrouterSecretSource(source: string | undefined): string {
  if (source === 'env') return 'Настройки окружения'
  if (source === 'linux-aes-gcm') return 'Защищённое хранилище Linux'
  if (source === 'dpapi' || source === 'admin_ui') return 'Защищённое хранилище Windows'
  return '—'
}
