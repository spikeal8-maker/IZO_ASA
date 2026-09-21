export type DeepSeekProviderModel = {
  id: string
  providerModelId: string
  name: string
  provider: 'deepseek'
  description: string
  available: boolean
  unavailableReason?: string
}

export type DeepSeekProviderStatus = {
  ok: boolean
  provider: 'deepseek'
  configured: boolean
  models: DeepSeekProviderModel[]
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: 'same-origin',
    ...init,
    headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
  })
  if (!response.ok) {
    let message = 'DeepSeek временно недоступен.'
    try {
      const payload = (await response.json()) as { detail?: string }
      if (payload.detail) message = payload.detail
    } catch {
      // Keep sanitized fallback.
    }
    throw new Error(message)
  }
  return (await response.json()) as T
}

export function loadDeepSeekStatus(signal?: AbortSignal): Promise<DeepSeekProviderStatus> {
  return requestJson<DeepSeekProviderStatus>('/api/chat/providers/deepseek', { signal })
}

export async function saveDeepSeekKey(key: string): Promise<void> {
  await requestJson('/api/chat/providers/deepseek/key', {
    method: 'PUT',
    body: JSON.stringify({ key }),
  })
}

export async function deleteDeepSeekKey(): Promise<void> {
  await requestJson('/api/chat/providers/deepseek/key', { method: 'DELETE' })
}

export function testDeepSeekConnection(): Promise<{ connected: boolean; models: string[] }> {
  return requestJson('/api/chat/providers/deepseek/test', { method: 'POST' })
}
