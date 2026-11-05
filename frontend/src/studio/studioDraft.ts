// ARCH-FE-STUDIO-001A: session-scoped studio draft persistence. This module
// owns serialization only and intentionally contains no rendering behavior.
import type { StudioDraft } from './studioTypes'

export const STUDIO_DRAFT_KEY = 'izo:studio-draft-v1'

export type StudioDraftOwner = Readonly<{ owner: string; generation: number }>
export type StudioHandoffRequest = { source: 'gallery' | 'uploaded' | 'feed'; id: string; target: string }
let ownerResolver: () => StudioDraftOwner | null = () => null
let lastReadOwner: StudioDraftOwner | null = null
let preparedHandoff: { owner: StudioDraftOwner; raw: string } | null = null
let preparation: { owner: StudioDraftOwner; raw: string; promise: Promise<void> } | null = null

// The app supplies a read-only trusted-auth snapshot; this serializer stays
// independent of React and never treats a stored owner as authentication.
export function bindStudioDraftOwner(resolver: () => StudioDraftOwner | null): void {
  ownerResolver = resolver
  lastReadOwner = null
  preparedHandoff = null
  preparation = null
}

export function captureStudioDraftOwner(): StudioDraftOwner | null {
  try {
    const value = ownerResolver()
    return value && typeof value.owner === 'string' && value.owner.length > 0 && Number.isSafeInteger(value.generation) && value.generation >= 0
      ? { owner: value.owner, generation: value.generation }
      : null
  } catch {
    return null
  }
}

function isCurrentOwner(captured: StudioDraftOwner | null): captured is StudioDraftOwner {
  const current = captureStudioDraftOwner()
  return !!captured && current?.owner === captured.owner && current.generation === captured.generation
}

export function clearStudioPrivateHandoffs(): void {
  preparedHandoff = null
  preparation = null
  for (const key of ['izoUseAsDraft', 'izo:video-source-v1']) {
    try { window.sessionStorage.removeItem(key) } catch { /* storage is optional */ }
  }
}

function observeOwner(owner: StudioDraftOwner | null): void {
  if (lastReadOwner && (lastReadOwner.owner !== owner?.owner || lastReadOwner.generation !== owner?.generation)) clearStudioPrivateHandoffs()
  lastReadOwner = owner
}

function handoffRequest(raw: string): StudioHandoffRequest {
  const value = JSON.parse(raw) as Record<string, unknown>
  const fields = { gallery: 'imageId', uploaded: 'sourceId', feed: 'publicationId' } as const
  const source = value?.source as keyof typeof fields
  if (!Object.hasOwn(fields, source) || !['image', 'editor', 'draw', 'face_source', 'face_target', 'prompt'].includes(String(value.target))) throw new Error('Invalid handoff')
  const id = value[fields[source]]
  if (typeof id !== 'string' || !id.trim() || id.length > 256 || Object.values(fields).some((field) => field !== fields[source] && value[field] != null)) throw new Error('Ambiguous handoff')
  return { source, id, target: String(value.target) }
}

// App waits for this owner-bound preparation before mounting the consumer.
// StrictMode subscribers share one request; cached text/URLs are never reused.
export function prepareStudioHandoffs(owner: StudioDraftOwner, resolve: (request: StudioHandoffRequest, signal: AbortSignal) => Promise<unknown>): Promise<void> {
  if (!isCurrentOwner(owner)) return Promise.resolve()
  observeOwner(owner)
  let raw: string | null
  try { raw = window.sessionStorage.getItem('izoUseAsDraft') } catch { return Promise.resolve() }
  if (!raw) return Promise.resolve()
  if (preparedHandoff?.raw === raw && isCurrentOwner(preparedHandoff.owner)) return Promise.resolve()
  if (preparation?.raw === raw && isCurrentOwner(preparation.owner)) return preparation.promise
  const operation = { owner, raw, promise: Promise.resolve() }
  preparation = operation
  operation.promise = (async () => {
    const controller = new AbortController()
    let timeout: ReturnType<typeof setTimeout> | undefined
    try {
      const request = handoffRequest(raw)
      const deadline = new Promise<never>((_, reject) => { timeout = setTimeout(() => { controller.abort(); reject(new Error('Handoff timeout')) }, 8000) })
      const data = await Promise.race([resolve(request, controller.signal), deadline]) as Record<string, unknown>
      const idField = { gallery: 'imageId', uploaded: 'sourceId', feed: 'publicationId' }[request.source]
      if (!data || data.ok !== true || data[idField] !== request.id || data.target !== request.target) throw new Error('Invalid handoff response')
      if (data.prompt != null && typeof data.prompt !== 'string') throw new Error('Invalid handoff prompt')
      if (data.inputImage != null) {
        if (typeof data.inputImage !== 'string' || !data.inputImage.startsWith('/') || data.inputImage.startsWith('//') || data.inputImage.includes('\\')) throw new Error('Invalid handoff image')
        // The fresh use-as response supplies the authorized resource. Keep its
        // relative URL on the configured API origin; do not duplicate routes.
        if (new URL(data.inputImage, 'https://izo-internal.invalid').origin !== 'https://izo-internal.invalid') throw new Error('Invalid handoff image origin')
      } else if (request.target !== 'prompt') throw new Error('Missing handoff image')
      if (preparation !== operation || !isCurrentOwner(owner) || window.sessionStorage.getItem('izoUseAsDraft') !== raw) return
      const fresh = JSON.stringify({ ...data, source: request.source })
      window.sessionStorage.setItem('izoUseAsDraft', fresh)
      preparedHandoff = { owner, raw: fresh }
    } catch {
      try {
        if (preparation === operation && isCurrentOwner(owner) && window.sessionStorage.getItem('izoUseAsDraft') === raw) window.sessionStorage.removeItem('izoUseAsDraft')
      } catch { /* storage is optional */ }
    } finally {
      clearTimeout(timeout)
    }
  })()
  return operation.promise
}

function discardUnpreparedPrompt(): void {
  const raw = window.sessionStorage.getItem('izoUseAsDraft')
  if (!preparedHandoff || !isCurrentOwner(preparedHandoff.owner) || raw !== preparedHandoff.raw) window.sessionStorage.removeItem('izoUseAsDraft')
}

export function readStudioDraft(): StudioDraft {
  try {
    const owner = captureStudioDraftOwner()
    observeOwner(owner)
    // Only the exact freshly authorized payload may reach the legacy consumer.
    discardUnpreparedPrompt()
    const value = window.sessionStorage.getItem(STUDIO_DRAFT_KEY)
    if (!value) return {}
    const stored = JSON.parse(value) as StudioDraft & { _studioVersion?: number; _studioOwner?: string }
    if (!owner || !stored || stored._studioVersion !== 2 || stored._studioOwner !== owner.owner) {
      window.sessionStorage.removeItem(STUDIO_DRAFT_KEY)
      return {}
    }
    const { _studioVersion, _studioOwner, ...draft } = stored
    void _studioVersion
    void _studioOwner
    return draft
  } catch {
    try { discardUnpreparedPrompt() } catch { /* storage is optional */ }
    return {}
  }
}

export function writeStudioDraft(draft: StudioDraft, owner = captureStudioDraftOwner()): void {
  if (!isCurrentOwner(owner)) return
  const stored = { ...draft, _studioVersion: 2, _studioOwner: owner.owner }
  try {
    window.sessionStorage.setItem(STUDIO_DRAFT_KEY, JSON.stringify(stored))
  } catch {
    const lightweight = {
      ...stored,
      sourceImage: draft.sourceImage?.startsWith('data:') ? undefined : draft.sourceImage,
      editSlots: draft.editSlots?.map((slot) => ({
        ...slot,
        image: slot.image?.startsWith('data:') ? undefined : slot.image,
      })),
    }
    try {
      if (isCurrentOwner(owner)) window.sessionStorage.setItem(STUDIO_DRAFT_KEY, JSON.stringify(lightweight))
    } catch {
      // Storage may be disabled; generation remains usable without recovery.
    }
  }
}
