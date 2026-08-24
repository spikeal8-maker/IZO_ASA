import assert from 'node:assert/strict'
import test from 'node:test'

import { estimatePhoneVideo, startPhoneVideo, type PhoneVideoRequest } from './src/phone/features/video/api.ts'

const request: PhoneVideoRequest = { mode: 'image_to_video', model: 'video/model', prompt: 'оживить кадр', duration: 4, resolution: '720p', aspectRatio: '9:16', generateAudio: true, firstFrame: 'data:image/png;base64,frame', lastFrame: null, references: [] }

test('estimates selected video format with the server economy', async () => {
  const previousFetch = globalThis.fetch
  let body: Record<string, unknown> = {}
  globalThis.fetch = async (_input, init) => { body = JSON.parse(String(init?.body || '{}')); return new Response(JSON.stringify({ chargedTokens: 7 }), { status: 200 }) }
  try {
    assert.equal((await estimatePhoneVideo(request)).chargedTokens, 7)
    assert.equal(body.resolution, '720p')
    assert.equal(body.aspectRatio, '9:16')
    assert.equal(body.generateAudio, true)
  } finally { globalThis.fetch = previousFetch }
})

test('starts video through the durable phone job facade', async () => {
  const previousFetch = globalThis.fetch
  let submitted: Record<string, unknown> = {}
  globalThis.fetch = async (input, init) => {
    if (String(input) === '/api/video/generate') { submitted = JSON.parse(String(init?.body || '{}')); return new Response(JSON.stringify({ id: 'video-job-1' }), { status: 200 }) }
    return new Response(JSON.stringify({ job: { id: 'video-job-1', modality: 'video', operation: 'image_to_video', status: 'completed', phase: 'terminal', progress: 100, message: '', createdAt: null, startedAt: null, completedAt: null, terminal: true, result: { id: 'gallery-video-1', type: 'video', url: '/api/video/media/video-job-1', thumbnailUrl: null, width: 720, height: 1280, durationSeconds: 4, aspectRatio: '9:16' }, billing: { chargedTokens: 7, tokenKind: 'main', refunded: false } } }), { status: 200 })
  }
  try {
    const result = await startPhoneVideo(request)
    assert.equal(result.result?.url, '/api/video/media/video-job-1')
    assert.equal(submitted.firstFrame, request.firstFrame)
    assert.equal(submitted.model, request.model)
  } finally { globalThis.fetch = previousFetch }
})
