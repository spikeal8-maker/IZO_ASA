export type PortableChatRole = 'user' | 'assistant'
export type PortableToolChoice = 'auto' | 'generate_image'

export type PortableChatTurn = {
  role: PortableChatRole
  content: string
}

export type PortableChatTool = {
  name: 'generate_image'
  status?: 'requested' | 'running' | 'done' | 'error'
  prompt?: string
  aspectRatio?: string
  resultUrl?: string
  jobId?: string
  error?: string
}

export type PortableChatRequest = {
  provider: string
  model: string
  messages: PortableChatTurn[]
  threadId?: string
  toolChoice?: PortableToolChoice
}

export type PortableChatEvent =
  | { type: 'state'; state: 'streaming' }
  | { type: 'delta'; text: string }
  | { type: 'tool'; tool: PortableChatTool }
  | { type: 'done'; provider: string; model: string; messageId: string | null }
  | { type: 'error'; code: string; message: string; status?: number }

export type PortableChatCompletion = {
  text: string
  tools: PortableChatTool[]
  messageId: string | null
  stopped: boolean
}

export type PortableChatObserver = {
  onEvent?: (event: PortableChatEvent) => void
}

export type PortableChatTransport = (
  request: PortableChatRequest,
  signal: AbortSignal,
  observer?: PortableChatObserver,
) => Promise<PortableChatCompletion>
