import assert from 'node:assert/strict'
import test from 'node:test'
import { createAdminCommandClient } from './src/adminCommand.ts'
import type { AdminCommandResult } from './src/adminCommand.ts'

const path = '/admin/users/local-target/tokens-v2'
const body = { delta: 25, reason: 'manual correction' }

function storage() {
  const data = new Map<string, string>()
  return {
    data,
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => { data.set(key, value) },
    removeItem: (key: string) => { data.delete(key) },
  }
}

test('duplicate clicks and a late success click share a single financial request', async () => {
  const store = storage()
  let release: (result: AdminCommandResult) => void = () => assert.fail('sender did not start')
  const calls: Record<string, unknown>[] = []
  const client = createAdminCommandClient(store, async (_path, request) => {
    calls.push(request)
    return new Promise(resolve => { release = resolve })
  }, () => 'command-click-000001')
  const first = client.submit(path, body)
  const second = client.submit(path, body)
  await Promise.resolve()
  assert.equal(calls.length, 1)
  assert.equal(calls[0].idempotency_key, 'command-click-000001')
  release({ ok: true, status: 200 })
  assert.deepEqual(await first, await second)
  assert.deepEqual(await client.submit(path, body), { ok: true, status: 200 })
  assert.equal(calls.length, 1)
  assert.equal(store.data.size, 0)
})

test('unknown response and a page reload reuse the persisted key and input', async () => {
  const store = storage()
  const keys: unknown[] = []
  const first = createAdminCommandClient(store, async (_path, request) => {
    keys.push(request.idempotency_key)
    throw new Error('connection closed after server commit')
  }, () => 'command-unknown-0001')
  assert.equal((await first.submit(path, body)).status, 0)
  const reloaded = createAdminCommandClient(store, async (_path, request) => {
    keys.push(request.idempotency_key)
    return { ok: true, status: 200 }
  }, () => assert.fail('reload allocated another financial command'))
  assert.deepEqual(reloaded.recover(path), body)
  assert.equal((await reloaded.submit(path, body)).ok, true)
  assert.deepEqual(keys, ['command-unknown-0001', 'command-unknown-0001'])
})

test('changed payload cannot replace a still unconfirmed command', async () => {
  const store = storage()
  let calls = 0
  const client = createAdminCommandClient(store, async () => {
    calls += 1
    return { ok: false, status: 503 }
  }, () => 'command-conflict-001')
  await client.submit(path, body)
  assert.equal((await client.submit(path, { ...body, delta: 26 })).status, 409)
  assert.equal(calls, 1)
  assert.deepEqual(client.recover(path), body)
})

test('explicit initial validation rejection permits a corrected new action', async () => {
  const store = storage()
  let next = 0
  const keys: unknown[] = []
  const client = createAdminCommandClient(store, async (_path, request) => {
    keys.push(request.idempotency_key)
    return { ok: false, status: 400 }
  }, () => `command-validation-${++next}`)
  await client.submit(path, body)
  await client.submit(path, { ...body, delta: -1 })
  assert.deepEqual(keys, ['command-validation-1', 'command-validation-2'])
})

test('a retry rejection retains the original unknown obligation', async () => {
  const store = storage()
  let calls = 0
  const client = createAdminCommandClient(store, async () => {
    calls += 1
    return { ok: false, status: calls === 1 ? 503 : 400 }
  }, () => 'command-retry-000001')
  await client.submit(path, body)
  await client.submit(path, body)
  assert.equal(store.data.size, 1)
  assert.equal((await client.submit(path, { ...body, delta: 30 })).status, 409)
})

test('plan replay uses normalized reason and canonical default duration', async () => {
  const store = storage()
  const planPath = '/admin/users/local-target/plan-v2'
  const keys: unknown[] = []
  const client = createAdminCommandClient(store, async (_path, request) => {
    keys.push(request.idempotency_key)
    assert.equal(request.reason, 'approved')
    assert.equal(request.duration_days, 30)
    return { ok: false, status: 503 }
  }, () => 'command-plan-000001')
  await client.submit(planPath, { plan: 'pro', reason: ' approved ' })
  await client.submit(planPath, { plan: 'pro', duration_days: 30, reason: 'approved' })
  assert.deepEqual(keys, ['command-plan-000001', 'command-plan-000001'])
})

test('unavailable storage prevents sending an unrepeatable command', async () => {
  const client = createAdminCommandClient({
    getItem: () => null,
    setItem: () => { throw new Error('storage blocked') },
    removeItem: () => assert.fail('unexpected removal'),
  }, async () => assert.fail('financial request was sent'), () => 'command-storage-001')
  const result = await client.submit(path, body)
  assert.equal(result.ok, false)
  assert.equal(result.status, 0)
})

test('corrupt pending state is not silently overwritten with a fresh key', async () => {
  const store = storage()
  store.setItem('izo.admin-command.v1:' + path, '{invalid')
  const client = createAdminCommandClient(store, async () => assert.fail('sent after corruption'),
    () => assert.fail('allocated key after corruption'))
  assert.equal((await client.submit(path, body)).ok, false)
  assert.equal(store.data.size, 1)
})

test('new confirmation after successful completion creates a new explicit command', async () => {
  const store = storage()
  const keys: unknown[] = []
  const sender = async (_path: string, request: Record<string, unknown>) => {
    keys.push(request.idempotency_key)
    return { ok: true, status: 200 }
  }
  await createAdminCommandClient(store, sender, () => 'command-first-00001').submit(path, body)
  await createAdminCommandClient(store, sender, () => 'command-second-0001').submit(path, body)
  assert.deepEqual(keys, ['command-first-00001', 'command-second-0001'])
})

test('late success from a closed dialog cannot erase a newer pending command', async () => {
  const store = storage()
  let release: (result: AdminCommandResult) => void = () => assert.fail('sender did not start')
  const original = createAdminCommandClient(store, async () => new Promise(resolve => { release = resolve }),
    () => 'command-original-001')
  const pendingOriginal = original.submit(path, body)
  await Promise.resolve()
  const retry = createAdminCommandClient(store, async (_path, request) => {
    assert.equal(request.idempotency_key, 'command-original-001')
    return { ok: true, status: 200 }
  }, () => assert.fail('retry generated another command'))
  await retry.submit(path, body)
  const newer = createAdminCommandClient(store, async () => ({ ok: false, status: 503 }), () => 'command-newer-00001')
  await newer.submit(path, { ...body, delta: 26 })
  release({ ok: true, status: 200 })
  await pendingOriginal
  assert.deepEqual(newer.recover(path), { ...body, delta: 26 })
  const recovered = JSON.parse(store.getItem('izo.admin-command.v1:' + path) ?? '{}')
  assert.equal(recovered.key, 'command-newer-00001')
})

test('late initial rejection cannot erase a replay whose response is still unknown', async () => {
  const store = storage()
  let release: (result: AdminCommandResult) => void = () => assert.fail('sender did not start')
  const original = createAdminCommandClient(store, async () => new Promise(resolve => { release = resolve }),
    () => 'command-rejected-01')
  const pendingOriginal = original.submit(path, body)
  await Promise.resolve()
  const retry = createAdminCommandClient(store, async () => ({ ok: false, status: 503 }),
    () => assert.fail('retry generated another command'))
  await retry.submit(path, body)
  release({ ok: false, status: 400 })
  await pendingOriginal
  const recovered = JSON.parse(store.getItem('izo.admin-command.v1:' + path) ?? '{}')
  assert.equal(recovered.key, 'command-rejected-01')
  assert.equal(recovered.attempts, 2)
  assert.deepEqual(retry.recover(path), body)
})
