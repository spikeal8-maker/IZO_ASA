// STUDIO-DRAFT-OPT-001: a single session-scoped persistence boundary for Studio.
// Never persist credentials, raw media bytes or an untrusted account identifier.
import type { AuthStatusV2 } from '../authV2'
import type { StudioDraft, StudioMode } from './studioTypes'

export const STUDIO_DRAFT_KEY = 'izo:studio-draft-v2'
export const STUDIO_DRAFT_TTL_MS = 24 * 60 * 60 * 1000
export type StudioDraftScope = 'guest' | `user:${string}`

const MODES: readonly StudioMode[] = ['text', 'i2i', 'edit', 'paint']

export function studioDraftScope(status: AuthStatusV2, internalUserId?: string | null): StudioDraftScope | null {
  if (status === 'anon') return 'guest'
  if (status !== 'authed' || typeof internalUserId !== 'string') return null
  const id = internalUserId.trim()
  return /^[a-zA-Z0-9_-]{1,128}$/.test(id) ? `user:${id}` : null
}

export function studioDraftKey(scope: StudioDraftScope): string {
  return `${STUDIO_DRAFT_KEY}:${scope}`
}

function stripInlineMedia(value: unknown): string | undefined {
  return typeof value === 'string' && value && !/^data:/i.test(value) ? value : undefined
}

function cleanDraft(input: unknown): StudioDraft {
  if (!input || typeof input !== 'object' || Array.isArray(input)) return {}
  const value = input as StudioDraft
  const prompts: NonNullable<StudioDraft['prompts']> = {}
  for (const mode of MODES) {
    if (typeof value.prompts?.[mode] === 'string') prompts[mode] = value.prompts[mode]
  }
  return {
    prompts,
    styleId: typeof value.styleId === 'string' ? value.styleId : undefined,
    resolutionId: typeof value.resolutionId === 'string' ? value.resolutionId : undefined,
    quality: typeof value.quality === 'string' ? value.quality : undefined,
    seed: typeof value.seed === 'number' && Number.isFinite(value.seed) ? value.seed : undefined,
    strengthPct: typeof value.strengthPct === 'number' && Number.isFinite(value.strengthPct) ? value.strengthPct : undefined,
    sourceImage: stripInlineMedia(value.sourceImage),
    editSlots: Array.isArray(value.editSlots)
      ? value.editSlots.map((slot) => ({
          role: typeof slot?.role === 'string' ? slot.role : '',
          takeNote: typeof slot?.takeNote === 'string' ? slot.takeNote : '',
          image: stripInlineMedia(slot?.image),
        })) as StudioDraft['editSlots']
      : undefined,
    editFaceStrengthPct: typeof value.editFaceStrengthPct === 'number' && Number.isFinite(value.editFaceStrengthPct)
      ? value.editFaceStrengthPct
      : undefined,
  }
}

export function readStudioDraft(scope: StudioDraftScope): StudioDraft {
  try {
    const raw = window.sessionStorage.getItem(studioDraftKey(scope))
    if (!raw) return {}
    const record = JSON.parse(raw) as { version?: number; savedAt?: number; draft?: unknown }
    const now = Date.now()
    if (record?.version !== 2 || typeof record.savedAt !== 'number' ||
        !Number.isFinite(record.savedAt) || record.savedAt > now ||
        now - record.savedAt > STUDIO_DRAFT_TTL_MS) return {}
    return cleanDraft(record.draft)
  } catch {
    // Browser storage can be blocked/corrupt; never prevent normal Studio use.
    return {}
  }
}

export function writeStudioDraft(scope: StudioDraftScope, draft: StudioDraft): void {
  try {
    window.sessionStorage.setItem(studioDraftKey(scope), JSON.stringify({
      version: 2,
      savedAt: Date.now(),
      draft: cleanDraft(draft),
    }))
  } catch {
    // Storage-disabled/quota errors are non-fatal; in-memory composer still works.
  }
}

export function clearStudioDraft(scope: StudioDraftScope): void {
  try {
    window.sessionStorage.removeItem(studioDraftKey(scope))
  } catch {
    // Storage access is best-effort.
  }
}
