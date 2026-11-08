import assert from 'node:assert/strict'
import test from 'node:test'
import { saveOpenrouterKey, checkOpenrouterKey, deleteOpenrouterKey, openrouterSecretSource } from './src/adminOpenrouterKey.ts'

const marker = ['sk', 'or', 'private-fixture-value'].join('-')
const reply = (status: number, body: unknown) => async () => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

test('503 preserves input contract and never claims storage success or reflects diagnostics', async () => {
  const result = await saveOpenrouterKey(reply(503, { detail: marker }), marker)
  assert.equal(result.saved, false)
  assert.equal(result.verified, false)
  assert.match(result.message, /Не удалось подтвердить сохранение/)
  assert.equal(result.message.includes(marker), false)
})

test('durable saved key clears input even when provider verification is unavailable', async () => {
  const result = await saveOpenrouterKey(reply(200, { ok: true, keySaved: true, keyVerified: false }), marker)
  assert.equal(result.saved, true)
  assert.equal(result.verified, false)
  assert.match(result.message, /проверка.*не подтверждена/)
})

test('successful storage and provider verification are explicit', async () => {
  const result = await saveOpenrouterKey(reply(200, { ok: true, keySaved: true, keyVerified: true }), marker)
  assert.equal(result.saved, true)
  assert.equal(result.verified, true)
  assert.match(result.message, /сохранён и проверен/)
})

test('ambiguous legacy or malformed success does not clear input', async () => {
  assert.equal((await saveOpenrouterKey(reply(200, { ok: true, key: { ok: true } }), marker)).saved, false)
  assert.equal((await saveOpenrouterKey(async () => new Response('invalid'), marker)).saved, false)
  assert.equal((await saveOpenrouterKey(async () => { throw new Error(marker) }, marker)).message.includes(marker), false)
})

test('environment priority and deletion remain truthful', async () => {
  const saved = await saveOpenrouterKey(reply(200, { ok: true, keySaved: true, environmentOverride: true }), marker)
  assert.match(saved.message, /настроек окружения/)
  const removed = await deleteOpenrouterKey(reply(200, { ok: true, keyRemoved: true, environmentOverride: true }))
  assert.match(removed, /остаётся активным/)
})

test('check uses a fresh GET key endpoint and no paid request', async () => {
  const requests: Array<{ path: string; method?: string }> = []
  const message = await checkOpenrouterKey(async (path, init) => {
    requests.push({ path, method: init?.method })
    return reply(200, { ok: true, keyVerified: true, key: { configured: true } })()
  })
  assert.deepEqual(requests, [{ path: '/admin/openrouter/key', method: 'GET' }])
  assert.match(message, /проверен/)
})

test('platform source labels do not misidentify Linux as Windows DPAPI', () => {
  assert.match(openrouterSecretSource('linux-aes-gcm'), /Linux/)
  assert.match(openrouterSecretSource('dpapi'), /Windows/)
  assert.match(openrouterSecretSource('env'), /окружения/)
})
