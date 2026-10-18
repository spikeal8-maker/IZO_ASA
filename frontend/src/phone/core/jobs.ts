import { phoneFetch } from './http.ts'


export type PhoneJobModality = 'image' | 'video' | 'chat' | 'audio' | '3d'
export type PhoneJobStatus = 'created' | 'queued' | 'running' | 'processing' | 'completed' | 'failed' | 'cancelled' | 'expired'

export type PhoneMediaAsset = {
  id: string | null
  type: PhoneJobModality
  url: string
  thumbnailUrl: string | null
  width: number | null
  height: number | null
  durationSeconds: number | null
  aspectRatio: string | null
}

export type PhoneJob = {
  id: string
  modality: PhoneJobModality
  operation: string
  status: PhoneJobStatus
  phase: 'created' | 'queued' | 'running' | 'processing' | 'terminal'
  progress: number
  message: string
  createdAt: string | null
  startedAt: string | null
  completedAt: string | null
  terminal: boolean
  result: PhoneMediaAsset | null
  billing: { chargedTokens: number | null; tokenKind: 'daily' | 'main' | null; refunded: boolean }
}

const modalities = new Set<PhoneJobModality>(['image', 'video', 'chat', 'audio', '3d'])
const statuses = new Set<PhoneJobStatus>(['created', 'queued', 'running', 'processing', 'completed', 'failed', 'cancelled', 'expired'])

export function isPhoneJob(value: unknown): value is PhoneJob {
  if (!value || typeof value !== 'object') return false
  const job = value as Partial<PhoneJob>
  return typeof job.id === 'string'
    && modalities.has(job.modality as PhoneJobModality)
    && statuses.has(job.status as PhoneJobStatus)
    && typeof job.progress === 'number'
    && job.progress >= 0
    && job.progress <= 100
    && typeof job.terminal === 'boolean'
}

function requireJob(value: unknown): PhoneJob {
  if (!isPhoneJob(value)) throw new Error('Сервер вернул несовместимое состояние задания.')
  return value
}

export async function loadPhoneJobs(active = true, signal?: AbortSignal): Promise<PhoneJob[]> {
  const payload = await phoneFetch<{ items?: unknown[] }>(`/api/phone/v1/jobs?active=${active}`, { signal })
  if (!Array.isArray(payload.items)) throw new Error('Сервер вернул несовместимый список заданий.')
  return payload.items.map(requireJob)
}

export async function loadPhoneJob(jobId: string, signal?: AbortSignal): Promise<PhoneJob> {
  const payload = await phoneFetch<{ job?: unknown }>(`/api/phone/v1/jobs/${encodeURIComponent(jobId)}`, { signal })
  return requireJob(payload.job)
}

export async function waitForPhoneJob(
  jobId: string,
  options: {
    signal?: AbortSignal
    intervalMs?: number
    read?: (id: string, signal?: AbortSignal) => Promise<PhoneJob>
    onChange?: (job: PhoneJob) => void
  } = {},
): Promise<PhoneJob> {
  const interval = Math.max(250, Math.min(options.intervalMs ?? 1500, 10_000))
  const read = options.read ?? loadPhoneJob
  while (!options.signal?.aborted) {
    const job = await read(jobId, options.signal)
    options.signal?.throwIfAborted()
    options.onChange?.(job)
    options.signal?.throwIfAborted()
    if (job.terminal) return job
    await new Promise<void>((resolve, reject) => {
      const onAbort = () => {
        globalThis.clearTimeout(timer)
        options.signal?.removeEventListener('abort', onAbort)
        reject(new DOMException('Aborted', 'AbortError'))
      }
      const timer = globalThis.setTimeout(() => {
        options.signal?.removeEventListener('abort', onAbort)
        resolve()
      }, interval)
      options.signal?.addEventListener('abort', onAbort, { once: true })
      if (options.signal?.aborted) onAbort()
    })
  }
  throw new DOMException('Aborted', 'AbortError')
}
