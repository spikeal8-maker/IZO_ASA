import assert from 'node:assert/strict'
import test from 'node:test'

import { createGenerationRequest } from './src/generationAdmission.ts'
import { phoneFetch, PhoneTransportError } from './src/phone/core/http.ts'

const body = JSON.stringify({ mode: 'text_to_image', prompt: 'Река', seed: 123, width: 512, height: 512 })

function capture(input: RequestInfo | URL, init?: RequestInit) {
  const headers = new Headers(init?.headers)
  return { url: String(input), body: init?.body, key: headers.get('Idempotency-Key'), headers, credentials: init?.credentials }
}

test('a lost generation response retries the identical key, body, seed and headers', async (t) => {
  const calls: ReturnType<typeof capture>[] = []
  t.mock.method(globalThis, 'fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push(capture(input, init))
    if (calls.length === 1) throw new TypeError('connection dropped after server admission')
    return new Response(JSON.stringify({ id: 'persisted-job' }), { status: 200 })
  })
  const headers = { 'Content-Type': 'application/json', 'X-Request-Test': 'kept' }
  const request = createGenerationRequest('/api/generate', { method: 'POST', body, headers, credentials: 'include' })
  assert.deepEqual(await (await request()).json(), { id: 'persisted-job' })
  assert.equal(calls.length, 2)
  assert.match(calls[0].key || '', /^[0-9a-f-]{36}$/i)
  assert.equal(calls[1].key, calls[0].key)
  assert.equal(calls[0].body, body)
  assert.equal(calls[1].body, body)
  assert.equal(calls[1].headers.get('X-Request-Test'), 'kept')
  assert.equal(calls[1].headers.get('Content-Type'), 'application/json')
  assert.equal(calls[1].credentials, 'include')
  assert.equal(new Headers(headers).has('Idempotency-Key'), false)
})

test('reusing the request after session refresh preserves its operation', async (t) => {
  const calls: ReturnType<typeof capture>[] = []
  t.mock.method(globalThis, 'fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push(capture(input, init))
    return new Response('{}', { status: calls.length === 1 ? 401 : 200 })
  })
  const request = createGenerationRequest('https://example.invalid/api/generate', { method: 'POST', body })
  assert.equal((await request()).status, 401)
  assert.equal(calls.length, 1)
  assert.equal((await request()).status, 200)
  assert.equal(calls[0].key, calls[1].key)
  assert.equal(calls[0].body, calls[1].body)
})

test('the network retry budget is bounded across session-refresh calls', async (t) => {
  let calls = 0
  t.mock.method(globalThis, 'fetch', async () => {
    calls += 1
    if (calls === 2) return new Response('{}', { status: 401 })
    throw new TypeError('network unavailable')
  })
  const request = createGenerationRequest('/api/generate', { method: 'POST', body })
  assert.equal((await request()).status, 401)
  await assert.rejects(request(), /network unavailable/)
  assert.equal(calls, 3)
})

test('a new explicit intent receives a distinct key despite identical content', async (t) => {
  const keys: Array<string | null> = []
  t.mock.method(globalThis, 'fetch', async (_input: RequestInfo | URL, init?: RequestInit) => {
    keys.push(new Headers(init?.headers).get('Idempotency-Key'))
    return new Response('{}')
  })
  await createGenerationRequest('/api/generate', { method: 'POST', body })()
  await createGenerationRequest('/api/generate', { method: 'POST', body })()
  assert.ok(keys[0] && keys[1])
  assert.notEqual(keys[0], keys[1])
})

test('an explicit caller key is preserved without mutating its Headers object', async (t) => {
  const headers = new Headers({ 'idempotency-key': 'caller-operation', Accept: 'application/json' })
  let observed: ReturnType<typeof capture> | undefined
  t.mock.method(globalThis, 'fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
    observed = capture(input, init)
    return new Response('{}')
  })
  await createGenerationRequest('/api/generate', { method: 'post', body, headers })()
  assert.equal(observed?.key, 'caller-operation')
  assert.equal(headers.get('Idempotency-Key'), 'caller-operation')
  assert.equal(headers.get('Accept'), 'application/json')
})

test('two network failures stop without an unbounded retry', async (t) => {
  let calls = 0
  t.mock.method(globalThis, 'fetch', async () => {
    calls += 1
    throw new TypeError('network down')
  })
  await assert.rejects(createGenerationRequest('/api/generate', { method: 'POST', body })(), /network down/)
  assert.equal(calls, 2)
})

for (const status of [401, 409, 429, 500, 503]) {
  test(`an HTTP ${status} response does not trigger a network retry`, async (t) => {
    let calls = 0
    t.mock.method(globalThis, 'fetch', async () => {
      calls += 1
      return new Response('{}', { status })
    })
    assert.equal((await createGenerationRequest('/api/generate', { method: 'POST', body })()).status, status)
    assert.equal(calls, 1)
  })
}

test('an aborted signal never retries generation', async (t) => {
  const controller = new AbortController()
  let calls = 0
  t.mock.method(globalThis, 'fetch', async () => {
    calls += 1
    controller.abort()
    throw new TypeError('cancelled request')
  })
  await assert.rejects(createGenerationRequest('/api/generate', { method: 'POST', body, signal: controller.signal })())
  assert.equal(calls, 1)
})

test('an AbortError without a signal is also never retried', async (t) => {
  let calls = 0
  t.mock.method(globalThis, 'fetch', async () => {
    calls += 1
    throw new DOMException('cancelled', 'AbortError')
  })
  await assert.rejects(createGenerationRequest('/api/generate', { method: 'POST', body })(), { name: 'AbortError' })
  assert.equal(calls, 1)
})

test('non-replayable bodies and non-POST use are rejected before fetch', (t) => {
  let calls = 0
  t.mock.method(globalThis, 'fetch', async () => {
    calls += 1
    return new Response('{}')
  })
  assert.throws(() => createGenerationRequest('/api/generate', { method: 'POST', body: new Blob(['data']) }), TypeError)
  assert.throws(() => createGenerationRequest('/api/generate', { method: 'GET' }), TypeError)
  assert.equal(calls, 0)
})

test('the actual phone wrapper uses stable admission while preserving trusted credentials', async (t) => {
  const calls: ReturnType<typeof capture>[] = []
  t.mock.method(globalThis, 'fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push(capture(input, init))
    if (calls.length === 1) throw new TypeError('response lost')
    return new Response(JSON.stringify({ id: 'phone-job' }))
  })
  const response = await phoneFetch('/api/generate', { method: 'POST', body, headers: { 'Content-Type': 'application/json' } })
  assert.deepEqual(response, { id: 'phone-job' })
  assert.equal(calls.length, 2)
  assert.ok(calls[0].key)
  assert.equal(calls[1].key, calls[0].key)
  assert.equal(calls[0].body, calls[1].body)
  assert.equal(calls[1].credentials, 'include')
  assert.equal(calls[1].headers.get('Accept'), 'application/json')
})

test('new phone actions have separate keys and supplied Headers are honored', async (t) => {
  const calls: ReturnType<typeof capture>[] = []
  t.mock.method(globalThis, 'fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push(capture(input, init))
    return new Response('{}')
  })
  await phoneFetch('/api/generate', { method: 'POST', body })
  await phoneFetch('/api/generate', { method: 'POST', body })
  await phoneFetch('/api/generate', {
    method: 'POST', body,
    headers: new Headers({ 'Idempotency-Key': 'caller-key', Accept: 'application/test+json' }),
  })
  assert.notEqual(calls[0].key, calls[1].key)
  assert.equal(calls[2].key, 'caller-key')
  assert.equal(calls[2].headers.get('Accept'), 'application/test+json')
})

for (const [method, path] of [
  ['GET', '/api/generate'], ['POST', '/api/video/generate'],
  ['POST', '/api/phone/chat'], ['GET', '/api/model-access'],
]) {
  test(`phone ${method} ${path} does not gain a generation key or automatic retry`, async (t) => {
    const calls: ReturnType<typeof capture>[] = []
    t.mock.method(globalThis, 'fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push(capture(input, init))
      throw new TypeError('offline')
    })
    await assert.rejects(
      phoneFetch(path, { method, ...(method === 'POST' ? { body } : {}) }),
      (error: unknown) => error instanceof PhoneTransportError && error.status === 0,
    )
    assert.equal(calls.length, 1)
    assert.equal(calls[0].key, null)
  })
}

test('a successful response whose body is interrupted reuses the accepted operation', async (t) => {
  const calls: ReturnType<typeof capture>[] = []
  t.mock.method(globalThis, 'fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push(capture(input, init))
    if (calls.length === 1) {
      const interrupted = new ReadableStream({
        start(controller) { controller.error(new TypeError('connection lost while reading body')) },
      })
      return new Response(interrupted, { status: 200 })
    }
    return new Response(JSON.stringify({ id: 'accepted-before-disconnect' }))
  })
  const response = await createGenerationRequest('/api/generate', { method: 'POST', body })()
  assert.deepEqual(await response.json(), { id: 'accepted-before-disconnect' })
  assert.equal(calls.length, 2)
  assert.equal(calls[0].key, calls[1].key)
  assert.equal(calls[0].body, calls[1].body)
})
