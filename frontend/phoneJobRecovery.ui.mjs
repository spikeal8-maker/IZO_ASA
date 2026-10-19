// Mocked API/real Phone UI regression. The caller owns the browser and its process deadline.
import assert from 'node:assert/strict'

const JOBS = '/api/phone/v1/jobs'
const IMAGE_ID = 'phone-ui-owned-image', VIDEO_ID = 'phone-ui-owned-video'
const RESULT = '/phone-preview-placeholder.jpg'
const model = { id: 'server:local_flux_klein', label: 'Controlled image', provider: 'comfyui',
  modelProfile: 'local_flux_klein', tokenHint: 1, supportedResolutionIds: ['sq-hd'] }
const videoModel = { id: 'local/ltx-2.3-fast-q3', name: 'Controlled video', provider: 'local_ltx',
  supportedResolutions: ['480p'], supportedAspectRatios: ['16:9'], supportedDurations: [4],
  generateAudio: false, available: true, publicPricing: { fromTokens: 1 } }
const platform = { ok: true, apiVersion: 'v1', defaultRoute: '/phone/image',
  shell: { nativeReact: true, resumeJobs: true, offlineDrafts: true, notificationHost: true },
  contracts: { capabilities: 'v1', jobs: 'v1', media: 'v1', billing: 'v1' },
  workspaces: [['image', 'Картинка', 'Фото'], ['video', 'Видео', 'Видео']].map(([id, label, shortLabel]) =>
    ({ id, label, shortLabel, route: `/phone/${id}`, enabled: true, stage: 'ready', navigation: 'primary', operations: [] })) }

function job(modality, status = 'queued') {
  const terminal = ['completed', 'failed', 'cancelled', 'expired'].includes(status)
  return { id: modality === 'image' ? IMAGE_ID : VIDEO_ID, modality,
    operation: modality === 'image' ? 'text_to_image' : 'text_to_video', status,
    phase: terminal ? 'terminal' : status, progress: terminal ? 100 : status === 'queued' ? 10 : 42,
    terminal, message: terminal && status !== 'completed' ? 'Задание остановлено.' : '',
    createdAt: '2026-10-18T00:00:00Z', startedAt: null, completedAt: null,
    result: status === 'completed' ? { id: 'phone-ui-image-result', type: modality, url: RESULT,
      thumbnailUrl: RESULT, width: 16, height: 16, durationSeconds: null, aspectRatio: '1:1' } : null,
    billing: { chargedTokens: 1, tokenKind: 'daily', refunded: status === 'cancelled' } }
}

function deferred() {
  let resolve
  const promise = new Promise((done) => { resolve = done })
  return { promise, resolve }
}

async function within(promise, milliseconds) {
  let timer
  try {
    return await Promise.race([promise, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error('PHONE_UI_DEFERRED_TIMEOUT')), milliseconds)
    })])
  } finally { clearTimeout(timer) }
}

async function harness(browser, origin, width, modality, hold = false) {
  const context = await browser.newContext({ viewport: { width, height: width === 390 ? 844 : 932 }, serviceWorkers: 'block' })
  const state = { job: job(modality), requests: 0, reads: 0, lists: 0, generates: 0, closing: false,
    violations: [], hold: hold ? deferred() : null, readStarted: deferred(),
    recoveryUnavailable: false, recoveryFailures: 0, listGate: null, listStarted: deferred(),
    pollUnavailable: false, pollFailures: 0 }
  try {
    await context.addInitScript(() => {
      const original = window.fetch
      window.__phoneObservedReads = []
      window.fetch = function (input, init) {
        const url = new URL(input instanceof Request ? input.url : input, location.origin)
        if (/^\/api\/phone\/v1\/jobs\//.test(url.pathname)) {
          if (window.__phoneObservedReads.length >= 16) throw new Error('PHONE_UI_READ_LIMIT')
          const signal = init?.signal
          const item = { path: url.pathname, hasSignal: signal instanceof AbortSignal, aborted: signal?.aborted === true }
          window.__phoneObservedReads.push(item)
          signal?.addEventListener('abort', () => { item.aborted = true }, { once: true })
        }
        return Reflect.apply(original, this, [input, init])
      }
    })
    await context.route('**/*', async (route) => {
      const request = route.request(), url = new URL(request.url()), pathname = url.pathname
      const reject = async (code) => {
        if (state.violations.length < 16) state.violations.push(code)
        await route.abort('blockedbyclient')
      }
      if (url.origin !== origin) return reject('PHONE_UI_EXTERNAL_REQUEST')
      if (!pathname.startsWith('/api/')) return request.method() === 'GET' ? route.continue() : reject('PHONE_UI_STATIC_MUTATION')
      if (++state.requests > 64) return reject('PHONE_UI_API_REQUEST_LIMIT')
      const respond = (value, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(value) })
      if (pathname === '/api/generate' || pathname === '/api/video/generate') {
        state.generates++
        return respond({ error: 'PHONE_UI_UNEXPECTED_GENERATION' }, 409)
      }
      if (pathname === '/api/video/estimate' && request.method() === 'POST') return respond({ chargedTokens: 1 })
      if (request.method() !== 'GET') return reject('PHONE_UI_UNEXPECTED_MUTATION')
      if (pathname === '/api/phone/v1/platform') return respond(platform)
      if (pathname === '/api/me-v2') return respond({ profile: { display_name: 'Owned UI fixture' }, account: { token_balance: 20, daily_tokens_remaining: 20 } })
      if (pathname === JOBS) {
        state.lists++
        if (url.search !== '?active=true') return reject('PHONE_UI_ACTIVE_QUERY_INVALID')
        if (state.recoveryUnavailable) {
          state.recoveryFailures++
          return respond({ detail: 'Сервис временно недоступен.' }, 503)
        }
        if (state.listGate) { state.listStarted.resolve(); await state.listGate.promise }
        try { return await respond({ items: state.job.terminal ? [] : [state.job] }) }
        catch (error) {
          if (!state.closing && request.failure()?.errorText !== 'net::ERR_ABORTED') throw error
        }
        return
      }
      if (pathname === `${JOBS}/${state.job.id}`) {
        state.reads++
        state.readStarted.resolve()
        if (state.pollUnavailable) {
          state.pollFailures++
          return respond({ detail: 'Сервис временно недоступен.' }, 503)
        }
        if (state.hold) await state.hold.promise
        try { return await respond({ job: state.job }) }
        catch (error) {
          if (!state.closing && request.failure()?.errorText !== 'net::ERR_ABORTED') throw error
        }
        return
      }
      if (pathname.startsWith(`${JOBS}/`)) return reject('PHONE_UI_WRONG_JOB_ID')
      if (pathname === '/api/model-access') return respond({ plan: 'free', modes: { text_to_image: { models: [model], presets: { fast: model.id } } } })
      if (pathname === '/api/models') return respond({ loras: [] })
      if (pathname === '/api/gallery/items') return respond({ items: [] })
      if (pathname === '/api/video/config') return respond({ videoSlots: 2, modes: { text_to_video: [videoModel], image_to_video: [], first_last_frame: [], reference_to_video: [] } })
      if (pathname === '/api/video/history') return respond({ items: state.job.modality === 'video' ? [{
        ...state.job, mode: 'text_to_video', prompt: 'Owned deferred video', model: videoModel.id,
        duration: 4, resolution: '480p', aspectRatio: '16:9', tokenCost: 1, galleryDeleted: false,
      }] : [] })
      return reject('PHONE_UI_UNEXPECTED_API')
    })
    const page = await context.newPage()
    page.setDefaultTimeout(6000)
    page.setDefaultNavigationTimeout(10000)
    return { context, page, state, close: async () => { state.closing = true; state.hold?.resolve(); state.listGate?.resolve(); await context.close() } }
  } catch (error) { state.closing = true; state.hold?.resolve(); state.listGate?.resolve(); await context.close(); throw error }
}

async function recoverImage(browser, origin, width, terminal) {
  const run = await harness(browser, origin, width, 'image')
  const { page, state } = run
  try {
    await page.goto(`${origin}/phone/image`, { waitUntil: 'domcontentloaded' })
    await page.locator('.phone-image-busy').waitFor({ state: 'visible' })
    assert.equal(await page.locator('.phone-image-prompt button').isDisabled(), true)
    assert.equal(state.generates, 0)
    const before = state.reads
    state.job = job('image', 'processing')
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.locator('.phone-image-busy span').filter({ hasText: '42%' }).waitFor()
    assert.ok(state.reads > before)
    assert.equal(state.generates, 0)
    if (width === 430) {
      const previousLists = state.lists
      await page.evaluate(() => window.dispatchEvent(new Event('offline')))
      assert.equal(await page.locator('.phone-image-prompt button').isDisabled(), true)
      await Promise.all([
        page.waitForResponse((response) => new URL(response.url()).pathname === JOBS && response.status() === 200),
        page.evaluate(() => window.dispatchEvent(new Event('online'))),
      ])
      assert.ok(state.lists > previousLists)
      await page.locator('.phone-image-busy').waitFor()
    }
    state.job = job('image', terminal)
    await page.locator('.phone-image-busy').waitFor({ state: 'hidden' })
    if (terminal === 'completed') {
      const image = page.getByRole('img', { name: 'Результат генерации', exact: true })
      await image.waitFor()
      assert.equal(await image.getAttribute('src'), RESULT)
    } else await page.locator('.phone-image-error').filter({ hasText: 'Задание остановлено.' }).waitFor()
    await page.locator('.phone-image-prompt textarea').fill('A new owned draft, not submitted')
    assert.equal(await page.locator('.phone-image-prompt button').isDisabled(), false)
    assert.deepEqual(state.violations, [])
    assert.equal(state.generates, 0)
    return { case: `image-${width}-${terminal}`, status: 'PASS', sameJobId: IMAGE_ID, generatedRequests: 0 }
  } finally { await run.close() }
}

async function abortUnmount(browser, origin, width, modality) {
  const run = await harness(browser, origin, width, modality, true)
  const { page, state } = run
  try {
    await page.goto(`${origin}/phone/${modality}`, { waitUntil: 'domcontentloaded' })
    await within(state.readStarted.promise, 6000)
    await page.locator(`.phone-${modality}-busy`).waitFor()
    const path = `${JOBS}/${state.job.id}`
    assert.equal(await page.evaluate((value) => {
      const reads = window.__phoneObservedReads.filter((item) => item.path === value)
      return reads.length > 0 && reads.every((item) => item.hasSignal)
    }, path), true)
    const target = modality === 'image' ? 'Видео' : 'Фото'
    await page.locator('.phone-bottom-nav').getByRole('button', { name: target, exact: true }).click()
    await page.locator(`[data-phone-workspace="${modality}"]`).waitFor({ state: 'detached' })
    await page.waitForFunction((value) => {
      const reads = window.__phoneObservedReads.filter((item) => item.path === value)
      return reads.length > 0 && reads.every((item) => item.aborted)
    }, path)
    const reads = state.reads
    state.hold.resolve()
    await page.waitForTimeout(2100) // Exceeds both existing 1500/1800 ms polling intervals.
    assert.equal(state.reads, reads)
    assert.equal(state.generates, 0)
    assert.deepEqual(state.violations, [])
    return { case: `${modality}-${width}-spa-unmount`, status: 'PASS', signalAborted: true, furtherReads: 0 }
  } finally { await run.close() }
}

async function retryImageRecovery(browser, origin, width) {
  const run = await harness(browser, origin, width, 'image')
  const { page, state } = run
  state.recoveryUnavailable = true
  try {
    await page.goto(`${origin}/phone/image`, { waitUntil: 'domcontentloaded' })
    const retry = page.getByRole('button', { name: 'Повторить проверку заданий', exact: true })
    const generate = page.locator('.phone-image-prompt button')
    await retry.waitFor({ state: 'visible' })
    assert.ok(state.recoveryFailures > 0)
    await page.locator('.phone-image-prompt textarea').fill('Owned draft while checking the existing job')
    assert.equal(await generate.isDisabled(), true)
    assert.equal(state.reads, 0)
    await page.locator('.phone-image-error').getByRole('button', { name: 'Закрыть', exact: true }).click()
    await retry.waitFor({ state: 'visible' })
    const beforeRetry = state.lists
    state.recoveryUnavailable = false
    state.listGate = deferred()
    await page.waitForTimeout(300)
    assert.equal(state.lists, beforeRetry, 'Recovery needs the explicit recheck action')
    await Promise.all([within(state.listStarted.promise, 6000), retry.click()])
    assert.equal(state.lists, beforeRetry + 1)
    assert.equal(await generate.isDisabled(), true, 'A pending retry cannot permit a new generation')
    assert.equal(state.reads, 0)
    assert.equal(state.generates, 0)
    state.job = job('image', 'processing')
    state.listGate.resolve()
    await page.locator('.phone-image-busy span').filter({ hasText: '42%' }).waitFor()
    await within(state.readStarted.promise, 6000)
    assert.equal(await generate.isDisabled(), true)
    assert.equal(state.generates, 0)
    state.pollUnavailable = true
    await retry.waitFor({ state: 'visible' })
    assert.ok(state.pollFailures > 0)
    assert.equal(await generate.isDisabled(), true, 'A failed poll cannot permit another generation')
    const beforePollRetry = state.lists
    state.pollUnavailable = false
    state.listGate = deferred()
    state.listStarted = deferred()
    await Promise.all([within(state.listStarted.promise, 6000), retry.click()])
    assert.equal(state.lists, beforePollRetry + 1)
    assert.equal(await generate.isDisabled(), true)
    assert.equal(state.generates, 0)
    await Promise.all([
      page.waitForResponse((response) => new URL(response.url()).pathname === `${JOBS}/${IMAGE_ID}` && response.status() === 200),
      Promise.resolve().then(() => state.listGate.resolve()),
    ])
    await page.locator('.phone-image-busy span').filter({ hasText: '42%' }).waitFor()
    assert.equal(await generate.isDisabled(), true)
    state.job = job('image', 'completed')
    await page.locator('.phone-image-busy').waitFor({ state: 'hidden' })
    const image = page.getByRole('img', { name: 'Результат генерации', exact: true })
    await image.waitFor()
    assert.equal(await image.getAttribute('src'), RESULT)
    assert.equal(await generate.isDisabled(), false)
    assert.deepEqual(state.violations, [])
    assert.equal(state.generates, 0)
    return { case: `image-${width}-recovery-retry`, status: 'PASS', sameJobId: IMAGE_ID,
      generatedRequests: 0, recoveryRetried: true, pollingRetried: true }
  } finally { await run.close() }
}

async function observedCase(caseName, action) {
  try { return await action() }
  catch (error) {
    const line = Number(String(error?.stack || '').slice(0, 8192).match(/phoneJobRecovery\.ui\.mjs:(\d+):\d+/)?.[1] || 0)
    const kind = error?.name === 'TimeoutError' ? 'TIMEOUT' : error?.code === 'ERR_ASSERTION' ? 'ASSERTION' : 'ERROR'
    throw Object.assign(new Error('D3_PHONE_UI_CHECK_FAILED'), { phoneUiFailure: {
      case: caseName, kind, sourceLine: Number.isInteger(line) && line > 0 && line <= 500 ? line : 0,
    } })
  }
}

export async function provePhoneJobRecoveryUI(browser, { origin }) {
  const url = new URL(origin)
  assert.ok(url.origin === origin && url.protocol === 'http:' && url.hostname === '127.0.0.1' && Number(url.port) > 1024)
  const cases = []
  for (const width of [390, 430]) {
    cases.push(await observedCase(`image-${width}-completed`, () => recoverImage(browser, origin, width, 'completed')))
    cases.push(await observedCase(`image-${width}-cancelled`, () => recoverImage(browser, origin, width, 'cancelled')))
    for (const modality of ['image', 'video']) cases.push(await observedCase(`${modality}-${width}-spa-unmount`, () => abortUnmount(browser, origin, width, modality)))
    cases.push(await observedCase(`image-${width}-recovery-retry`, () => retryImageRecovery(browser, origin, width)))
  }
  return { status: 'PASS', evidenceClass: 'mocked-api-real-phone-ui', modelExecution: false,
    acceleratorExecution: false, uiCancellation: 'NOT_SUPPORTED', installedAcceptance: 'NOT_VERIFIED', cases }
}
