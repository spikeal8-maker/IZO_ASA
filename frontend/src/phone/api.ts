import { isPhonePlatformManifest, type PhonePlatformManifest } from './contracts.ts'

export class PhoneApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'PhoneApiError'
    this.status = status
  }
}

export async function loadPhonePlatform(signal?: AbortSignal): Promise<PhonePlatformManifest> {
  const response = await fetch('/api/phone/v1/platform', {
    credentials: 'include',
    headers: { Accept: 'application/json' },
    signal,
  })
  if (!response.ok) {
    throw new PhoneApiError(response.status, 'Не удалось загрузить мобильную платформу.')
  }
  const payload: unknown = await response.json()
  if (!isPhonePlatformManifest(payload)) {
    throw new PhoneApiError(502, 'Сервер вернул несовместимые настройки мобильной платформы.')
  }
  return payload
}
