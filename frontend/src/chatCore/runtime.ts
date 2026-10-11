import type {
  PortableChatCompletion,
  PortableChatObserver,
  PortableChatRequest,
  PortableChatTransport,
} from './types.ts'

export type PortableChatPhase = 'idle' | 'loading' | 'streaming' | 'stopped' | 'error'

export type PortableChatRuntimeState = {
  phase: PortableChatPhase
  error: string
}

type LastRequest = {
  request: PortableChatRequest
  observer?: PortableChatObserver
}

const abortError = (caught: unknown) => caught instanceof DOMException && caught.name === 'AbortError'

export class PortableChatRuntime {
  private active: AbortController | null = null
  private last: LastRequest | null = null
  private listeners = new Set<(state: PortableChatRuntimeState) => void>()
  private currentState: PortableChatRuntimeState = { phase: 'idle', error: '' }

  constructor(private readonly transport: PortableChatTransport) {}

  get state(): PortableChatRuntimeState {
    return this.currentState
  }

  subscribe(listener: (state: PortableChatRuntimeState) => void): () => void {
    this.listeners.add(listener)
    listener(this.currentState)
    return () => this.listeners.delete(listener)
  }

  send(request: PortableChatRequest, observer?: PortableChatObserver): Promise<PortableChatCompletion> {
    this.last = { request, observer }
    return this.execute(request, observer)
  }

  retry(observer?: PortableChatObserver): Promise<PortableChatCompletion> {
    if (!this.last) return Promise.reject(new Error('Нет запроса для повтора.'))
    const nextObserver = observer || this.last.observer
    this.last = { request: this.last.request, observer: nextObserver }
    return this.execute(this.last.request, nextObserver)
  }

  stop(): void {
    this.active?.abort()
  }

  private setState(state: PortableChatRuntimeState): void {
    this.currentState = state
    for (const listener of this.listeners) listener(state)
  }

  private async execute(request: PortableChatRequest, observer?: PortableChatObserver): Promise<PortableChatCompletion> {
    this.active?.abort()
    const controller = new AbortController()
    this.active = controller
    let text = ''
    const tools: PortableChatCompletion['tools'] = []
    let messageId: string | null = null
    this.setState({ phase: 'loading', error: '' })
    const wrapped: PortableChatObserver = {
      onEvent: (event) => {
        if (event.type === 'state' || event.type === 'delta' || event.type === 'tool') {
          this.setState({ phase: 'streaming', error: '' })
        }
        if (event.type === 'delta') text += event.text
        if (event.type === 'tool') tools.push(event.tool)
        if (event.type === 'done') messageId = event.messageId
        observer?.onEvent?.(event)
      },
    }
    try {
      const completion = await this.transport(request, controller.signal, wrapped)
      this.setState({ phase: 'idle', error: '' })
      return {
        text: completion.text || text,
        tools: completion.tools.length ? completion.tools : tools,
        messageId: completion.messageId || messageId,
        stopped: false,
      }
    } catch (caught) {
      if (controller.signal.aborted || abortError(caught)) {
        this.setState({ phase: 'stopped', error: '' })
        return { text, tools, messageId, stopped: true }
      }
      const message = caught instanceof Error ? caught.message : 'Чат временно недоступен.'
      this.setState({ phase: 'error', error: message })
      throw caught
    } finally {
      if (this.active === controller) this.active = null
    }
  }
}

export type { PortableChatCompletion } from './types.ts'
