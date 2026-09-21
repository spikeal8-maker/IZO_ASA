import type {
  PortableChatCompletion,
  PortableChatEvent,
  PortableChatTransport,
} from './types.ts'

export class PortableChatTransportError extends Error {
  constructor(
    message: string,
    readonly code = 'transport',
    readonly status = 0,
  ) {
    super(message)
  }
}

async function responseError(response: Response): Promise<PortableChatTransportError> {
  try {
    const payload = (await response.json()) as { detail?: string }
    return new PortableChatTransportError(payload.detail || 'Чат временно недоступен.', 'http', response.status)
  } catch {
    return new PortableChatTransportError('Чат временно недоступен.', 'http', response.status)
  }
}

export function createHttpChatTransport(endpoint = '/api/chat/stream'): PortableChatTransport {
  return async (request, signal, observer): Promise<PortableChatCompletion> => {
    const response = await fetch(endpoint, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', Accept: 'application/x-ndjson' },
      body: JSON.stringify(request),
      signal,
    })
    if (!response.ok) throw await responseError(response)
    if (!response.body) throw new PortableChatTransportError('Сервер не открыл поток ответа.')

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let text = ''
    const tools: PortableChatCompletion['tools'] = []
    let messageId: string | null = null

    const consume = (line: string) => {
      if (!line.trim()) return
      let event: PortableChatEvent
      try {
        event = JSON.parse(line) as PortableChatEvent
      } catch {
        return
      }
      if (event.type === 'error') throw new PortableChatTransportError(event.message, event.code, event.status || 0)
      if (event.type === 'delta') text += event.text
      if (event.type === 'tool') tools.push(event.tool)
      if (event.type === 'done') messageId = event.messageId
      observer?.onEvent?.(event)
    }

    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      for (const line of lines) consume(line)
      if (done) break
    }
    if (buffer.trim()) consume(buffer)
    return { text, tools, messageId, stopped: false }
  }
}
