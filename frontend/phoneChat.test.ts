import assert from 'node:assert/strict'
import test from 'node:test'

import { runChatImageTool, sendChatMessage } from './src/phone/features/chat/api.ts'
import { cleanAssistantText } from './src/phone/features/chat/format.ts'


test('hides technical image tool envelopes from the conversation', () => {
  const value = cleanAssistantText('{"action":"generate_image","action_input":{"prompt":"кот"}}', [{ name: 'generate_image', status: 'requested' }])
  assert.equal(value, '')
  assert.equal(cleanAssistantText('Короткий ответ.', []), 'Короткий ответ.')
})

test('sends only the current user turn and durable thread id', async () => {
  const previousFetch = globalThis.fetch
  let captured: Record<string, unknown> = {}
  globalThis.fetch = async (_input, init) => {
    captured = JSON.parse(String(init?.body || '{}')) as Record<string, unknown>
    return new Response(JSON.stringify({ reply: 'Ответ', modelId: 'local:izo-chat', chargedTokens: 1, tokenKind: 'daily', tools: [] }), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }
  try {
    const answer = await sendChatMessage({ threadId: '0123456789abcdef', content: 'Привет', modelId: 'local:izo-chat', images: [], requestId: 'request-1234' })
    assert.equal(answer.reply, 'Ответ')
    assert.equal(captured.threadId, '0123456789abcdef')
    assert.deepEqual(captured.messages, [{ role: 'user', content: 'Привет' }])
  } finally { globalThis.fetch = previousFetch }
})

test('runs requested image tool through the real generation job contract', async () => {
  const previousFetch = globalThis.fetch
  globalThis.fetch = async (input) => {
    const path = String(input)
    if (path === '/api/model-access') return new Response(JSON.stringify({ modes: { text_to_image: { models: [{ id: 'server:local_flux_klein', provider: 'comfyui', modelProfile: 'local_flux_klein' }], presets: { fast: 'server:local_flux_klein' } } } }), { status: 200 })
    if (path === '/api/generate') return new Response(JSON.stringify({ id: 'job-image-1' }), { status: 200 })
    if (path.endsWith('/api/phone/v1/jobs/job-image-1')) return new Response(JSON.stringify({ job: { id: 'job-image-1', modality: 'image', operation: 'text_to_image', status: 'completed', phase: 'terminal', progress: 100, message: '', createdAt: null, startedAt: null, completedAt: null, terminal: true, result: { id: 'image-1', type: 'image', url: '/api/media/result.webp', thumbnailUrl: null, width: 1024, height: 1024, durationSeconds: null, aspectRatio: '1:1' }, billing: { chargedTokens: 1, tokenKind: 'daily', refunded: false } } }), { status: 200 })
    return new Response('{}', { status: 404 })
  }
  try {
    const states: string[] = []
    const result = await runChatImageTool({ name: 'generate_image', status: 'requested', prompt: 'красная кружка', aspectRatio: '1:1' }, (tool) => states.push(String(tool.status)))
    assert.equal(result.resultUrl, '/api/media/result.webp')
    assert.deepEqual(states, ['running', 'done'])
  } finally { globalThis.fetch = previousFetch }
})
