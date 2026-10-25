import assert from 'node:assert/strict'
import { webcrypto } from 'node:crypto'
import { beforeEach, test } from 'node:test'
import { beginImageGenerationCommand as beginVerified, acknowledgeImageGenerationCommand, completeImageGenerationCommand as completeVerified, getAcceptedImageGenerationJob as getVerifiedJob, rejectImageGenerationCommand } from './src/studio/imageGenerationCommand.ts'

const values = new Map()
let owner = 'account-A'
let authOk = true
let expiredAccess = false
let refreshValid = true
let refreshCount = 0

const resolveMe = async () => {
  if (!authOk) return null
  if (expiredAccess) {
    if (!refreshValid) return null
    refreshCount += 1
    expiredAccess = false
  }
  return { internal_user_id: owner }
}
const beginImageGenerationCommand = (scope, draft, seed) => beginVerified(scope, draft, resolveMe, seed)
const getAcceptedImageGenerationJob = (scope) => getVerifiedJob(scope, resolveMe)
const completeImageGenerationCommand = (scope, jobId) => completeVerified(scope, jobId, resolveMe)
globalThis.sessionStorage = {
  getItem: (key) => values.has(key) ? values.get(key) : null,
  setItem: (key, value) => values.set(key, String(value)),
  removeItem: (key) => values.delete(key),
}
Object.defineProperty(globalThis, 'crypto', { configurable: true, value: webcrypto })
globalThis.fetch = async () => { throw new Error('Direct owner fetch bypassed canonical session resolver') }

beforeEach(() => { values.clear(); owner = 'account-A'; authOk = true; expiredAccess = false; refreshValid = true; refreshCount = 0 })

test('concurrent same intent 2/5/10 freezes one key, seed and body per owner', async () => {
  for (const n of [2, 5, 10]) {
    values.clear()
    const requests = await Promise.all(Array.from({ length: n }, () =>
      beginImageGenerationCommand('phone', { prompt: 'synthetic fixture', width: 704, height: 704 })))
    assert.equal(new Set(requests.map((x) => x.key)).size, 1)
    assert.equal(new Set(requests.map((x) => x.seed)).size, 1)
    assert.equal(new Set(requests.map((x) => x.body)).size, 1)
    assert.equal(new Set(requests.map((x) => x.ownerId)).size, 1)
    assert.equal(JSON.parse(requests[0].body).clientRequestId, requests[0].key)
  }
})

test('pending unknown ACK A→logout→B→logout→A: B gets independent key, A retains original', async () => {
  for (const scope of ['phone', 'desktop']) {
    values.clear()
    owner = 'account-A'
    const first = await beginImageGenerationCommand(scope, { prompt: 'shared text' }, 42)
    owner = 'account-B'
    assert.equal(await getAcceptedImageGenerationJob(scope), null)
    const second = await beginImageGenerationCommand(scope, { prompt: 'shared text' }, 43)
    assert.notEqual(first.key, second.key)
    assert.notEqual(first.ownerId, second.ownerId)
    owner = 'account-A'
    const restored = await beginImageGenerationCommand(scope, { prompt: 'shared text' }, 1)
    assert.deepEqual(restored, first)
    assert.equal(restored.seed, 42)
  }
})

test('accepted A job ID cannot be inherited by B and A can recover after F5', async () => {
  for (const scope of ['phone', 'desktop']) {
    values.clear()
    owner = 'account-A'
    const first = await beginImageGenerationCommand(scope, { prompt: 'private A' })
    acknowledgeImageGenerationCommand(scope, first.ownerId, first.key, 'job_private_A')
    assert.equal(await getAcceptedImageGenerationJob(scope), 'job_private_A')
    owner = 'account-B'
    assert.equal(await getAcceptedImageGenerationJob(scope), null)
    const second = await beginImageGenerationCommand(scope, { prompt: 'private B' })
    acknowledgeImageGenerationCommand(scope, second.ownerId, second.key, 'job_private_B')
    assert.equal(await getAcceptedImageGenerationJob(scope), 'job_private_B')
    await completeImageGenerationCommand(scope, 'job_private_A')
    assert.equal(await getAcceptedImageGenerationJob(scope), 'job_private_B')
    owner = 'account-A'
    assert.equal(await getAcceptedImageGenerationJob(scope), 'job_private_A')
    assert.equal((await beginImageGenerationCommand(scope, { prompt: 'private A' })).key, first.key)
    await completeImageGenerationCommand(scope, 'job_private_A')
    assert.equal(await getAcceptedImageGenerationJob(scope), null)
  }
})

test('changed request for unresolved account command is fail-closed', async () => {
  const first = await beginImageGenerationCommand('phone', { prompt: 'original' })
  await assert.rejects(() => beginImageGenerationCommand('phone', { prompt: 'changed' }), /Предыдущий запуск/)
  assert.equal((await beginImageGenerationCommand('phone', { prompt: 'original' })).key, first.key)
})

test('accepted job survives reload; unrelated completion and 401 never erase it', async () => {
  const first = await beginImageGenerationCommand('desktop', { prompt: 'again' }, 42)
  acknowledgeImageGenerationCommand('desktop', first.ownerId, first.key, 'job_accepted_1')
  rejectImageGenerationCommand('desktop', first.ownerId, first.key, 401)
  assert.equal(await getAcceptedImageGenerationJob('desktop'), 'job_accepted_1')
  await completeImageGenerationCommand('desktop', 'job_unrelated')
  assert.equal(await getAcceptedImageGenerationJob('desktop'), 'job_accepted_1')
  await completeImageGenerationCommand('desktop', 'job_accepted_1')
  assert.notEqual((await beginImageGenerationCommand('desktop', { prompt: 'again' })).key, first.key)
})

test('429/500/401/403 keep unresolved charge identity; definite 402 releases it', async () => {
  const first = await beginImageGenerationCommand('phone', { prompt: 'charge' })
  for (const status of [429, 500, 401, 403]) {
    rejectImageGenerationCommand('phone', first.ownerId, first.key, status)
    assert.equal((await beginImageGenerationCommand('phone', { prompt: 'charge' })).key, first.key)
  }
  rejectImageGenerationCommand('phone', first.ownerId, first.key, 402)
  assert.notEqual((await beginImageGenerationCommand('phone', { prompt: 'charge' })).key, first.key)
})

test('unauthenticated or missing verified account fails closed without writing pending', async () => {
  authOk = false
  await assert.rejects(() => beginImageGenerationCommand('phone', { prompt: 'anonymous' }), /Не удалось подтвердить аккаунт/)
  assert.equal(values.size, 0)
  authOk = true
  owner = ''
  await assert.rejects(() => beginImageGenerationCommand('phone', { prompt: 'anonymous' }), /идентификатор аккаунта/)
  assert.equal(values.size, 0)
})

test('corrupt pending state for A blocks only A, not B', async () => {
  values.set('izo.image.pending.phone.v2.account-A', 'corrupt')
  await assert.rejects(() => beginImageGenerationCommand('phone', { prompt: 'new' }), /Новое списание заблокировано/)
  owner = 'account-B'
  assert.ok((await beginImageGenerationCommand('phone', { prompt: 'new' })).key)
})

test('legacy unscoped v1 command is never silently reassigned between accounts', async () => {
  values.set('izo.image.pending.phone.v1', '{"key":"orphan"}')
  await assert.rejects(() => beginImageGenerationCommand('phone', { prompt: 'new' }), /предыдущей версии/)
  owner = 'account-B'
  await assert.rejects(() => beginImageGenerationCommand('phone', { prompt: 'new' }), /предыдущей версии/)
})

test('valid refresh recovers accepted paid job with original key/seed', async () => {
  const initial = await beginImageGenerationCommand('desktop', { prompt: 'pending' }, 12)
  acknowledgeImageGenerationCommand('desktop', initial.ownerId, initial.key, 'job_paid_1')
  expiredAccess = true
  assert.equal(await getAcceptedImageGenerationJob('desktop'), 'job_paid_1')
  assert.equal(refreshCount, 1)
  const resumed = await beginImageGenerationCommand('desktop', { prompt: 'pending' }, 999)
  assert.equal(resumed.key, initial.key)
  assert.equal(resumed.seed, 12)
  assert.equal(resumed.acceptedJobId, 'job_paid_1')
})

test('invalid refresh retains unresolved owner command without a new debit', async () => {
  const first = await beginImageGenerationCommand('phone', { prompt: 'pending' })
  expiredAccess = true
  refreshValid = false
  await assert.rejects(() => beginImageGenerationCommand('phone', { prompt: 'pending' }), /Не удалось подтвердить аккаунт/)
  assert.equal(values.size, 1)
  expiredAccess = false
  assert.equal((await beginImageGenerationCommand('phone', { prompt: 'pending' })).key, first.key)
})
