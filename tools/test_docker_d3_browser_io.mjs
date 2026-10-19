import test from 'node:test'
import assert from 'node:assert/strict'
import { BrowserIO, CaptureBudget, LIMITS, fetchInPage, capturedJSON, decodePublicVideo } from './docker_d3_browser_io.mjs'

const argumentsFor = { route: '/api/owned', method: 'GET', expected: 200, maxBytes: 64, json: true }
const locations = new WeakSet(), documents = new WeakSet()
function environment(t, implementation) {
  if (!locations.has(t)) {
    locations.add(t)
    const old = Object.getOwnPropertyDescriptor(globalThis, 'location')
    Object.defineProperty(globalThis, 'location', { configurable: true, value: { origin: 'http://127.0.0.1:23456' } })
    t.after(() => old ? Object.defineProperty(globalThis, 'location', old) : delete globalThis.location)
  }
  t.mock.method(globalThis, 'fetch', implementation)
}
function streamed(chunks, headers = { 'content-type': 'application/json' }, status = 200) {
  const state = { reads: 0, readers: 0, cancellations: 0, releases: 0 }
  const reader = { async read() { const value = chunks[state.reads++]; return value === undefined ? { done: true } : { done: false, value } },
    async cancel() { state.cancellations++ }, releaseLock() { state.releases++ } }
  const reply = { status, headers: new Headers(headers), body: {
    getReader() { state.readers++; return reader }, async cancel() { state.cancellations++ } },
  arrayBuffer() { throw new Error('full allocation forbidden') }, json() { throw new Error('full allocation forbidden') } }
  return { state, reply, reader }
}

test('native fetch retains cookies, rejects redirects and streams bounded bytes without full-body helpers', async (t) => {
  const fixture = streamed([Buffer.from('{"o'), Buffer.from('k":true}')])
  environment(t, async (route, options) => {
    assert.equal(route, '/api/owned'); assert.equal(options.credentials, 'include'); assert.equal(options.redirect, 'error')
    assert.equal(options.body, '{"owned":true}'); assert.equal(options.headers['Content-Type'], 'application/json')
    assert.equal(Object.keys(options.headers).some((key) => /cookie|authorization/i.test(key)), false)
    return fixture.reply
  })
  const value = await fetchInPage({ ...argumentsFor, method: 'POST', data: { owned: true } })
  assert.equal(value.ok, true); assert.deepEqual(JSON.parse(Buffer.from(value.base64, 'base64')), { ok: true })
  assert.equal(value.bytes, 11); assert.equal(fixture.state.reads, 3)
  assert.ok(fixture.state.cancellations >= 1); assert.ok(fixture.state.releases >= 1)
})

test('untrusted Content-Length is rejected before the first body reader allocation', async (t) => {
  for (const length of ['100000000', '-1', '1e4', 'NaN']) {
    const fixture = streamed([new Uint8Array(100)], { 'content-type': 'application/json', 'content-length': length })
    environment(t, async () => fixture.reply)
    const value = await fetchInPage(argumentsFor)
    assert.deepEqual(value, { ok: false, code: 'D3_RESPONSE_TOO_LARGE' })
    assert.equal(fixture.state.readers, 0); assert.equal(fixture.state.reads, 0)
    assert.ok(fixture.state.cancellations >= 1)
  }
})

test('missing or lying lengths cannot hide an oversized streaming body', async (t) => {
  for (const headers of [{ 'content-type': 'application/json' }, { 'content-type': 'application/json', 'content-length': '2' }]) {
    const fixture = streamed([Buffer.alloc(3), Buffer.alloc(2), Buffer.alloc(20)], headers)
    environment(t, async () => fixture.reply)
    assert.deepEqual(await fetchInPage({ ...argumentsFor, maxBytes: 4 }), { ok: false, code: 'D3_RESPONSE_TOO_LARGE' })
    assert.equal(fixture.state.reads, 2); assert.ok(fixture.state.cancellations >= 1)
  }
})

test('expected errors/status-only checks and rejected redirects never consume arbitrary error bodies', async (t) => {
  const fixture = streamed([Buffer.alloc(10000)], {}, 401)
  environment(t, async () => fixture.reply)
  assert.deepEqual(await fetchInPage({ ...argumentsFor, expected: 401, maxBytes: 0 }), { ok: true, bytes: 0, base64: '' })
  assert.equal(fixture.state.readers, 0)
  fixture.reply.status = 302
  assert.deepEqual(await fetchInPage(argumentsFor), { ok: false, code: 'D3_HTTP_302' })
  assert.equal(fixture.state.readers, 0)
})

test('headers and a stalled body share a bounded deadline and abort their native request', async (t) => {
  let signal, unblock
  environment(t, async (_, options) => { signal = options.signal; return new Promise((resolve) => { unblock = resolve }) })
  const value = await fetchInPage({ ...argumentsFor, timeout: 2 })
  assert.deepEqual(value, { ok: false, code: 'D3_TRANSPORT_TIMEOUT' }); assert.equal(signal.aborted, true)
  const late = streamed([Buffer.from('{}')]); unblock(late.reply)
  await new Promise((resolve) => setImmediate(resolve)); assert.equal(late.state.reads, 0)
  const fixture = streamed([])
  fixture.reader.read = () => new Promise(() => {})
  environment(t, async (_, options) => { signal = options.signal; return fixture.reply })
  assert.deepEqual(await fetchInPage({ ...argumentsFor, timeout: 2 }), { ok: false, code: 'D3_TRANSPORT_TIMEOUT' })
  assert.equal(signal.aborted, true); assert.ok(fixture.state.cancellations >= 1)
})

test('transport input guards and exceptions do not disclose paths or endpoints', async (t) => {
  let called = false
  environment(t, async () => { called = true; throw new Error('http://private.invalid/token /srv/private/file') })
  for (const route of ['https://private.invalid/api/owned', '//private.invalid/api/owned', '/api/\\private.invalid']) {
    assert.deepEqual(await fetchInPage({ ...argumentsFor, route }), { ok: false, code: 'D3_TRANSPORT_INPUT_INVALID' })
  }
  assert.equal(called, false)
  assert.deepEqual(await fetchInPage(argumentsFor), { ok: false, code: 'D3_TRANSPORT_FAILED' })
})

test('captured UI JSON requires bounded identity Content-Length before body()', async () => {
  for (const headers of [{}, { 'content-length': '65' }, { 'content-length': '-1' },
    { 'content-length': '2', 'content-encoding': 'gzip' }, { 'content-length': '2', 'content-type': 'text/html' }]) {
    let reads = 0
    await assert.rejects(capturedJSON({ headers: () => ({ 'content-type': 'application/json', ...headers }),
      body: async () => { reads++; return Buffer.from('{}') } }, 64), /D3_CAPTURE_BODY_NOT_BOUNDED/)
    assert.equal(reads, 0)
  }
  const reply = { headers: () => ({ 'content-type': 'application/json', 'content-length': '2' }), body: async () => Buffer.from('{}') }
  assert.deepEqual(await capturedJSON(reply, 64), { value: {}, bytes: 2 })
  await assert.rejects(capturedJSON({ ...reply, body: async () => Buffer.from('{"x":1}') }), /D3_CAPTURE_LENGTH_MISMATCH/)
})

test('byte reservations and work request counts cannot consume the separate cleanup allowance', () => {
  const budget = new CaptureBudget(), tickets = []
  for (let index = 0; index < 8; index++) tickets.push(budget.reserve(LIMITS.publicMedia))
  assert.throws(() => budget.reserve(1), /D3_CAPTURE_BYTE_LIMIT/)
  for (const ticket of tickets) budget.release(ticket, ticket)
  assert.equal(budget.bytes, LIMITS.totalBytes); assert.equal(budget.reserved, 0)
  assert.throws(() => budget.reserve(1), /D3_CAPTURE_BYTE_LIMIT/)
  for (const kind of ['direct', 'http']) {
    for (let index = 0; index < LIMITS[kind]; index++) budget.request(kind)
    assert.throws(() => budget.request(kind), /D3_REQUEST_LIMIT/)
    for (let index = 0; index < 4; index++) budget.request(kind, true)
    assert.throws(() => budget.request(kind, true), /D3_REQUEST_LIMIT/)
  }
})

test('a work guard failure still permits only the two fixed session cleanup operations', async () => {
  const io = new BrowserIO(null, 'http://127.0.0.1:23456', 'owned', () => true), client = {}
  io.pages.set(client, { evaluate: async (_, args) => {
    assert.equal(args.maxBytes, 0); return { ok: true, bytes: 0, base64: '' }
  } })
  io.violation = 'D3_BROWSER_REQUEST_GUARD_FAILED'; io.beginCleanup()
  await io.read(client, 'POST', '/api/auth/session/logout-v2', {}, 200)
  await io.read(client, 'GET', '/api/me-v2', undefined, 401)
  await assert.rejects(io.read(client, 'POST', '/api/generate', {}, 200), /D3_REQUEST_NOT_ADMITTED/)
  await assert.rejects(io.read(client, 'GET', '/api/me-v2', undefined, 401, 10), /D3_REQUEST_NOT_ADMITTED/)
  assert.equal(io.counts().apiRequests, 2)
})

test('route failures retain the first finite code and never expose exception details', async () => {
  for (const exhausted of [true, false]) {
    let handler, aborted = 0
    const client = { route: async (_, callback) => { handler = callback }, newPage: async () => ({ goto: async () => {} }) }
    const io = new BrowserIO({ newContext: async () => client }, 'http://127.0.0.1:23456', 'owned', () => false)
    await io.context()
    if (exhausted) io.budget.httpRequests = LIMITS.http
    const denied = { request: () => { throw new Error('private.invalid/secret') }, abort: async () => { aborted++ } }
    await handler(exhausted ? { ...denied, request: () => ({ url: () => io.origin + '/api/owned' }) } : denied)
    const code = exhausted ? 'D3_BROWSER_HTTP_REQUEST_LIMIT' : 'D3_BROWSER_REQUEST_GUARD_FAILED'
    assert.equal(io.violation, code)
    await handler(denied); assert.equal(io.violation, code); assert.equal(aborted, 2)
    assert.equal(io.counts().browserWorkHttpRequests, exhausted ? LIMITS.http : 0)
    assert.equal(io.counts().browserCleanupHttpRequests, 0)
  }
})

function videoDOM(t, overrides = {}) {
  if (!documents.has(t)) {
    documents.add(t)
    const previous = Object.getOwnPropertyDescriptor(globalThis, 'document')
    t.after(() => previous ? Object.defineProperty(globalThis, 'document', previous) : delete globalThis.document)
  }
  const calls = { revoked: 0, removed: 0, stopped: 0, loads: 0 }
  let time = 0
  const video = { videoWidth: 832, videoHeight: 480, duration: 2.083333, readyState: 2,
    pause() { calls.stopped++ }, removeAttribute() {}, load() { calls.loads++ }, remove() { calls.removed++ },
    set src(_) { queueMicrotask(() => this.onloadeddata?.()) },
    set currentTime(value) { time = value; queueMicrotask(() => this.onseeked?.()) }, get currentTime() { return time }, ...overrides }
  Object.defineProperty(globalThis, 'document', { configurable: true, value: { createElement: () => video, body: { append() {} } } })
  t.mock.method(URL, 'createObjectURL', () => 'blob:owned')
  t.mock.method(URL, 'revokeObjectURL', (url) => { assert.equal(url, 'blob:owned'); calls.revoked++ })
  return calls
}

test('guest decoder state checks reject invalid media and always stop/remove/revoke their local Blob', async (t) => {
  for (const overrides of [{}, { videoWidth: 853 }, { duration: NaN }, { readyState: 1 }]) {
    const calls = videoDOM(t, overrides)
    const value = await decodePublicVideo({ base64: Buffer.from('controlled bytes').toString('base64'), width: 832, height: 480, timeout: 20 })
    assert.equal(value.ok, Object.keys(overrides).length === 0)
    if (value.ok) assert.equal(value.playback.seekedSeconds, .5)
    else assert.equal(value.code, 'D3_PUBLIC_VIDEO_DECODE_FAILED')
    assert.deepEqual(calls, { revoked: 1, removed: 1, stopped: 1, loads: 1 })
  }
})
