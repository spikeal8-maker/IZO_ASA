/** Durable paid-image intent, separated by server-verified account identity. No prompt/media persisted. */
export type ImageCommandScope = 'phone' | 'desktop'

type PendingImageCommand = {
  version: 1
  key: string
  seed: number
  payloadHash: string
  acceptedJobId?: string
}

export type ImageGenerationCommand = {
  ownerId: string
  key: string
  seed: number
  body: string
  acceptedJobId?: string
}

const replayBlocked = 'Предыдущий запуск ещё не подтверждён. Проверьте задания и повторите его с прежними параметрами, прежде чем начинать другую генерацию.'
const legacyBlocked = 'Обнаружен запрос предыдущей версии без подтверждённого владельца. Новый платный запуск заблокирован до проверки задания.'

function keyFor(scope: ImageCommandScope, ownerId: string): string {
  return `izo.image.pending.${scope}.v2.${encodeURIComponent(ownerId)}`
}

function legacyKeyFor(scope: ImageCommandScope): string {
  return `izo.image.pending.${scope}.v1`
}

/** Caller supplies canonical authV2.fetchMeV2: cookie-only with shared 401 refresh. */
export type VerifiedMeResolver = () => Promise<{ internal_user_id?: unknown } | null>

async function verifiedOwner(resolveMe: VerifiedMeResolver): Promise<string> {
  const value: unknown = await resolveMe()
  if (!value) throw new Error('Не удалось подтвердить аккаунт. Войдите снова, прежде чем запускать генерацию.')
  const owner = value && typeof value === 'object'
    ? (value as { internal_user_id?: unknown }).internal_user_id : undefined
  if (typeof owner !== 'string' || !owner || owner.length > 160 || owner.trim() !== owner || [...owner].some((ch) => ch.charCodeAt(0) < 32 || ch.charCodeAt(0) === 127)) {
    throw new Error('Сервер не подтвердил идентификатор аккаунта. Новый платный запуск заблокирован.')
  }
  return owner
}

function readPending(scope: ImageCommandScope, ownerId: string): PendingImageCommand | null {
  // A legacy v1 command cannot be attributed to A or B: do not silently discard or reassign it.
  if (sessionStorage.getItem(legacyKeyFor(scope)) !== null) throw new Error(legacyBlocked)
  const raw = sessionStorage.getItem(keyFor(scope, ownerId))
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

function writePending(scope: ImageCommandScope, ownerId: string, command: PendingImageCommand): void {
  sessionStorage.setItem(keyFor(scope, ownerId), JSON.stringify(command))
}

async function hashPayload(body: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(body))
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
}

export async function beginImageGenerationCommand(
  scope: ImageCommandScope,
  draft: Record<string, unknown>,
  resolveMe: VerifiedMeResolver,
  requestedSeed?: number,
): Promise<ImageGenerationCommand> {
  const ownerId = await verifiedOwner(resolveMe)
  const previous = readPending(scope, ownerId)
  const key = previous?.key ?? crypto.randomUUID()
  const freshSeed = crypto.getRandomValues(new Uint32Array(1))[0] % 2147483646 + 1
  const seed = previous?.seed ?? (
    Number.isSafeInteger(requestedSeed) && Number(requestedSeed) >= 1 && Number(requestedSeed) <= 2147483646
      ? Number(requestedSeed) : freshSeed
  )
  // Persist before hashing or I/O: an unknown acceptance must retain its key on F5.
  if (!previous) writePending(scope, ownerId, { version: 1, key, seed, payloadHash: '' })
  const body = JSON.stringify({ ...draft, seed, clientRequestId: key })
  const payloadHash = await hashPayload(body)
  const current = readPending(scope, ownerId)
  if (!current || current.key !== key || (current.payloadHash && current.payloadHash !== payloadHash)) {
    throw new Error(replayBlocked)
  }
  if (!current.payloadHash) writePending(scope, ownerId, { ...current, payloadHash })
  return { ownerId, key, seed, body, acceptedJobId: current.acceptedJobId }
}

export function acknowledgeImageGenerationCommand(scope: ImageCommandScope, ownerId: string, key: string, jobId: string): void {
  if (!/^[a-zA-Z0-9_-]{1,160}$/.test(jobId)) throw new Error('Сервер вернул некорректный идентификатор задания.')
  const pending = readPending(scope, ownerId)
  if (pending?.key === key) writePending(scope, ownerId, { ...pending, acceptedJobId: jobId })
}

export async function getAcceptedImageGenerationJob(scope: ImageCommandScope, resolveMe: VerifiedMeResolver): Promise<string | null> {
  const ownerId = await verifiedOwner(resolveMe)
  return readPending(scope, ownerId)?.acceptedJobId || null
}

export async function completeImageGenerationCommand(scope: ImageCommandScope, jobId: string, resolveMe: VerifiedMeResolver): Promise<void> {
  const ownerId = await verifiedOwner(resolveMe)
  const pending = readPending(scope, ownerId)
  if (pending?.acceptedJobId === jobId) sessionStorage.removeItem(keyFor(scope, ownerId))
}

export function rejectImageGenerationCommand(scope: ImageCommandScope, ownerId: string, key: string, status: number): void {
  // 401/403 can reflect an account switch; unknown outcome and rate limits must never release the key.
  if ([400, 402, 422].includes(status)) {
    const pending = readPending(scope, ownerId)
    if (pending?.key === key && !pending.acceptedJobId) sessionStorage.removeItem(keyFor(scope, ownerId))
  }
}
