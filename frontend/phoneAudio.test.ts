import assert from 'node:assert/strict'
import test from 'node:test'

import { transcribePhoneAudio } from './src/phone/features/audio/api.ts'

test('sends mobile audio through the protected transcription endpoint', async () => {
  const previousFetch = globalThis.fetch
  let requestUrl = ''
  let submitted: FormData | null = null
  globalThis.fetch = async (input, init) => {
    requestUrl = String(input)
    submitted = init?.body as FormData
    return new Response(JSON.stringify({ ok: true, text: 'Проверка записи', model: 'fake-asr', provider: 'fake' }), { status: 200 })
  }
  try {
    const file = new File([new Uint8Array([1, 2, 3])], 'voice.wav', { type: 'audio/wav' })
    const result = await transcribePhoneAudio(file, 2300)
    assert.equal(result.text, 'Проверка записи')
    assert.match(requestUrl, /duration_ms=2300/)
    assert.equal((submitted as FormData).get('file') instanceof File, true)
  } finally { globalThis.fetch = previousFetch }
})

test('shows a safe transcription service error', async () => {
  const previousFetch = globalThis.fetch
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'Сервис распознавания временно недоступен.' }), { status: 502 })
  try {
    const file = new File([new Uint8Array([1])], 'voice.wav', { type: 'audio/wav' })
    await assert.rejects(() => transcribePhoneAudio(file, 1000), /временно недоступен/)
  } finally { globalThis.fetch = previousFetch }
})
