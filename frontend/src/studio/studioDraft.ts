// ARCH-FE-STUDIO-001A: session-scoped studio draft persistence. This module
// owns serialization only and intentionally contains no rendering behavior.
import type { StudioDraft } from './studioTypes'

export const STUDIO_DRAFT_KEY = 'izo:studio-draft-v1'

export function readStudioDraft(): StudioDraft {
  try {
    const value = window.sessionStorage.getItem(STUDIO_DRAFT_KEY)
    return value ? JSON.parse(value) as StudioDraft : {}
  } catch {
    return {}
  }
}

export function writeStudioDraft(draft: StudioDraft): void {
  try {
    window.sessionStorage.setItem(STUDIO_DRAFT_KEY, JSON.stringify(draft))
  } catch {
    const lightweight = {
      ...draft,
      sourceImage: draft.sourceImage?.startsWith('data:') ? undefined : draft.sourceImage,
      editSlots: draft.editSlots?.map((slot) => ({
        ...slot,
        image: slot.image?.startsWith('data:') ? undefined : slot.image,
      })),
    }
    try {
      window.sessionStorage.setItem(STUDIO_DRAFT_KEY, JSON.stringify(lightweight))
    } catch {
      // Storage may be disabled; generation remains usable without recovery.
    }
  }
}
