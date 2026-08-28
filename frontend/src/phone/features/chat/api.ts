import { phoneFetch } from '../../core/http.ts'
import { waitForPhoneJob } from '../../core/jobs.ts'


export type PhoneChatThread = {
  id: string
  title: string
  chatModelId: string
  imageModelId: string | null
  videoModelId: string | null
  contextChars: number
  createdAt: string
  updatedAt: string
}

export type PhoneChatTool = {
  name: 'web_search' | 'generate_image' | string
  ok?: boolean
  status?: 'requested' | 'running' | 'done' | 'error'
  query?: string
  prompt?: string
  aspectRatio?: string
  resultUrl?: string
  jobId?: string
  sources?: Array<{ title: string; url: string }>
  error?: string
}

export type PhoneChatMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
  provider: string
  model: string
  tools: PhoneChatTool[]
  chargedTokens: number
  tokenKind: 'daily' | 'main' | ''
  createdAt: string
  status: 'done' | 'pending' | 'error'
}

export type PhoneChatModel = {
  id: string
  name: string
  provider: 'local' | 'api'
  tokenCost: number
  tokenKind: 'free' | 'daily' | 'main'
  description: string
  contextChars: number
  inputPerMillionUsd?: number
  outputPerMillionUsd?: number
  inputPerMillionProductTokens?: number
  outputPerMillionProductTokens?: number
  retailPerMillionProductTokens?: number
  available?: boolean
  unavailableReason?: string
  usageBased?: boolean
  priceGuidance?: string
}

export async function listChatThreads(signal?: AbortSignal): Promise<PhoneChatThread[]> {
  const payload = await phoneFetch<{ threads?: PhoneChatThread[] }>('/api/phone/chat/threads', { signal })
  return Array.isArray(payload.threads) ? payload.threads : []
}

export async function createChatThread(modelId: string, signal?: AbortSignal): Promise<PhoneChatThread> {
  const payload = await phoneFetch<{ thread: PhoneChatThread }>('/api/phone/chat/threads', {
    method: 'POST', signal, headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: 'Новый чат', chatModelId: modelId, contextChars: 60000 }),
  })
  return payload.thread
}

export async function updateChatThread(threadId: string, values: Partial<Pick<PhoneChatThread, 'title' | 'chatModelId' | 'imageModelId' | 'videoModelId' | 'contextChars'>>): Promise<PhoneChatThread> {
  const payload = await phoneFetch<{ thread: PhoneChatThread }>(`/api/phone/chat/threads/${encodeURIComponent(threadId)}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(values),
  })
  return payload.thread
}

export async function deleteChatThread(threadId: string): Promise<void> {
  await phoneFetch(`/api/phone/chat/threads/${encodeURIComponent(threadId)}`, { method: 'DELETE' })
}

export async function loadChatMessages(threadId: string, signal?: AbortSignal): Promise<{ thread: PhoneChatThread; messages: PhoneChatMessage[] }> {
  const payload = await phoneFetch<{ thread: PhoneChatThread; messages?: PhoneChatMessage[] }>(`/api/phone/chat/threads/${encodeURIComponent(threadId)}/messages`, { signal })
  return { thread: payload.thread, messages: Array.isArray(payload.messages) ? payload.messages : [] }
}

export async function loadChatModels(signal?: AbortSignal): Promise<{ defaultModel: string; models: PhoneChatModel[] }> {
  const payload = await phoneFetch<{ defaultModel?: string; models?: PhoneChatModel[] }>('/api/phone/chat/models', { signal })
  return { defaultModel: payload.defaultModel || 'local:izo-chat', models: Array.isArray(payload.models) ? payload.models : [] }
}

export async function sendChatMessage(input: {
  threadId: string
  content: string
  modelId: string
  images: string[]
  requestId: string
}): Promise<{
  reply: string
  modelId: string
  chargedTokens: number
  tokenKind: 'daily' | 'main'
  tools: PhoneChatTool[]
  messageId?: string | null
}> {
  return phoneFetch('/api/phone/chat', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      messages: [{ role: 'user', content: input.content }], threadId: input.threadId,
      modelId: input.modelId, route: 'auto', requestId: input.requestId, images: input.images,
    }),
  })
}

export async function saveChatTools(threadId: string, messageId: string, tools: PhoneChatTool[]): Promise<void> {
  await phoneFetch(`/api/phone/chat/threads/${encodeURIComponent(threadId)}/messages/${encodeURIComponent(messageId)}/tools`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ tools }),
  })
}

export async function runChatImageTool(tool: PhoneChatTool, onChange: (tool: PhoneChatTool) => void, preferredModelId?: string | null): Promise<PhoneChatTool> {
  const sizes: Record<string, [string, number, number]> = {
    '1:1': ['sq-hd', 1024, 1024], '9:16': ['v-hd', 720, 1280],
    '16:9': ['h-hd', 1280, 720], '3:2': ['p-hd', 1152, 768],
  }
  const access = await phoneFetch<{ modes?: Record<string, { models?: Array<{ id: string; provider: 'comfyui' | 'openrouter'; modelProfile: string }>; presets?: { fast?: string } }> }>('/api/model-access')
  const row = access.modes?.text_to_image
  const models = row?.models || []
  const selected = models.find((item) => item.id === preferredModelId) || models.find((item) => item.id === row?.presets?.fast) || models[0] || { id: 'server:local_flux_klein', provider: 'comfyui' as const, modelProfile: 'local_flux_klein' }
  const [resolutionId, width, height] = sizes[tool.aspectRatio || '1:1'] || sizes['1:1']
  const started = await phoneFetch<{ id?: string; jobId?: string }>('/api/generate', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      mode: 'text_to_image', provider: selected.provider, prompt: String(tool.prompt || '').slice(0, 3000),
      negativePrompt: '', seed: Math.floor(Math.random() * 2147483646) + 1, width, height,
      resolutionId, steps: 4, cfg: 1, guidance: 3.5, strength: .75,
      modelProfile: selected.modelProfile, loras: [],
    }),
  })
  const jobId = String(started.id || started.jobId || '')
  if (!jobId) throw new Error('Сервер не вернул номер генерации.')
  const running = { ...tool, status: 'running' as const, jobId }
  onChange(running)
  const job = await waitForPhoneJob(jobId, { onChange: () => undefined })
  if (job.status !== 'completed' || !job.result?.url) throw new Error(job.message || 'Изображение не создано.')
  const completed = { ...running, status: 'done' as const, resultUrl: job.result.url }
  onChange(completed)
  return completed
}

export async function transcribePhoneVoice(blob: Blob, durationMs: number): Promise<string> {
  const extension = blob.type.includes('ogg') ? 'ogg' : blob.type.includes('mp4') ? 'm4a' : 'webm'
  const form = new FormData()
  form.append('file', blob, `voice.${extension}`)
  const payload = await phoneFetch<{ text?: string }>(`/api/tools/transcribe?duration_ms=${Math.round(durationMs)}&language=ru`, { method: 'POST', body: form })
  return String(payload.text || '').trim()
}
