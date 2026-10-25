/** Non-financial phone UI draft state, isolated by server-confirmed internal_user_id.
 * Legacy unowned v1 keys are intentionally never read or migrated.
 */
export type PhoneDraftKind = 'image.prompt' | 'video.prompt' | 'video.source'

function verifiedOwnerKey(ownerId: string): string {
  if (typeof ownerId !== 'string' || ownerId.length === 0 || ownerId.length > 160
    || ownerId.trim() !== ownerId || /[\u0000-\u001f\u007f]/.test(ownerId)) {
    throw new Error('Не удалось подтвердить владельца мобильного черновика.')
  }
  return encodeURIComponent(ownerId)
}

export function phoneDraftKey(kind: PhoneDraftKind, ownerId: string): string {
  return `izo.phone.draft.v2.${verifiedOwnerKey(ownerId)}.${kind}`
}

export function readPhoneDraft(kind: PhoneDraftKind, ownerId: string): string {
  const key = phoneDraftKey(kind, ownerId)
  try {
    return sessionStorage.getItem(key) || ''
  } catch {
    return ''
  }
}

export function writePhoneDraft(kind: PhoneDraftKind, ownerId: string, value: string): void {
  const key = phoneDraftKey(kind, ownerId)
  try {
    if (!value) sessionStorage.removeItem(key)
    else sessionStorage.setItem(key, value)
  } catch {
    // A disabled or full sessionStorage must not expose drafts to another owner.
    // Video hand-off will simply be unavailable on the next route.
  }
}
