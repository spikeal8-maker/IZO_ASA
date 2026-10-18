import assert from 'node:assert/strict'
import { getEventListeners } from 'node:events'
import test from 'node:test'

import { waitForPhoneJob, type PhoneJob } from './src/phone/core/jobs.ts'
import { startPhoneImage } from './src/phone/features/image/api.ts'
import { startPhoneVideo } from './src/phone/features/video/api.ts'

const job = (status: PhoneJob['status'] = 'completed', modality: 'image' | 'video' = 'image'): PhoneJob => ({
  id: `${modality}-owned`, modality, operation: modality === 'image' ? 'text_to_image' : 'text_to_video',
  status, phase: status === 'completed' ? 'terminal' : 'running', progress: status === 'completed' ? 100 : 42,
  message: '', createdAt: null, startedAt: null, completedAt: null,
  terminal: ['completed', 'cancelled', 'failed', 'expired'].includes(status),
  result: status === 'completed' ? { id: `${modality}-result`, type: modality,
    url: '/api/media/owned.png', thumbnailUrl: null, width: 16, height: 16,
    durationSeconds: null, aspectRatio: '1:1' } : null,
  billing: { chargedTokens: 1, tokenKind: 'daily', refunded: status === 'cancelled' },
})

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

test('an aborted deferred terminal read cannot notify or complete', async () => {
  const controller = new AbortController(), response = deferred<PhoneJob>(), seen: PhoneJob[] = []
  const pending = waitForPhoneJob('image-owned', { signal: controller.signal,
    read: () => response.promise, onChange: (value) => seen.push(value) })
  controller.abort()
  response.resolve(job()) // A mocked/late transport may resolve even after abort.
  await assert.rejects(pending, { name: 'AbortError' })
  assert.deepEqual(seen, [])
  assert.equal(getEventListeners(controller.signal, 'abort').length, 0)
})

test('old deferred response cannot change the next observer', async () => {
  const old = new AbortController(), response = deferred<PhoneJob>(), seen: string[] = []
  const first = waitForPhoneJob('image-old', { signal: old.signal, read: () => response.promise,
    onChange: (value) => seen.push(value.id) })
  old.abort()
  const second = await waitForPhoneJob('image-new', { read: async () => ({ ...job(), id: 'image-new' }),
    onChange: (value) => seen.push(value.id) })
  response.resolve({ ...job(), id: 'image-old' })
  await assert.rejects(first, { name: 'AbortError' })
  assert.equal(second.id, 'image-new')
  assert.deepEqual(seen, ['image-new'])
})

test('abort from the observer cannot be returned as a completed operation', async () => {
  const controller = new AbortController()
  await assert.rejects(waitForPhoneJob('image-owned', { signal: controller.signal,
    read: async () => job(), onChange: () => controller.abort() }), { name: 'AbortError' })
})

test('normal interval completion removes abort listeners', async () => {
  const controller = new AbortController(), values = [job('queued'), job('running'), job()]
  const seen: string[] = []
  const result = await waitForPhoneJob('image-owned', { signal: controller.signal, intervalMs: 250,
    read: async () => values.shift()!, onChange: (value) => seen.push(value.status) })
  assert.equal(result.status, 'completed')
  assert.deepEqual(seen, ['queued', 'running', 'completed'])
  assert.equal(getEventListeners(controller.signal, 'abort').length, 0)
})

test('abort during the interval stops further reads and removes its listener', async () => {
  const controller = new AbortController(), first = deferred<void>()
  let reads = 0
  const pending = waitForPhoneJob('image-owned', { signal: controller.signal, intervalMs: 10_000,
    read: async () => { reads += 1; return job('queued') }, onChange: () => first.resolve() })
  await first.promise
  controller.abort()
  await assert.rejects(pending, { name: 'AbortError' })
  assert.equal(reads, 1)
  assert.equal(getEventListeners(controller.signal, 'abort').length, 0)
})

test('a signal aborted before observation performs no read', async () => {
  const controller = new AbortController()
  controller.abort()
  let reads = 0
  await assert.rejects(waitForPhoneJob('image-owned', { signal: controller.signal,
    read: async () => { reads += 1; return job() } }), { name: 'AbortError' })
  assert.equal(reads, 0)
})

const imageInput = {
  mode: 'text_to_image' as const, prompt: 'owned synthetic scene',
  model: { id: 'server:local_flux_klein', label: 'Flux2', provider: 'comfyui' as const,
    modelProfile: 'local_flux_klein', tokenHint: 1, supportedResolutionIds: ['sq-hd'] },
  resolutionId: 'sq-hd', width: 1024, height: 1024, inputImages: [],
}
const videoInput = {
  mode: 'text_to_video' as const, model: 'local/ltx-2.3-fast-q3', prompt: 'owned synthetic scene',
  duration: 4, resolution: '480p', aspectRatio: '16:9', generateAudio: false,
}

for (const modality of ['image', 'video'] as const) {
  const start = (onChange: (value: PhoneJob) => void, signal: AbortSignal) => modality === 'image'
    ? startPhoneImage(imageInput, onChange, signal) : startPhoneVideo(videoInput, onChange, signal)
  const endpoint = modality === 'image' ? '/api/generate' : '/api/video/generate'

  test(`${modality}: the same signal and trusted-cookie transport own POST and polling`, async () => {
    const previous = globalThis.fetch, controller = new AbortController()
    const calls: string[] = [], seen: string[] = [], inits: RequestInit[] = []
    globalThis.fetch = async (input, init) => {
      calls.push(String(input))
      inits.push(init || {})
      if (String(input) === endpoint) {
        return Response.json({ id: `${modality}-owned` })
      }
      return Response.json({ job: job('completed', modality) })
    }
    try {
      const result = await start((value) => seen.push(value.status), controller.signal)
      assert.equal(result.id, `${modality}-owned`)
      assert.deepEqual(calls, [endpoint, `/api/phone/v1/jobs/${modality}-owned`])
      assert.deepEqual(seen, ['completed'])
      assert.equal(inits[0].method, 'POST')
      assert.equal(JSON.parse(String(inits[0].body)).mode, modality === 'image' ? 'text_to_image' : 'text_to_video')
      for (const init of inits) {
        assert.equal(init.signal, controller.signal)
        assert.equal(init.credentials, 'include')
      }
    } finally { globalThis.fetch = previous }
  })

  test(`${modality}: a late admission after unmount cannot start polling or update UI`, async () => {
    const previous = globalThis.fetch, controller = new AbortController(), response = deferred<Response>()
    const calls: string[] = [], seen: PhoneJob[] = []
    globalThis.fetch = async (input) => {
      calls.push(String(input))
      return String(input) === endpoint ? response.promise : Response.json({ job: job('completed', modality) })
    }
    try {
      const pending = start((value) => seen.push(value), controller.signal)
      controller.abort()
      response.resolve(Response.json({ id: `${modality}-owned` }))
      await assert.rejects(pending, { name: 'AbortError' })
      assert.deepEqual(calls, [endpoint])
      assert.deepEqual(seen, [])
    } finally { globalThis.fetch = previous }
  })
}
