// Pure receipt checks for the installed browser; no network or product mutations.
export const ensure = (value, code) => { if (!value) throw new Error(code) }
const same = (left, right) => JSON.stringify(left) === JSON.stringify(right)
const fields = ['id', 'jobId', 'delta', 'spentTokens', 'reason', 'provider', 'mode', 'model', 'createdAt']
const totals = ['spentTokens', 'balanceSpentTokens', 'includedSpentTokens', 'refundedTokens', 'balance']

export function snapshot(me, history) {
  const identity = [me.legacy_user_id, me.internal_user_id]
  const account = { token_balance: me.account?.token_balance, daily_tokens_used: me.account?.daily_tokens_used }
  const summary = Object.fromEntries(totals.map((key) => [key, history.summary?.[key]]))
  ensure(identity.every((value) => typeof value === 'string' && value.length > 0)
    && [...Object.values(account), ...Object.values(summary)].every(Number.isSafeInteger)
    && summary.balance === account.token_balance && Array.isArray(history.items) && history.items.length < 200,
  'D3_ACCOUNT_SNAPSHOT_INVALID')
  const items = history.items.map((item) => Object.fromEntries(fields.map((key) => [key, item[key] ?? null])))
  ensure(items.every((item) => typeof item.id === 'string' && /^[A-Za-z0-9_-]{1,120}…?$/.test(item.id)
    && Number.isSafeInteger(item.delta) && Number.isSafeInteger(item.spentTokens) && item.spentTokens >= 0),
  'D3_LEDGER_SNAPSHOT_INVALID')
  items.sort((a, b) => a.id.localeCompare(b.id))
  ensure(new Set(items.map((item) => item.id)).size === items.length, 'D3_LEDGER_IDS_NOT_UNIQUE')
  return { identity, account, ledger: { summary, items } }
}

export function settlement(before, after, admission, { mode, provider, chatEntries = 0 }) {
  const cost = admission.tokenCost, jobId = admission.id
  ensure(Number.isSafeInteger(cost) && cost > 0 && typeof jobId === 'string'
    && /^[A-Za-z0-9_-]{1,120}$/.test(jobId)
    && ((mode === 'text_to_image' && provider === 'comfyui' && chatEntries === 1)
      || (mode === 'text_to_video' && provider === 'local_ltx' && chatEntries === 0)), 'D3_SETTLEMENT_INPUT_INVALID')
  const previous = new Map(before.ledger.items.map((item) => [item.id, item]))
  const current = new Map(after.ledger.items.map((item) => [item.id, item]))
  ensure(previous.size === before.ledger.items.length && current.size === after.ledger.items.length
    && same(before.identity, after.identity)
    && [...previous].every(([key, item]) => current.has(key) && same(current.get(key), item)),
  'D3_LEDGER_BASELINE_CHANGED')
  const added = [...current.values()].filter((item) => !previous.has(item.id))
  const free = added.filter((item) => item.reason === 'free_chat' && item.mode === 'phone_chat'
    && item.provider === 'local' && item.delta === 0 && item.spentTokens === 0 && item.jobId === null)
  const charges = added.filter((item) => item.spentTokens === cost && Number.isSafeInteger(item.spentTokens))
  ensure(free.length === chatEntries && charges.length === 1 && added.length === chatEntries + 1,
    'D3_SINGLE_CHARGE_NOT_PROVEN')
  const charge = charges[0], publicId = jobId.slice(0, 10) + (jobId.length > 10 ? '…' : '')
  ensure(charge.jobId === publicId && charge.mode === mode && charge.provider === provider,
    'D3_CHARGE_PROVENANCE_INVALID')
  const left = before.ledger.summary, right = after.ledger.summary
  const balance = before.account.token_balance - after.account.token_balance
  const daily = after.account.daily_tokens_used - before.account.daily_tokens_used
  ensure([...Object.values(before.account), ...Object.values(after.account), ...Object.values(left),
    ...Object.values(right), charge.delta, admission.tokenBalance].every(Number.isSafeInteger)
    && balance >= 0 && daily >= 0 && balance + daily === cost
    && charge.delta === -balance && charge.reason === (daily === cost ? 'daily_generation' : 'generation')
    && after.account.token_balance === admission.tokenBalance
    && left.balance === before.account.token_balance && right.balance === after.account.token_balance
    && right.spentTokens - left.spentTokens === cost && right.refundedTokens === left.refundedTokens
    && right.balanceSpentTokens - left.balanceSpentTokens === balance
    && right.includedSpentTokens - left.includedSpentTokens === daily, 'D3_ACCOUNT_DEBIT_MISMATCH')
  if (provider === 'comfyui') ensure(admission.mode === mode && admission.provider === provider
    && Number.isSafeInteger(admission.dailyTokensUsed) && admission.dailyTokensUsed === after.account.daily_tokens_used
    && Number.isSafeInteger(admission.mainBalanceTokenPart) && admission.mainBalanceTokenPart === balance
    && Number.isSafeInteger(admission.dailyTokenPart) && admission.dailyTokenPart === daily,
  'D3_IMAGE_ADMISSION_DEBIT_MISMATCH')
  return { status: 'PASS', ledgerId: charge.id, publicJobId: publicId, mode, provider,
    tokenCost: cost, mainBalanceDebit: balance, dailyBudgetDebit: daily, refundDelta: 0,
    zeroTokenChatEntries: free.length, previousLedgerRowsUnchanged: previous.size,
    fullJobLedgerLinkage: 'NOT_VERIFIED' } // Public IDs are truncated; a private full-ID receipt must prove linkage.
}

const validId = (value) => typeof value === 'string' && /^[A-Za-z0-9_-]{1,120}$/.test(value)
const date = (value) => typeof value === 'string' && value.length <= 80 && Number.isFinite(Date.parse(value))
const dimension = (value) => Number.isSafeInteger(value) && value > 0 && value <= 8192

export function imageURL(value, ownerId) {
  ensure(typeof value === 'string' && /^\/api\/media\/[A-Za-z0-9_-]+\.(png|webp|jpe?g)(\?userId=[A-Za-z0-9_-]+)?$/.test(value)
    && (!value.includes('?') || value.endsWith(`?userId=${ownerId}`)), 'D3_IMAGE_URL_NOT_OWNED')
  return value
}

export function completedProjection(legacy, envelope, admission, { modality, ownerId }) {
  const mode = modality === 'image' ? 'text_to_image' : 'text_to_video'
  ensure(['image', 'video'].includes(modality) && validId(admission?.id)
    && Number.isSafeInteger(admission.tokenCost) && admission.tokenCost > 0, 'D3_PROJECTION_INPUT_INVALID')
  ensure(legacy?.id === admission.id && legacy.mode === mode && legacy.status === 'completed'
    && legacy.progress === 100 && legacy.tokenCost === admission.tokenCost && !legacy.error
    && date(legacy.createdAt) && date(legacy.completedAt), 'D3_LEGACY_JOB_MISMATCH')
  let assetId, url
  if (modality === 'image') {
    ensure(legacy.provider === 'comfyui' && legacy.userId === ownerId && validId(legacy.resultImageId)
      && dimension(legacy.width) && dimension(legacy.height), 'D3_LEGACY_IMAGE_MISMATCH')
    assetId = legacy.resultImageId; url = imageURL(legacy.resultUrl, ownerId)
    if (legacy.thumbnailUrl) imageURL(legacy.thumbnailUrl, ownerId)
  } else {
    ensure(legacy.galleryVideoId === `gallery_${admission.id}` && validId(legacy.galleryVideoId)
      && legacy.videoUrl === `/api/video/media/${admission.id}` && legacy.model === 'local/ltx-2.3-fast-q3'
      && legacy.duration === 2 && legacy.resolution === '480p' && legacy.aspectRatio === '16:9'
      && legacy.generateAudio === false && legacy.galleryDeleted === false, 'D3_LEGACY_VIDEO_MISMATCH')
    assetId = legacy.galleryVideoId; url = legacy.videoUrl
  }
  const phone = envelope?.job
  ensure(envelope?.ok === true && phone?.id === admission.id && phone.operation === mode && phone.modality === modality
    && phone.status === 'completed' && phone.phase === 'terminal' && phone.progress === 100 && phone.terminal === true
    && phone.createdAt === legacy.createdAt && phone.completedAt === legacy.completedAt
    && phone.billing?.chargedTokens === admission.tokenCost && phone.billing.refunded === false
    && (phone.billing.tokenKind ?? null) === (legacy.tokenKind ?? null), 'D3_PHONE_JOB_MISMATCH')
  const expected = { id: assetId, type: modality, url, thumbnailUrl: legacy.thumbnailUrl || legacy.posterUrl || null,
    width: legacy.width ?? null, height: legacy.height ?? null, durationSeconds: legacy.duration || legacy.durationSeconds || null,
    aspectRatio: legacy.aspectRatio ?? null }
  ensure(phone.result && Object.entries(expected).every(([key, value]) => phone.result[key] === value),
    'D3_PHONE_RESULT_MISMATCH')
  return { status: 'PASS', jobId: admission.id, modality, operation: mode, phase: 'terminal', progress: 100,
    resultId: assetId, resultType: modality, chargedTokens: admission.tokenCost, refunded: false }
}

export function decodedImage(value, url, before = null) {
  ensure(value?.complete === true && value.src === url && dimension(value.width) && dimension(value.height)
    && (!before || (value.width === before.width && value.height === before.height)), 'D3_CHAT_IMAGE_NOT_DECODED')
  return { width: value.width, height: value.height }
}

export function publicationFor(envelope, galleryId, publicationId = null) {
  const value = envelope?.publication
  ensure(envelope?.ok === true && validId(value?.id) && (!publicationId || value.id === publicationId)
    && value.video_id === galleryId && value.image_id === null && value.media_type === 'video'
    && ['preparing', 'published'].includes(value.status) && !value.media_error, 'D3_PUBLICATION_IDENTITY_MISMATCH')
  return value
}

export async function poll(read, ready, allowed, seconds = 20,
  { now = () => performance.now(), wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms)) } = {}) {
  ensure(Number.isFinite(seconds) && seconds > 0 && seconds <= 60, 'D3_POLL_BUDGET_INVALID')
  const deadline = now() + seconds * 1000
  while (true) {
    ensure(now() < deadline, 'D3_POLL_TIMEOUT')
    const value = await read()
    ensure(now() < deadline, 'D3_POLL_TIMEOUT')
    if (ready(value)) return value
    ensure(allowed(value), 'D3_TERMINAL_OR_CONTRACT_FAILURE')
    await wait(200)
  }
}
