// Bounds captured API/media bytes; this is not a Chromium process memory limit.
import { ensure } from './docker_d3_browser_contracts.mjs'

export const LIMITS = Object.freeze({ json: 65536, error: 2048, privateMedia: 1048576,
  publicMedia: 2097152, totalBytes: 16777216, direct: 200, http: 400, captures: 16, timeout: 8000 })

// Self-contained for page.evaluate: HttpOnly cookies and Set-Cookie stay in the native browser jar.
export async function fetchInPage({ route, method, data, expected, maxBytes, json = false, timeout = 8000 }) {
  const fail = (code) => { throw new Error(code) }
  const controller = new AbortController()
  let reader, responseBody, timer
  const started = performance.now()
  try {
    if (!Number.isInteger(maxBytes) || maxBytes < 0 || maxBytes > 2097152
      || !Number.isInteger(timeout) || timeout < 1 || timeout > 8000
      || !['GET', 'POST'].includes(method) || typeof route !== 'string' || !route.startsWith('/api/')
      || route.includes('\\') || new URL(route, location.origin).origin !== location.origin) fail('D3_TRANSPORT_INPUT_INVALID')
    const deadline = new Promise((_, reject) => { timer = setTimeout(() => {
      controller.abort(); reject(new Error('D3_TRANSPORT_TIMEOUT'))
    }, timeout) })
    const work = (async () => {
      const reply = await fetch(route, { method, credentials: 'include', redirect: 'error',
        signal: controller.signal, headers: data === undefined ? {} : { 'Content-Type': 'application/json' },
        body: data === undefined ? undefined : JSON.stringify(data) })
      responseBody = reply.body
      if (controller.signal.aborted || performance.now() - started >= timeout) {
        void responseBody?.cancel().catch(() => {}); fail('D3_TRANSPORT_TIMEOUT')
      }
      if (reply.status !== expected) fail(`D3_HTTP_${reply.status}`)
      if (!maxBytes) return { ok: true, bytes: 0, base64: '' }
      const declared = reply.headers.get('content-length')
      if (declared !== null && (!/^\d{1,10}$/.test(declared) || Number(declared) > maxBytes)) fail('D3_RESPONSE_TOO_LARGE')
      if (json && !/^application\/json(?:\s*;|$)/i.test(reply.headers.get('content-type') || '')) fail('D3_RESPONSE_NOT_JSON')
      if (!reply.body) fail('D3_RESPONSE_BODY_MISSING')
      reader = reply.body.getReader()
      const chunks = []
      let size = 0
      while (true) {
        const { done, value } = await reader.read()
        if (controller.signal.aborted || performance.now() - started >= timeout) fail('D3_TRANSPORT_TIMEOUT')
        if (done) break
        if (!(value instanceof Uint8Array) || value.byteLength > maxBytes - size) fail('D3_RESPONSE_TOO_LARGE')
        size += value.byteLength; chunks.push(value)
      }
      const bytes = new Uint8Array(size)
      let offset = 0, binary = ''
      for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length }
      for (let index = 0; index < size; index += 8192) binary += String.fromCharCode(...bytes.subarray(index, index + 8192))
      return { ok: true, bytes: size, base64: btoa(binary) }
    })()
    return await Promise.race([deadline, work])
  } catch (error) {
    const code = String(error?.message || '')
    return { ok: false, code: /^D3_[A-Z0-9_]{2,100}$/.test(code) ? code : 'D3_TRANSPORT_FAILED' }
  } finally {
    clearTimeout(timer); controller.abort()
    if (reader) {
      try { void reader.cancel().catch(() => {}).finally(() => { try { reader.releaseLock() } catch {} }) } catch {}
      try { reader.releaseLock() } catch {}
    } else { try { void responseBody?.cancel().catch(() => {}) } catch {} }
  }
}

const parseJSON = (bytes) => {
  try { return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)) }
  catch { throw new Error('D3_RESPONSE_JSON_INVALID') }
}

// UI fetches are real application requests. Admit identity Content-Length before Playwright body().
export async function capturedJSON(reply, maximum = LIMITS.json) {
  const headers = reply.headers(), length = headers['content-length'], encoding = headers['content-encoding']
  ensure(typeof length === 'string' && /^\d{1,10}$/.test(length) && Number(length) <= maximum
    && (!encoding || encoding.toLowerCase() === 'identity')
    && /^application\/json(?:\s*;|$)/i.test(headers['content-type'] || ''), 'D3_CAPTURE_BODY_NOT_BOUNDED')
  const bytes = await reply.body()
  ensure(bytes instanceof Uint8Array && bytes.length === Number(length) && bytes.length <= maximum,
    'D3_CAPTURE_LENGTH_MISMATCH')
  return { value: parseJSON(bytes), bytes: bytes.length }
}

export class CaptureBudget {
  directRequests = 0; cleanupRequests = 0; httpRequests = 0; cleanupHttpRequests = 0
  captures = 0; bytes = 0; reserved = 0
  request(kind, cleanup = false) {
    const key = kind === 'http' ? (cleanup ? 'cleanupHttpRequests' : 'httpRequests')
      : (cleanup ? 'cleanupRequests' : 'directRequests')
    const limit = cleanup ? 4 : kind === 'http' ? LIMITS.http : LIMITS.direct
    ensure(this[key] < limit, 'D3_REQUEST_LIMIT'); this[key]++
  }
  reserve(maximum) {
    ensure(Number.isSafeInteger(maximum) && maximum > 0 && maximum <= LIMITS.publicMedia, 'D3_CAPTURE_CAP_INVALID')
    const capacity = Math.min(maximum, LIMITS.totalBytes - this.bytes - this.reserved)
    ensure(capacity > 0, 'D3_CAPTURE_BYTE_LIMIT'); this.reserved += capacity
    return capacity
  }
  release(capacity, consumed = 0) {
    ensure(Number.isSafeInteger(consumed) && consumed >= 0 && consumed <= capacity, 'D3_CAPTURE_BYTE_LIMIT')
    this.reserved -= capacity; this.bytes += consumed
  }
}

export class BrowserIO {
  budget = new CaptureBudget(); pages = new WeakMap(); cleaning = false; violation = null
  constructor(browser, origin, runId, expired) {
    this.browser = browser; this.origin = origin; this.transportPath = `/__d3_transport_${runId}`; this.expired = expired
  }
  async context() {
    const context = await this.browser.newContext({ viewport: { width: 390, height: 844 }, serviceWorkers: 'block',
      extraHTTPHeaders: { 'Accept-Encoding': 'identity' } })
    await context.route('**/*', async (route) => {
      try {
        const request = route.request(), url = new URL(request.url())
        const cleanup = this.cleaning && url.origin === this.origin && request.frame().page() === this.pages.get(context)
          && ((request.method() === 'POST' && url.pathname === '/api/auth/session/logout-v2')
            || (request.method() === 'GET' && url.pathname === '/api/me-v2')) && !url.search
        if (['http:', 'https:'].includes(url.protocol)) this.budget.request('http', cleanup)
        if (this.cleaning && !cleanup) return await route.abort('blockedbyclient')
        if (url.origin === this.origin && url.pathname === this.transportPath && !url.search
          && request.isNavigationRequest() && request.resourceType() === 'document') {
          return await route.fulfill({ status: 200, contentType: 'text/html', body: '<!doctype html><title>D3 transport</title>' })
        }
        if (url.origin === this.origin || ['data:', 'blob:'].includes(url.protocol)) return await route.continue()
        await route.abort('blockedbyclient')
      } catch {
        this.violation = 'D3_BROWSER_REQUEST_GUARD_FAILED'
        try { await route.abort('blockedbyclient') } catch {}
      }
    })
    const page = await context.newPage()
    this.pages.set(context, page)
    await page.goto(this.origin + this.transportPath, { waitUntil: 'domcontentloaded', timeout: LIMITS.timeout })
    return context
  }
  async read(client, method, route, data, expected = 200, maximum = 0, json = false) {
    const cleanup = this.cleaning && ((method === 'POST' && route === '/api/auth/session/logout-v2')
      || (method === 'GET' && route === '/api/me-v2')) && maximum === 0
    ensure(this.pages.has(client) && (cleanup || (!this.cleaning && !this.expired() && !this.violation))
      && typeof route === 'string' && route.startsWith('/api/') && !route.includes('\\')
      && new URL(route, this.origin).origin === this.origin
      && (data === undefined || Buffer.byteLength(JSON.stringify(data)) <= 16384), 'D3_REQUEST_NOT_ADMITTED')
    this.budget.request('direct', cleanup)
    const capacity = maximum ? this.budget.reserve(maximum) : 0
    let consumed = 0
    try {
      const value = await this.pages.get(client).evaluate(fetchInPage,
        { route, method, data, expected, maxBytes: capacity, json })
      ensure(value?.ok === true, /^D3_[A-Z0-9_]{2,100}$/.test(value?.code || '') ? value.code : 'D3_TRANSPORT_FAILED')
      ensure(Number.isInteger(value.bytes) && value.bytes >= 0 && value.bytes <= capacity
        && typeof value.base64 === 'string' && value.base64.length <= Math.ceil(capacity / 3) * 4, 'D3_TRANSPORT_RESULT_INVALID')
      const bytes = Buffer.from(value.base64, 'base64')
      ensure(bytes.length === value.bytes && (this.cleaning || !this.expired()), 'D3_TRANSPORT_RESULT_INVALID')
      consumed = bytes.length; return bytes
    } finally { this.budget.release(capacity, consumed) }
  }
  async api(client, method, route, data, expected = 200) {
    return parseJSON(await this.read(client, method, route, data, expected, expected >= 400 ? LIMITS.error : LIMITS.json, true))
  }
  async capture(reply, expected = 200) {
    ensure(reply.status() === expected && !this.expired() && ++this.budget.captures <= LIMITS.captures,
      'D3_CAPTURE_NOT_ADMITTED')
    const capacity = this.budget.reserve(LIMITS.json)
    let consumed = 0
    try {
      const value = await capturedJSON(reply, capacity)
      ensure(!this.expired(), 'D3_BROWSER_DEADLINE_EXCEEDED')
      consumed = value.bytes; return value.value
    } finally { this.budget.release(capacity, consumed) }
  }
  requestJSON(reply) {
    const value = reply.request().postData()
    ensure(typeof value === 'string' && Buffer.byteLength(value) <= 16384, 'D3_UI_REQUEST_TOO_LARGE')
    return parseJSON(Buffer.from(value))
  }
  beginCleanup() { this.cleaning = true }
  counts() {
    return { apiRequests: this.budget.directRequests + this.budget.cleanupRequests,
      browserHttpRequests: this.budget.httpRequests + this.budget.cleanupHttpRequests,
      capturedResponses: this.budget.captures, capturedBytes: this.budget.bytes,
      chromiumMemoryLimit: 'NOT_VERIFIED' }
  }
}

// Decode the bounded bytes already fetched as the guest; no second network URL or provider call.
export async function decodePublicVideo({ base64, width, height, timeout = 8000 }) {
  let video, url, timer
  try {
    if (typeof base64 !== 'string' || base64.length > 2796204 || timeout < 1 || timeout > 8000) throw new Error()
    const raw = atob(base64), bytes = Uint8Array.from(raw, (character) => character.charCodeAt(0))
    if (bytes.length > 2097152) throw new Error()
    url = URL.createObjectURL(new Blob([bytes], { type: 'video/mp4' }))
    video = document.createElement('video'); video.muted = true; video.preload = 'auto'
    const work = new Promise((resolve, reject) => {
      video.onerror = () => reject(new Error())
      video.onloadeddata = () => {
        if (video.videoWidth !== width || video.videoHeight !== height || !Number.isFinite(video.duration)
          || video.duration <= 2 || video.duration >= 2.2) return reject(new Error())
        video.onseeked = () => video.readyState >= 2 && Math.abs(video.currentTime - .5) < .05
          ? resolve({ width: video.videoWidth, height: video.videoHeight, duration: video.duration, seekedSeconds: video.currentTime })
          : reject(new Error())
        video.currentTime = .5
      }
      video.src = url; document.body.append(video)
    })
    return { ok: true, playback: await Promise.race([work, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error()), timeout) })]) }
  } catch { return { ok: false, code: 'D3_PUBLIC_VIDEO_DECODE_FAILED' } }
  finally {
    clearTimeout(timer)
    if (video) { video.onloadeddata = video.onerror = video.onseeked = null; video.pause(); video.removeAttribute('src'); video.load(); video.remove() }
    if (url) URL.revokeObjectURL(url)
  }
}
