import assert from 'node:assert/strict'
import test from 'node:test'

import { phoneBillingLabel, phoneTokenClass } from './src/phone/core/billing.ts'
import { isPhoneJob, waitForPhoneJob, type PhoneJob } from './src/phone/core/jobs.ts'
import { isSafePhoneMediaUrl, phoneMediaAspect, phoneMediaFit } from './src/phone/core/media.ts'


const job = (status: PhoneJob['status'], progress: number): PhoneJob => ({
  id: 'job-1', modality: 'image', operation: 'text_to_image', status,
  phase: status === 'completed' ? 'terminal' : 'running', progress, message: '',
  createdAt: null, startedAt: null, completedAt: null,
  terminal: status === 'completed', result: null,
  billing: { chargedTokens: 1, tokenKind: 'daily', refunded: false },
})


test('validates normalized jobs and rejects impossible progress', () => {
  assert.equal(isPhoneJob(job('running', 50)), true)
  assert.equal(isPhoneJob({ ...job('running', 50), progress: 101 }), false)
  assert.equal(isPhoneJob({ ...job('running', 50), modality: 'provider-name' }), false)
})


test('polls until terminal without creating a duplicate job', async () => {
  const snapshots = [job('queued', 4), job('running', 55), job('completed', 100)]
  const seen: number[] = []
  const result = await waitForPhoneJob('job-1', {
    intervalMs: 250,
    read: async () => snapshots.shift() || job('completed', 100),
    onChange: (value) => seen.push(value.progress),
  })
  assert.equal(result.status, 'completed')
  assert.deepEqual(seen, [4, 55, 100])
})


test('keeps media private and preserves real aspect ratio', () => {
  const asset = { id: 'image-1', type: 'image' as const, url: '/api/media/a.webp', thumbnailUrl: null, width: 1080, height: 1920, durationSeconds: null, aspectRatio: '9:16' }
  assert.equal(isSafePhoneMediaUrl(asset.url), true)
  assert.equal(isSafePhoneMediaUrl('https://provider.invalid/private-file'), false)
  assert.equal(phoneMediaAspect(asset), 1080 / 1920)
  assert.equal(phoneMediaFit(asset), 'contain')
})


test('keeps daily and main token visuals distinct', () => {
  assert.equal(phoneTokenClass('daily'), 'phone-token phone-token--daily')
  assert.equal(phoneTokenClass('main'), 'phone-token phone-token--main')
  assert.equal(phoneBillingLabel({ tokens: 3.1, tokenKind: 'main', label: '' }), '4 ток. · основные')
})
