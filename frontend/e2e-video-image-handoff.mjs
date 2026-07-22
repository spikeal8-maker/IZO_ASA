import { spawn } from 'node:child_process'
import { mkdir, readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { resolve } from 'node:path'
import { chromium } from 'playwright'

const localPort = 5203
const localOrigin = `http://127.0.0.1:${localPort}`
const base = process.env.PRODUCT_VIDEO_E2E_BASE_URL || localOrigin
const root = fileURLToPath(new URL('..', import.meta.url))
const evidenceDir = process.env.PRODUCT_VIDEO_E2E_SCREENSHOT_DIR || resolve(root, '.runtime', 'evidence', 'PRODUCT-VIDEO-001')
const galleryRoot = resolve(root, 'backend', 'static', 'gallery')
const galleryHtml = await readFile(resolve(galleryRoot, 'index.html'), 'utf8')
const galleryCss = await readFile(resolve(galleryRoot, 'gallery.css'), 'utf8')
const galleryJs = await readFile(resolve(galleryRoot, 'gallery.js'), 'utf8')

const sourceSvg = Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="900" height="1600" viewBox="0 0 900 1600"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#24124f"/><stop offset=".48" stop-color="#8f3f9f"/><stop offset="1" stop-color="#d7f426"/></linearGradient></defs><rect width="900" height="1600" fill="url(#g)"/><circle cx="450" cy="560" r="250" fill="#141d18" opacity=".64"/><path d="M210 1280c120-300 360-300 480 0" fill="#111912" opacity=".8"/><text x="450" y="1450" text-anchor="middle" fill="#f7ffe7" font-family="Arial" font-size="58" font-weight="700">IZO ASA</text></svg>`)

const model = {
  id: 'video/product-test',
  name: 'ИЗО Видео Test',
  description: 'Fixture model',
  supportedResolutions: ['720p', '1080p'],
  supportedAspectRatios: ['16:9', '9:16', '1:1', '4:3'],
  supportedDurations: [5, 8],
  supportedFrameImages: ['first_frame'],
  generateAudio: true,
  publicPricing: { fromTokens: 10, examples: [{ duration: 5, resolution: '720p', aspectRatio: '9:16', tokens: 10 }] },
}
const image = {
  id: 'gallery-animate-1',
  imageId: 'gallery-animate-1',
  mediaType: 'image',
  url: '/api/media/product-video/source.png',
  viewerSrc: '/api/media/product-video/source.png',
  downloadUrl: '/api/media/product-video/source.png',
  thumbnailUrl: '/api/media/product-video/thumb.png',
  promptOriginal: 'Портрет в мягком свете на фоне вечернего города',
  width: 900,
  height: 1600,
  mode: 'text_to_image',
  createdAt: '2026-07-22T10:00:00Z',
}
const galleryVideo = {
  id: 'gallery-video-1',
  mediaType: 'video',
  videoUrl: '/api/video/media/gallery-video-1',
  viewerSrc: '/api/video/media/gallery-video-1',
  thumbnailUrl: '/api/media/product-video/thumb.png',
  promptOriginal: 'Fixture video',
  width: 1280,
  height: 720,
  duration: 5,
  mode: 'text_to_video',
  createdAt: '2026-07-22T10:05:00Z',
}
const me = {
  internal_user_id: 'product-video-user',
  legacy_user_id: 'product-video-user',
  status: 'active',
  account: { role: 'user', plan: 'business', token_balance: 500, daily_tokens_limit: 500, daily_tokens_remaining: 500, gallery_access: true },
  session: { provider: 'web_email', platform: 'web_desktop', expires_at: '2099-01-01T00:00:00Z', refresh_expires_at: '2099-02-01T00:00:00Z' },
  identities: [],
  profile: { display_name: 'Video Product QA', language_code: 'ru', providers: ['web_email'] },
}

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

async function waitForPreview(url) {
  const deadline = Date.now() + 20_000
  while (Date.now() < deadline) {
    try { if ((await fetch(url)).ok) return } catch { /* preview is starting */ }
    await new Promise((resolveWait) => setTimeout(resolveWait, 200))
  }
  throw new Error(`preview did not start at ${url}`)
}

async function installFixtures(context, { missingMedia = false } = {}) {
  const state = { generateRequests: 0, useAsRequests: 0, privateMediaRequests: 0 }
  await context.route(`${base}/gallery`, (route) => route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: galleryHtml }))
  await context.route('**/static/gallery/gallery.css*', (route) => route.fulfill({ status: 200, contentType: 'text/css; charset=utf-8', body: galleryCss }))
  await context.route('**/static/gallery/gallery.js*', (route) => route.fulfill({ status: 200, contentType: 'text/javascript; charset=utf-8', body: galleryJs }))
  await context.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    const method = route.request().method()
    if (url.pathname.startsWith('/api/media/')) {
      state.privateMediaRequests += 1
      if (missingMedia && url.pathname.endsWith('/missing.png')) return route.fulfill({ status: 404, json: { detail: 'not found' } })
      return route.fulfill({ status: 200, contentType: 'image/svg+xml', body: sourceSvg })
    }
    if (url.pathname === '/api/auth/bootstrap-v2') return route.fulfill({ json: { installation_id: 'product-video', anonymous_id: 'product-video' } })
    if (url.pathname === '/api/auth/capabilities-v2') return route.fulfill({ json: { password_login_available: true, email_otp_available: true, bot_login: {} } })
    if (url.pathname === '/api/auth/session/refresh-v2') return route.fulfill({ json: { ok: true } })
    if (url.pathname === '/api/me-v2') return route.fulfill({ json: me })
    if (url.pathname === '/api/gallery/items') return route.fulfill({ json: { items: [image, galleryVideo], limits: { originals: { used: 1, limit: 50 }, videos: { used: 1, limit: 50 }, feed: { used: 0, limit: 50 }, favorites: { used: 0, limit: 50 }, plan: 'business' }, capabilities: { videoFeedPublication: true }, hasMore: false } })
    if (url.pathname === '/api/gallery/secondary') return route.fulfill({ json: { feedItems: [], uploadedItems: [], uploadedUnavailableCount: 0 } })
    if (url.pathname === `/api/gallery/${image.id}/use-as` && method === 'POST') {
      state.useAsRequests += 1
      return route.fulfill({ json: { ok: true, imageId: image.id, target: 'image', inputImage: image.url, prompt: image.promptOriginal, width: image.width, height: image.height } })
    }
    if (url.pathname === `/api/gallery/${image.id}`) return route.fulfill({ json: { ...image, sources: [] } })
    if (url.pathname === '/api/video/config') return route.fulfill({ json: { modes: { text_to_video: [model], image_to_video: [model], first_last_frame: [model], reference_to_video: [model] }, plan: 'business', videoSlots: 50, feedPublicationEnabled: true, economy: { tokenRub: 5, minMarginPercent: 40 }, availability: {} } })
    if (url.pathname === '/api/video/history') return route.fulfill({ json: { items: [] } })
    if (url.pathname === '/api/video/estimate') return route.fulfill({ json: { chargedTokens: 10 } })
    if (url.pathname === '/api/video/generate') { state.generateRequests += 1; return route.fulfill({ status: 500, json: { detail: 'generation must not run in handoff E2E' } }) }
    if (url.pathname === '/api/feed') return route.fulfill({ json: { items: [] } })
    if (url.pathname === '/api/tariffs') return route.fulfill({ json: { tariffs: {} } })
    if (url.pathname === '/api/models') return route.fulfill({ json: { ok: true, profiles: [] } })
    if (url.pathname === '/api/model-access') return route.fulfill({ json: { models: [] } })
    return route.fulfill({ json: { ok: true, items: [] } })
  })
  await context.route('**/api/video/media/**', (route) => route.fulfill({ status: 200, contentType: 'video/mp4', body: Buffer.alloc(0) }))
  return state
}

async function assertVideoSourceApplied(page, state, placement) {
  await page.waitForURL('**/video')
  await page.locator('.video-studio').waitFor({ state: 'visible' })
  const mode = placement === 'desktop'
    ? page.locator('.video-mode-tabs button[aria-selected="true"]')
    : page.locator('.video-mobile-mode-trigger')
  assert((await mode.textContent())?.includes('Изображение → видео'), `${placement}: image_to_video mode was not selected`)
  const source = page.locator(`.video-${placement}-inputs .video-source.filled img`)
  await source.waitFor({ state: 'visible' })
  assert((await source.getAttribute('src'))?.includes('/api/media/product-video/source.png'), `${placement}: first-frame URL was not applied`)
  const dimensions = await source.evaluate((element) => ({ width: element.naturalWidth, height: element.naturalHeight, fit: getComputedStyle(element).objectFit }))
  assert(dimensions.width === 900 && dimensions.height === 1600 && dimensions.fit === 'contain', `${placement}: source aspect ratio preview was not preserved`)
  await page.getByText('Исходный кадр добавлен', { exact: true }).waitFor({ state: 'visible' })
  assert(await page.locator('.video-prompt textarea').inputValue() === 'Плавно оживи изображение. Сохрани внешность, форму объектов и композицию. Добавь естественное движение камеры, света и деталей окружения.', `${placement}: starter prompt was not applied`)
  assert((await page.locator('.video-format-tabs button.active').textContent())?.includes('9:16'), `${placement}: closest source aspect ratio was not selected`)
  assert(await page.evaluate(() => sessionStorage.getItem('izo:video-source-v1')) === null, `${placement}: handoff was not consumed`)
  assert(state.privateMediaRequests >= 1, `${placement}: private image was not reverified`)
  assert(state.generateRequests === 0, `${placement}: generation started automatically`)
}

async function runGalleryFlow(browser, viewport, placement) {
  const context = await browser.newContext({ viewport, isMobile: placement === 'mobile', hasTouch: placement === 'mobile' })
  const state = await installFixtures(context)
  const page = await context.newPage()
  await page.goto(`${base}/gallery`, { waitUntil: 'domcontentloaded' })
  await page.locator('.card.videoCard').click()
  await page.locator('#viewer.open').waitFor()
  assert(!await page.locator('#animateBtn').isVisible(), `${placement}: animate action is visible for a video file`)
  await page.locator('#viewerClose').click()
  await page.locator('.card:not(.videoCard)').first().click()
  await page.locator('#viewer.open').waitFor()
  const animate = page.locator('#animateBtn')
  await animate.waitFor({ state: 'visible' })
  await page.waitForFunction(() => (document.querySelector('#viewerImg')?.naturalWidth || 0) > 0)
  const animateBox = await animate.boundingBox()
  assert(animateBox && animateBox.x >= 0 && animateBox.x + animateBox.width <= viewport.width + 1, `${placement}: gallery animate action overflows the viewport`)
  if (placement === 'desktop') {
    const zoomInBox = await page.locator('#desktopZoomInBtn').boundingBox()
    assert(zoomInBox && zoomInBox.x + zoomInBox.width <= viewport.width + 1, 'desktop: gallery zoom controls overflow the viewport')
  }
  await page.screenshot({ path: resolve(evidenceDir, `gallery-animate-${placement}.png`) })
  await animate.click()
  await assertVideoSourceApplied(page, state, placement)
  assert(state.useAsRequests === 1, `${placement}: gallery owner-check use-as call was not made exactly once`)
  await page.screenshot({ path: resolve(evidenceDir, `gallery-to-video-${placement}.png`) })
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.locator('.video-studio').waitFor({ state: 'visible' })
  assert(await page.locator(`.video-${placement}-inputs .video-source.filled img`).count() === 0, `${placement}: consumed handoff was reapplied after reload`)
  assert(state.generateRequests === 0, `${placement}: reload started generation`)
  await context.close()
}

async function runStudioResultFlow(browser, viewport, placement) {
  const context = await browser.newContext({ viewport, isMobile: placement === 'mobile', hasTouch: placement === 'mobile' })
  const state = await installFixtures(context)
  const page = await context.newPage()
  await page.goto(`${base}/`, { waitUntil: 'domcontentloaded' })
  const actions = page.locator('.iv3 .image-actions')
  await actions.waitFor({ state: 'visible' })
  await actions.scrollIntoViewIfNeeded()
  const animate = actions.getByRole('button', { name: 'Оживить' })
  await animate.waitFor({ state: 'visible' })
  const actionBox = await actions.boundingBox()
  assert(actionBox && actionBox.x >= 0 && actionBox.x + actionBox.width <= viewport.width + 1, `${placement}: result actions overflow the viewport`)
  await page.screenshot({ path: resolve(evidenceDir, `studio-result-animate-${placement}.png`) })
  await animate.click()
  await assertVideoSourceApplied(page, state, placement)
  assert(state.useAsRequests === 0, `${placement}: Studio result unexpectedly called gallery use-as`)
  assert(state.generateRequests === 0, `${placement}: Studio handoff started generation`)
  await context.close()
}

async function runUnavailableSourceFlow(browser) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  await context.addInitScript(() => sessionStorage.setItem('izo:video-source-v1', JSON.stringify({ version: 1, createdAt: Date.now(), galleryImageId: 'missing', mediaUrl: '/api/media/product-video/missing.png', width: 900, height: 1600 })))
  const state = await installFixtures(context, { missingMedia: true })
  const page = await context.newPage()
  await page.goto(`${base}/video`, { waitUntil: 'domcontentloaded' })
  await page.getByText('Исходное изображение больше недоступно. Выберите другое изображение.').waitFor({ state: 'visible' })
  assert(await page.locator('.video-desktop-inputs .video-source.filled img').count() === 0, 'unavailable source was installed')
  assert(await page.evaluate(() => sessionStorage.getItem('izo:video-source-v1')) === null, 'unavailable handoff was not discarded')
  assert(state.generateRequests === 0, 'unavailable source started generation')
  await context.close()
}

async function runPreservedDraftPromptFlow(browser) {
  const savedPrompt = 'Медленное движение камеры вокруг героя'
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  await context.addInitScript((prompt) => {
    localStorage.setItem('izo-video-draft-v2', JSON.stringify({ mode: 'text_to_video', prompt }))
    sessionStorage.setItem('izo:video-source-v1', JSON.stringify({ version: 1, createdAt: Date.now(), galleryImageId: 'draft-source', mediaUrl: '/api/media/product-video/source.png', width: 900, height: 1600 }))
  }, savedPrompt)
  const state = await installFixtures(context)
  const page = await context.newPage()
  await page.goto(`${base}/video`, { waitUntil: 'domcontentloaded' })
  await page.locator('.video-desktop-inputs .video-source.filled img').waitFor({ state: 'visible' })
  assert(await page.locator('.video-prompt textarea').inputValue() === savedPrompt, 'non-empty saved video prompt was overwritten')
  assert(await page.evaluate(() => sessionStorage.getItem('izo:video-source-v1')) === null, 'saved-prompt handoff was not consumed')
  assert(state.generateRequests === 0, 'saved-prompt handoff started generation')
  await context.close()
}

await mkdir(evidenceDir, { recursive: true })
let previewProcess
if (!process.env.PRODUCT_VIDEO_E2E_BASE_URL) {
  const viteBin = fileURLToPath(new URL('./node_modules/vite/bin/vite.js', import.meta.url))
  previewProcess = spawn(process.execPath, [viteBin, 'preview', '--host', '127.0.0.1', '--port', String(localPort), '--strictPort'], { cwd: fileURLToPath(new URL('.', import.meta.url)), stdio: ['ignore', 'pipe', 'pipe'] })
  await waitForPreview(localOrigin)
}

const browser = await chromium.launch({ headless: true })
try {
  await runStudioResultFlow(browser, { width: 1440, height: 900 }, 'desktop')
  await runStudioResultFlow(browser, { width: 390, height: 844 }, 'mobile')
  await runGalleryFlow(browser, { width: 1440, height: 900 }, 'desktop')
  await runGalleryFlow(browser, { width: 390, height: 844 }, 'mobile')
  await runUnavailableSourceFlow(browser)
  await runPreservedDraftPromptFlow(browser)
  console.log(JSON.stringify({ ok: true, scenarios: ['studio-result', 'gallery', 'unavailable', 'one-time-reload', 'no-video-action', 'saved-prompt'], viewports: ['1440x900', '390x844'], providerCalls: 0, evidenceDir }))
} finally {
  await browser.close()
  if (previewProcess && !previewProcess.killed) previewProcess.kill()
}
