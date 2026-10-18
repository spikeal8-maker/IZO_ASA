import test from 'node:test'
import assert from 'node:assert/strict'
import { snapshot, settlement, completedProjection, decodedImage, publicationFor, poll } from './docker_d3_browser_contracts.mjs'

function example(provider = 'comfyui', balance = 0) {
  const mode = provider === 'comfyui' ? 'text_to_image' : 'text_to_video'
  const daily = 2 - balance
  const me = { legacy_user_id: 'web_owned', internal_user_id: 'owned', account: { token_balance: 100, daily_tokens_used: 4 } }
  const history = { summary: { spentTokens: 4, balanceSpentTokens: 0, includedSpentTokens: 4, refundedTokens: 0, balance: 100 },
    items: [{ id: 'previous…', jobId: 'old_job', delta: 0, spentTokens: 4, reason: 'daily_generation', provider: 'comfyui', mode: 'edit' }] }
  const before = snapshot(me, history)
  me.account.token_balance -= balance; me.account.daily_tokens_used += daily
  history.summary.spentTokens += 2; history.summary.balanceSpentTokens += balance
  history.summary.includedSpentTokens += daily; history.summary.balance -= balance
  const admission = { id: 'job_123456789abcdef', mode, provider, tokenCost: 2, tokenBalance: 100 - balance,
    dailyTokensUsed: 4 + daily, dailyTokenPart: daily, mainBalanceTokenPart: balance }
  history.items.push({ id: 'charge…', jobId: 'job_123456…', delta: -balance, spentTokens: 2,
    reason: daily === 2 ? 'daily_generation' : 'generation', mode, provider })
  if (provider === 'comfyui') history.items.push({ id: 'free_chat…', jobId: null, delta: 0, spentTokens: 0,
    reason: 'free_chat', mode: 'phone_chat', provider: 'local' })
  return [before, snapshot(me, history), admission, { mode, provider, chatEntries: provider === 'comfyui' ? 1 : 0 }]
}

test('daily, main and mixed debits tie the actual balance, ledger, admission and job', () => {
  for (const provider of ['comfyui', 'local_ltx']) for (const balance of [0, 1, 2]) {
    const proof = settlement(...example(provider, balance))
    assert.equal(proof.mainBalanceDebit, balance)
    assert.equal(proof.dailyBudgetDebit, 2 - balance)
    assert.equal(proof.provider, provider)
  }
})

test('coherent totals cannot conceal the wrong charge or absent account debit', () => {
  const faults = [
    (v) => { v[1].ledger.items.find((i) => i.id === 'charge…').jobId = 'foreign_job' },
    (v) => { v[1].ledger.items.find((i) => i.id === 'charge…').mode = 'edit' },
    (v) => { v[1].ledger.items.find((i) => i.id === 'charge…').provider = 'openrouter' },
    (v) => { v[1].account.daily_tokens_used = v[0].account.daily_tokens_used },
    (v) => { v[1].ledger.items.find((i) => i.id === 'charge…').reason = 'daily_generation_refund' },
    (v) => { v[1].ledger.items.push({ ...v[1].ledger.items[0], id: 'extra_charge' }) },
    (v) => { v[1].ledger.items.find((i) => i.id === 'previous…').delta = -1 },
    (v) => { v[1].ledger.items = v[1].ledger.items.filter((i) => i.id !== 'previous…') },
    (v) => { v[1].identity[0] = 'web_foreign' },
    (v) => { v[2].tokenBalance = 99 },
    (v) => { v[2].dailyTokenPart = 1 },
    (v) => { v[2].mainBalanceTokenPart = 1 },
    (v) => { v[2].dailyTokensUsed = 5 },
    (v) => { v[1].ledger.summary.refundedTokens = 1 },
    (v) => { v[1].ledger.summary.includedSpentTokens = 5 },
    (v) => { v[1].ledger.items.find((i) => i.id === 'free_chat…').delta = -1 },
    (v) => { v[1].ledger.items.push({ ...v[1].ledger.items.find((i) => i.id === 'free_chat…'), id: 'extra_chat' }) },
  ]
  for (const fault of faults) { const value = example(); fault(value); assert.throws(() => settlement(...value), /D3_/) }
})

test('snapshot rejects truncation, duplicate public IDs and noninteger accounting', () => {
  const me = { legacy_user_id: 'web_owned', internal_user_id: 'owned', account: { token_balance: 1, daily_tokens_used: 0 } }
  const h = { summary: { spentTokens: 0, balanceSpentTokens: 0, includedSpentTokens: 0, refundedTokens: 0, balance: 1 }, items: [] }
  assert.equal(snapshot(me, h).ledger.items.length, 0)
  for (const mutate of [
    (v) => { v.summary.balance = 2 },
    (v) => { v.summary.spentTokens = '0' },
    (v) => { v.items = Array(200).fill({ id: 'same', delta: 0, spentTokens: 0 }) },
    (v) => { v.items = Array(2).fill({ id: 'same', delta: 0, spentTokens: 0 }) },
  ]) { const value = structuredClone(h); mutate(value); assert.throws(() => snapshot(me, value), /D3_/) }
})

test('a late completed response fails the same deadline as a late pending response', async () => {
  for (const state of ['completed', 'running']) {
    let clock = 0
    await assert.rejects(poll(async () => { clock = 1000; return state }, (v) => v === 'completed', () => true, 1,
      { now: () => clock, wait: async () => {} }), /D3_POLL_TIMEOUT/)
  }
  let clock = 0, reads = 0
  assert.equal(await poll(async () => ++reads === 2 ? 'completed' : 'running', (v) => v === 'completed',
    (v) => v === 'running', 1, { now: () => clock, wait: async (ms) => { clock += ms } }), 'completed')
  await assert.rejects(poll(async () => 'failed', () => false, (v) => v === 'running'), /D3_TERMINAL/)
})

test('the public ten-character prefix explicitly cannot prove full-job ledger linkage', () => {
  const value = example()
  value[2].id = 'job_123456_OTHER_FULL_JOB'
  const proof = settlement(...value)
  assert.equal(proof.status, 'PASS')
  assert.equal(proof.publicJobId, 'job_123456…')
  assert.equal(proof.fullJobLedgerLinkage, 'NOT_VERIFIED')
})

function projection(modality = 'image') {
  const id = modality === 'image' ? 'job_request_owned' : 'video_20261018_owned'
  const mode = modality === 'image' ? 'text_to_image' : 'text_to_video'
  const legacy = { id, mode, status: 'completed', progress: 100, tokenCost: 2,
    createdAt: '2026-10-18T12:00:00+00:00', completedAt: '2026-10-18T12:00:03+00:00' }
  const result = modality === 'image'
    ? { id: 'image_owned', type: 'image', url: '/api/media/owned.png?userId=web_owned', thumbnailUrl: null,
      width: 1024, height: 1024, durationSeconds: null, aspectRatio: null }
    : { id: `gallery_${id}`, type: 'video', url: `/api/video/media/${id}`, thumbnailUrl: null,
      width: null, height: null, durationSeconds: 2, aspectRatio: '16:9' }
  if (modality === 'image') Object.assign(legacy, { provider: 'comfyui', userId: 'web_owned',
    resultImageId: result.id, resultUrl: result.url, width: 1024, height: 1024 })
  else Object.assign(legacy, { galleryVideoId: result.id, videoUrl: result.url, model: 'local/ltx-2.3-fast-q3',
    duration: 2, resolution: '480p', aspectRatio: '16:9', generateAudio: false, galleryDeleted: false })
  const envelope = { ok: true, job: { id, operation: mode, modality, status: 'completed', phase: 'terminal',
    progress: 100, terminal: true, result, createdAt: legacy.createdAt, completedAt: legacy.completedAt,
    billing: { chargedTokens: 2, refunded: false, tokenKind: null } } }
  return [legacy, envelope, { id, tokenCost: 2 }, { modality, ownerId: 'web_owned' }]
}

test('completed image/video projections retain exact IDs, assets, fields and billing', () => {
  for (const modality of ['image', 'video']) {
    const values = projection(modality), proof = completedProjection(...values)
    assert.equal(proof.jobId, values[2].id)
    assert.equal(proof.resultId, values[1].job.result.id)
    assert.equal(proof.chargedTokens, 2)
    assert.equal(proof.modality, modality)
  }
})

test('completed labels cannot hide foreign jobs, assets, owners or malformed Phone projections', () => {
  const common = [
    (v) => { v[0].id = 'different_full_job' },
    (v) => { v[0].mode = 'edit' },
    (v) => { v[0].progress = 99 },
    (v) => { v[0].tokenCost = 3 },
    (v) => { v[0].error = 'untrusted private error' },
    (v) => { v[1].ok = false },
    (v) => { v[1].job.id = 'foreign_job' },
    (v) => { v[1].job.operation = 'edit' },
    (v) => { v[1].job.modality = 'audio' },
    (v) => { v[1].job.phase = 'running' },
    (v) => { v[1].job.progress = '100' },
    (v) => { v[1].job.terminal = false },
    (v) => { v[1].job.completedAt = '2026-10-18T12:00:04+00:00' },
    (v) => { v[1].job.billing.chargedTokens = 1 },
    (v) => { v[1].job.billing.refunded = true },
    (v) => { v[1].job.result = null },
    (v) => { v[1].job.result.id = 'foreign_asset' },
    (v) => { v[1].job.result.url = '/api/media/foreign.png' },
    (v) => { v[1].job.result.type = 'audio' },
    (v) => { v[1].job.result.width = 200 },
    (v) => { delete v[1].job.result.aspectRatio },
  ]
  for (const modality of ['image', 'video']) for (const fault of common) {
    const values = projection(modality); fault(values)
    assert.throws(() => completedProjection(...values), /D3_(LEGACY|PHONE)_/)
  }
  for (const fault of [
    (v) => { v[0].provider = 'openrouter' },
    (v) => { v[0].userId = 'web_foreign' },
    (v) => { v[0].resultUrl = '/api/media/owned.png?userId=web_foreign' },
    (v) => { v[0].resultUrl = 'https://untrusted.invalid/owned.png' },
    (v) => { v[0].resultUrl = '/api/media/../owned.png' },
    (v) => { v[0].thumbnailUrl = '/api/media/owned.png?userId=web_foreign' },
    (v) => { v[0].width = 0 },
  ]) { const values = projection(); fault(values); assert.throws(() => completedProjection(...values), /D3_(IMAGE|LEGACY)_/) }
  for (const fault of [
    (v) => { v[0].galleryVideoId = 'gallery_foreign' },
    (v) => { v[0].videoUrl = '/api/video/media/video_foreign' },
    (v) => { v[0].model = 'another_model' },
    (v) => { v[0].duration = 4 },
    (v) => { v[0].galleryDeleted = true },
    (v) => { v[0].generateAudio = true },
  ]) { const values = projection('video'); fault(values); assert.throws(() => completedProjection(...values), /D3_LEGACY_VIDEO_/) }
})

test('a visible image with unchanged src must still decode after reload', () => {
  const url = '/api/media/owned.png?userId=web_owned'
  const loaded = { complete: true, src: url, width: 256, height: 256 }
  assert.deepEqual(decodedImage(loaded, url, { width: 256, height: 256 }), { width: 256, height: 256 })
  for (const value of [{ ...loaded, width: 0 }, { ...loaded, height: 0 }, { ...loaded, complete: false },
    { ...loaded, src: '/api/media/foreign.png' }, { ...loaded, width: 512 }]) {
    assert.throws(() => decodedImage(value, url, { width: 256, height: 256 }), /D3_CHAT_IMAGE_NOT_DECODED/)
  }
})

test('a ready publication cannot belong to another source video or another publication', () => {
  const value = { ok: true, publication: { id: 'owned_publication', video_id: 'gallery_video_owned', image_id: null,
    media_type: 'video', status: 'published', media_status: 'ready' } }
  assert.equal(publicationFor(value, 'gallery_video_owned', 'owned_publication').status, 'published')
  for (const mutate of [
    (v) => { v.publication.id = 'different_publication' },
    (v) => { v.publication.video_id = 'gallery_video_foreign' },
    (v) => { v.publication.image_id = 'image_foreign' },
    (v) => { v.publication.media_type = 'image' },
    (v) => { v.publication.media_error = '/private/provider/error' },
  ]) { const copy = structuredClone(value); mutate(copy); assert.throws(() => publicationFor(copy,
    'gallery_video_owned', 'owned_publication'), /D3_PUBLICATION_IDENTITY_MISMATCH/) }
})
