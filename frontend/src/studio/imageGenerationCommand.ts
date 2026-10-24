/** One durable browser command per unresolved paid image-generation intent. No prompts or media are stored. */
export type ImageCommandScope = 'phone' | 'desktop'

type PendingImageCommand = {
  version: 1
  key: string
  seed: number
  payloadHash: string
  acceptedJobId?: string
}

export type ImageGenerationCommand = { key: string; seed: number; body: string; acceptedJobId?: string }

const keyFor = (scope: ImageCommandScope) => `izo.image.pending.${scope}.v1`
const replayBlocked = 'Предыдущий запуск ещё не подтверждён. Проверьте задания и повторите его с прежними параметрами, прежде чем начинать другую генерацию.'

function readPending(scope: ImageCommandScope): PendingImageCommand | null {
  const raw = sessionStorage.getItem(keyFor(scope))
  if (raw === null) return null
  try {
    const value: unknown = JSON.parse(raw)
    if (!value || typeof value !== 'object') throw new Error('invalid')
    const pending = value as Partial<PendingImageCommand>
    if (pending.version !== 1 || typeof pending.key !== 'string'
      || !/^[a-f0-9-]{36}$/.test(pending.key)
      || !Number.isSafeInteger(pending.seed) || Number(pending.seed) < 1 || Number(pending.seed) > 2147483646
      || typeof pending.payloadHash !== 'string' || !/^(?:[a-f0-9]{64})?$/.test(pending.payloadHash)
      || (pending.acceptedJobId !== undefined && (typeof pending.acceptedJobId !== 'string'
        || !/^[a-zA-Z0-9_-]{1,160}$/.test(pending.acceptedJobId)))) {
      throw new Error('invalid')
    }
    return pending as PendingImageCommand
  } catch {
    throw new Error('Не удалось проверить сохранённый запрос. Новое списание заблокировано; проверьте задания и данные браузера.')
  }
}

function writePending(scope: ImageCommandScope, command: PendingImageCommand): void {
  sessionStorage.setItem(keyFor(scope), JSON.stringify(command))
}

async function hashPayload(body: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(body))
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
}

export async function beginImageGenerationCommand(
  scope: ImageCommandScope,
  draft: Record<string, unknown>,
  requestedSeed?: number,
): Promise<ImageGenerationCommand> {
  const previous = readPending(scope)
  const key = previous?.key ?? crypto.randomUUID()
  const freshSeed = crypto.getRandomValues(new Uint32Array(1))[0] % 2147483646 + 1
  const seed = previous?.seed ?? (
    Number.isSafeInteger(requestedSeed) && Number(requestedSeed) >= 1 && Number(requestedSeed) <= 2147483646
      ? Number(requestedSeed) : freshSeed
  )

  // Persist the identity before hashing or making a network request; a reload
  // must never silently replace a potentially accepted paid command.
  if (!previous) writePending(scope, { version: 1, key, seed, payloadHash: '' })
  const body = JSON.stringify({ ...draft, seed, clientRequestId: key })
  const payloadHash = await hashPayload(body)
  const current = readPending(scope)
  if (!current || current.key !== key || (current.payloadHash && current.payloadHash !== payloadHash)) {
    throw new Error(replayBlocked)
  }
  if (!current.payloadHash) writePending(scope, { ...current, payloadHash })
  return { key, seed, body, acceptedJobId: current.acceptedJobId }
}

export function acknowledgeImageGenerationCommand(scope: ImageCommandScope, key: string, jobId: string): void {
  if (!/^[a-zA-Z0-9_-]{1,160}$/.test(jobId)) throw new Error('Сервер вернул некорректный идентификатор задания.')
  const pending = readPending(scope)
  if (pending?.key === key) writePending(scope, { ...pending, acceptedJobId: jobId })
}

export function completeImageGenerationCommand(scope: ImageCommandScope, jobId: string): void {
  const pending = readPending(scope)
  if (pending?.acceptedJobId === jobId) sessionStorage.removeItem(keyFor(scope))
}

export function rejectImageGenerationCommand(scope: ImageCommandScope, key: string, status: number): void {
  // These are definite pre-admission rejections. 409/429/5xx and lost
  // responses remain unresolved and must be retried with the original key.
  if ([400, 401, 402, 403, 422].includes(status)) {
    const pending = readPending(scope)
    if (pending?.key === key && !pending.acceptedJobId) sessionStorage.removeItem(keyFor(scope))
  }
}
