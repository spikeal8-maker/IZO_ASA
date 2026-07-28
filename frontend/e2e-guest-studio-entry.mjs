import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

const localPort = 5204
const localOrigin = `http://127.0.0.1:${localPort}`
const base = process.env.E2E_BASE_URL || localOrigin

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

async function waitForPreview(url) {
  const deadline = Date.now() + 20_000
  while (Date.now() < deadline) {
    try {
      if ((await fetch(url)).ok) return
    } catch {
      // Preview is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 200))
  }
  throw new Error(`preview did not start at ${url}`)
}

const model = {
  id: 'video/guest-preview',
  name: 'Seedance 1.5 Pro',
  description: 'Плавное видео по тексту и изображению.',
  supportedResolutions: ['480p', '720p', '1080p'],
  supportedAspectRatios: ['16:9', '9:16', '1:1', '4:3'],
  supportedDurations: [4, 6],
  supportedFrameImages: ['first_frame'],
  generateAudio: true,
  publicPricing: { fromTokens: 3, examples: [{ duration: 4, resolution: '480p', aspectRatio: '16:9', tokens: 3 }] },
}

const publicFeed = {
  items: [
    {
      id: 'guest-feed-video',
      media_type: 'video',
      title: 'Видео из новой ленты',
      prompt: 'Камера движется над городом',
      created_at: '2026-07-28T10:00:00Z',
      aspect_ratio: '9:16',
      resolution: '720×1280',
      duration_ms: 6000,
      has_audio: true,
      model: 'Seedance 1.5 Pro',
      thumbnail_url: 'data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%22720%22 height=%221280%22/%3E',
      video_url: 'data:video/mp4;base64,AAAA',
    },
    {
      id: 'guest-feed-image',
      media_type: 'image',
      title: 'Изображение из новой ленты',
      prompt: 'Светлый портрет',
      created_at: '2026-07-28T09:00:00Z',
      aspect_ratio: '1:1',
      resolution: '1024×1024',
      model: 'ИЗО Base',
      image_url: 'data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%221024%22 height=%221024%22/%3E',
      thumbnail_url: 'data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%221024%22 height=%221024%22/%3E',
    },
  ],
}

async function mockGuestApi(page) {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/auth/bootstrap-v2') {
      return route.fulfill({ json: { installation_id: 'guest-entry', anonymous_id: 'guest-entry' } })
    }
    if (
      url.pathname === '/api/me-v2'
      || url.pathname === '/api/auth/session/refresh-v2'
      || url.pathname === '/api/auth/bot-login/status'
      || url.pathname === '/api/model-access'
      || url.pathname === '/api/gallery/items'
      || url.pathname === '/api/video/history'
      || url.pathname === '/api/video/estimate'
    ) {
      return route.fulfill({ status: 401, json: { detail: 'Not authenticated' } })
    }
    if (url.pathname === '/api/auth/capabilities-v2') {
      return route.fulfill({ json: { password_login_available: true, email_otp_available: true, bot_login: {} } })
    }
    if (url.pathname === '/api/tariffs') return route.fulfill({ json: { tariffs: {} } })
    if (url.pathname === '/api/models') return route.fulfill({ json: { ok: true, profiles: [] } })
    if (url.pathname === '/api/video/config') {
      return route.fulfill({
        json: {
          authenticated: false,
          modes: {
            text_to_video: [model],
            image_to_video: [model],
            first_last_frame: [model],
            reference_to_video: [model],
          },
          plan: 'guest',
          videoSlots: 0,
          videoStorage: { used: 0, limit: 0, free: 0, full: false, storedBytes: 0 },
          economy: { tokenRub: 5, minMarginPercent: 40 },
          availability: {},
        },
      })
    }
    if (url.pathname === '/api/feed') return route.fulfill({ json: publicFeed })
    return route.fulfill({ json: { ok: true, items: [] } })
  })
}

async function inspectGuest(browser, viewport) {
  const page = await browser.newPage({ viewport, isMobile: viewport.width < 761, hasTouch: viewport.width < 761 })
  await mockGuestApi(page)
  await page.goto(`${base}/?guest_entry=${viewport.width}`, { waitUntil: 'networkidle' })
  await page.locator('.iv3-format-trigger').waitFor()

  const imageDefault = {
    resolution: ((await page.locator('.iv3-format-trigger').textContent()) || '').replace(/\s+/g, ''),
    ratio: ((await page.locator('.ratio-button.active').textContent()) || '').trim(),
  }
  await page.locator('.mode-tabs .tab[aria-label="Генерация видео"]').click()
  await page.locator('.video-studio').waitFor()
  await page.locator('.video-loading').waitFor({ state: 'detached' })
  await page.locator('.video-prompt textarea').fill('Гостевой просмотр видеостудии')
  const result = {
    viewport,
    imageDefault,
    modelCards: await page.locator('.video-quality-tabs button').count(),
    modelName: (await page.locator('.video-quality-tabs').textContent()) || '',
    generateDisabled: await page.locator('.video-generate').isDisabled(),
    generateLabel: (await page.locator('.video-generate').textContent()) || '',
    feedVideos: await page.locator('.video-history-list [data-media-kind="video"]').count(),
    feedImages: await page.locator('.video-history-list [data-media-kind="image"]').count(),
    placeholderVisible: await page.locator('.video-stage-placeholder-bg').isVisible(),
    overflowX: await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 2),
  }
  if (process.env.E2E_SCREENSHOT_DIR) {
    await page.screenshot({ path: `${process.env.E2E_SCREENSHOT_DIR}/guest-video-${viewport.width}x${viewport.height}.png`, fullPage: true })
  }
  await page.close()
  return result
}

async function run() {
  let previewProcess
  if (!process.env.E2E_BASE_URL) {
    const viteBin = fileURLToPath(new URL('./node_modules/vite/bin/vite.js', import.meta.url))
    previewProcess = spawn(process.execPath, [viteBin, 'preview', '--host', '127.0.0.1', '--port', String(localPort), '--strictPort'], {
      cwd: fileURLToPath(new URL('.', import.meta.url)),
      stdio: ['ignore', 'pipe', 'pipe'],
    })
    await waitForPreview(localOrigin)
  }
  const browser = await chromium.launch()
  try {
    const results = []
    for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
      const result = await inspectGuest(browser, viewport)
      assert(result.imageDefault.resolution.includes('HD1024×1024'), `Fresh image default is not HD 1024×1024: ${JSON.stringify(result.imageDefault)}`)
      assert(result.imageDefault.ratio === '1:1', `Fresh image default is not square: ${JSON.stringify(result.imageDefault)}`)
      assert(result.modelCards === 3 && result.modelName.includes('Seedance 1.5 Pro'), 'Guest video model catalogue is hidden')
      assert(result.generateDisabled && result.generateLabel.includes('Войдите'), 'Guest video generation button is active')
      assert(result.feedVideos === 1 && result.feedImages === 1, 'Public feed fallback is missing video or image')
      assert(result.placeholderVisible, 'Video empty preview has no branded background')
      assert(!result.overflowX, `Guest layout overflows at ${viewport.width}px`)
      results.push(result)
    }
    console.log(JSON.stringify({ ok: true, results }, null, 2))
  } finally {
    await browser.close()
    if (previewProcess && !previewProcess.killed) previewProcess.kill()
  }
}

run().catch((error) => {
  console.error(error)
  process.exit(1)
})
