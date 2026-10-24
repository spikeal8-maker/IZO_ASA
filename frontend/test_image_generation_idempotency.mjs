import assert from 'node:assert/strict'
import { webcrypto } from 'node:crypto'
import { beforeEach, test } from 'node:test'
import { beginImageGenerationCommand, acknowledgeImageGenerationCommand, rejectImageGenerationCommand } from './src/studio/imageGenerationCommand.ts'

const values = new Map()
globalThis.sessionStorage = {
  getItem: (key) => values.has(key) ? values.get(key) : null,
  setItem: (key, value) => values.set(key, String(value)),
  removeItem: (key) => values.delete(key),
}
Object.defineProperty(globalThis, 'crypto', { configurable: true, value: webcrypto })

beforeEach(() => values.clear())

test('concurrent repeated intent 2/5/10 uses exactly one key, frozen seed and body', async () => {
  for (const n of [2, 5, 10]) {
    values.clear()
    const requests = await Promise.all(Array.from({ length: n }, () =>
      beginImageGenerationCommand('phone', { prompt: 'safe synthetic fixture', width: 704, height: 704 })))
    assert.equal(new Set(requests.map((x) => x.key)).size, 1)
    assert.equal(new Set(requests.map((x) => x.seed)).size, 1)
    assert.equal(new Set(requests.map((x) => x.body)).size, 1)
    assert.equal(JSON.parse(requests[0].body).clientRequestId, requests[0].key)
  }
})

test('network outcome unknown survives reload and preserves original operation', async () => {
  const first = await beginImageGenerationCommand('desktop', { prompt: 'test', model: 'local' }, 42)
  const recovered = await beginImageGenerationCommand('desktop', { prompt: 'test', model: 'local' }, 13)
  assert.deepEqual(recovered, first)
  assert.equal(first.seed, 42)
})

test('changed request with unresolved key fails closed rather than creating a paid job', async () => {
  const first = await beginImageGenerationCommand('phone', { prompt: 'original' })
  await assert.rejects(() => beginImageGenerationCommand('phone', { prompt: 'changed' }), /Предыдущий запуск/)
  assert.equal((await beginImageGenerationCommand('phone', { prompt: 'original' })).key, first.key)
})

test('an acknowledged operation and an explicit subsequent launch get different keys', async () => {
  const first = await beginImageGenerationCommand('desktop', { prompt: 'again' })
  acknowledgeImageGenerationCommand('desktop', first.key)
  const second = await beginImageGenerationCommand('desktop', { prompt: 'again' })
  assert.notEqual(second.key, first.key)
})

test('definitive admission rejection may release key; uncertain 429/500 must not', async () => {
  const first = await beginImageGenerationCommand('phone', { prompt: 'charge' })
  rejectImageGenerationCommand('phone', first.key, 500)
  rejectImageGenerationCommand('phone', first.key, 429)
  assert.equal((await beginImageGenerationCommand('phone', { prompt: 'charge' })).key, first.key)
  rejectImageGenerationCommand('phone', first.key, 402)
  assert.notEqual((await beginImageGenerationCommand('phone', { prompt: 'charge' })).key, first.key)
})

test('unreadable saved state fails closed', async () => {
  values.set('izo.image.pending.phone.v1', 'corrupted')
  await assert.rejects(() => beginImageGenerationCommand('phone', { prompt: 'another' }), /Новое списание заблокировано/)
})
