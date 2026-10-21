import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

const localPort = 5198
const localOrigin = `http://127.0.0.1:${localPort}`
const baseUrl = process.env.IZO_E2E_BASE_URL || `${localOrigin}/#text-to-image`
const pixel = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2n0kAAAAASUVORK5CYII='

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

async function waitForPreview(url) {
  const deadline = Date.now() + 20_000
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url)
      if (response.ok) return
    } catch {
      // Preview is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 200))
  }
  throw new Error(`preview did not start at ${url}`)
}

function galleryPayload(kind) {
  if (kind === 'malformed') return { items: [null, 7, {}, { id: 'missing-media' }] }
  return {
    items: [
      {
        id: 'new-contract',
        viewerSrc: pixel,
        downloadUrl: pixel,
        thumbnailUrl: pixel,
        promptOriginal: 'Новый контракт галереи',
        width: 1024,
        height: 1024,
      },
      {
        id: 'legacy-contract',
        url: pixel,
        thumbnailUrl: pixel,
        promptOriginal: 'Старый контракт галереи',
        width: 1024,
        height: 768,
      },
      {
        thumbnailUrl: pixel,
        prompt: 'Запись без идентификатора',
        width: 768,
        height: 1024,
      },
      null,
      { id: 'broken-without-media' },
    ],
  }
}

async function installApiFixtures(context, kind) {
  await context.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    if (kind === 'backend-unavailable') {
      await route.abort('connectionrefused')
      return
    }
    if (url.pathname === '/api/gallery/items') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(galleryPayload(kind)) })
      return
    }
    if (url.pathname === '/api/feed') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [] }) })
      return
    }
    if (url.pathname === '/api/auth/capabilities-v2') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ capabilities_loaded: true }) })
      return
    }
    await route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ detail: 'test guest' }) })
  })
}

async function openStudio(browser, kind) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  await installApiFixtures(context, kind)
  const pageErrors = []
  const page = await context.newPage()
  page.on('pageerror', (error) => pageErrors.push(String(error)))
  await page.goto(baseUrl, { waitUntil: 'domcontentloaded' })
  await page.locator('.prompt-section textarea').waitFor({ state: 'visible' })
  assert(!await page.getByText('Студия временно остановлена').count(), `${kind}: root ErrorBoundary is visible`)
  assert(pageErrors.length === 0, `${kind}: page errors: ${pageErrors.join(' | ')}`)
  return { context, page, pageErrors }
}

async function verifyIsolatedFailure(browser, region, survivingSelector) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  await installApiFixtures(context, 'mixed')
  await context.addInitScript((failedRegion) => {
    window.sessionStorage.setItem('izo:e2e:fail-region', failedRegion)
  }, region)
  const page = await context.newPage()
  await page.goto(baseUrl, { waitUntil: 'domcontentloaded' })
  const fallback = page.locator(`[data-runtime-region="${region}"]`).filter({ hasText: 'временно недоступен' })
  await fallback.waitFor({ state: 'visible' })
  assert(!await page.getByText('Студия временно остановлена').count(), `${region}: local failure reached root ErrorBoundary`)
  await page.locator(survivingSelector).waitFor({ state: 'visible' })
  await fallback.getByRole('button', { name: 'Повторить' }).click()
  await page.locator(`[data-studio-region="${region}"]`).waitFor({ state: 'visible' })
  assert(!await page.getByText('Студия временно остановлена').count(), `${region}: retry reached root ErrorBoundary`)
  await context.close()
}

let previewProcess
if (!process.env.IZO_E2E_BASE_URL) {
  const viteBin = fileURLToPath(new URL('./node_modules/vite/bin/vite.js', import.meta.url))
  previewProcess = spawn(process.execPath, [viteBin, 'preview', '--host', '127.0.0.1', '--port', String(localPort), '--strictPort'], {
    cwd: fileURLToPath(new URL('.', import.meta.url)),
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  await waitForPreview(localOrigin)
}

const browser = await chromium.launch({ headless: true })
try {
  const { context, page } = await openStudio(browser, 'mixed')
  await context.addInitScript((draft) => {
    window.sessionStorage.setItem('izo:studio-draft-v2:guest', JSON.stringify({ version: 2, savedAt: Date.now(), draft }))
  }, {
    prompts: { text: 'Черновик должен сохраниться', i2i: '', edit: '', paint: '' },
    styleId: '',
    resolutionId: 'h-1280',
    quality: 'standard',
    seed: 424242,
    strengthPct: 63,
    editSlots: Array.from({ length: 4 }, () => ({ role: '', takeNote: '' })),
    editFaceStrengthPct: 75,
  })
  await page.reload({ waitUntil: 'domcontentloaded' })
  const textarea = page.locator('.prompt-section textarea')
  await textarea.waitFor({ state: 'visible' })
  await page.waitForFunction(() => document.querySelector('.prompt-section textarea')?.value === 'Черновик должен сохраниться', null, { timeout: 10000 })

  const activeQuality = page.locator('.quality-button.active')
  assert(await activeQuality.count() === 1, 'exactly one quality button must be active')
  assert((await activeQuality.locator('.quality-label').textContent())?.includes('Стандарт'), 'standard quality was not restored')
  const activeModel = activeQuality.locator('.quality-model-name')
  const beforeHover = await activeModel.evaluate((node) => getComputedStyle(node).color)
  assert(!beforeHover.includes('rgba(0, 0, 0, 0)'), `active model label is transparent: ${beforeHover}`)
  await activeQuality.hover()
  const afterHover = await activeModel.evaluate((node) => getComputedStyle(node).color)
  assert(!afterHover.includes('rgba(0, 0, 0, 0)'), `hovered model label is transparent: ${afterHover}`)

  const selectedFormat = page.locator('.iv3-format-option.active')
  if (await selectedFormat.count() === 1) {
    assert((await selectedFormat.textContent())?.includes('1280×720'), 'wide format was not restored')
  }
  const historyImages = page.locator('.history-item img')
  await historyImages.first().waitFor({ state: 'visible' })
  assert(await historyImages.count() === 3, `mixed: expected 3 normalized history images, got ${await historyImages.count()}`)
  assert(!await page.getByText('Студия временно остановлена').count(), 'mixed: studio crashed after gallery render')
  await context.close()

  const malformed = await openStudio(browser, 'malformed')
  assert(await malformed.page.locator('.history-item img').count() === 0, 'malformed: invalid gallery records were rendered')
  assert(!await malformed.page.getByText('Студия временно остановлена').count(), 'malformed: invalid gallery records crashed studio')
  await malformed.context.close()

  const unavailable = await openStudio(browser, 'backend-unavailable')
  assert(!await unavailable.page.getByText('Студия временно остановлена').count(), 'backend-unavailable: studio crashed')
  assert(await unavailable.page.locator('.prompt-section textarea').isVisible(), 'backend-unavailable: prompt is not usable')
  await unavailable.context.close()

  await verifyIsolatedFailure(browser, 'studio-form', '[data-studio-region="preview"]')
  await verifyIsolatedFailure(browser, 'preview', '[data-studio-region="studio-form"]')
  await verifyIsolatedFailure(browser, 'history', '[data-studio-region="preview"]')

  console.log(JSON.stringify({
    ok: true,
    beforeHover,
    afterHover,
    baseUrl,
    galleryContracts: ['new', 'legacy', 'missing-id', 'malformed'],
    networkFailures: ['backend-unavailable', 'guest-401'],
    isolatedFailures: ['studio-form', 'preview', 'history'],
  }))
} finally {
  await browser.close()
  if (previewProcess && !previewProcess.killed) previewProcess.kill()
}
