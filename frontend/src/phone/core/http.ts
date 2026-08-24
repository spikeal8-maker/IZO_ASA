export class PhoneTransportError extends Error {
  status: number
  retryable: boolean

  constructor(status: number, message: string, retryable = status === 0 || status >= 500) {
    super(message)
    this.name = 'PhoneTransportError'
    this.status = status
    this.retryable = retryable
  }
}

const privateErrorPattern = /openrouter|openai|comfy\s*ui|provider|endpoint|api[ _-]*key|insufficient|credits|traceback/i

function publicMessage(value: unknown, fallback: string): string {
  const message = typeof value === 'string' ? value.trim() : ''
  return message && !privateErrorPattern.test(message) ? message : fallback
}

export async function phoneFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, {
      ...init,
      credentials: 'include',
      headers: { Accept: 'application/json', ...init.headers },
    })
  } catch {
    throw new PhoneTransportError(0, 'Нет соединения с сервером.')
  }
  if (!response.ok) {
    let detail: unknown
    try {
      const payload = await response.json() as { detail?: unknown }
      detail = payload.detail
    } catch {
      detail = null
    }
    const fallback = response.status === 401
      ? 'Нужно снова войти в аккаунт.'
      : 'Сервис временно недоступен. Попробуйте ещё раз или обратитесь в поддержку.'
    throw new PhoneTransportError(response.status, publicMessage(detail, fallback))
  }
  return response.json() as Promise<T>
}
