import { chromium } from 'playwright'

const base = process.env.E2E_BASE_URL || 'http://127.0.0.1:5174'

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

const model = {
  id: 'video/layout-test',
  name: 'Google: Veo Layout Test',
  description: 'Тестовая видеомодель для проверки адаптивного интерфейса.',
  supportedResolutions: ['720p', '1080p'],
  supportedAspectRatios: ['16:9', '9:16', '1:1'],
  supportedDurations: [4, 6, 8],
  supportedFrameImages: ['first_frame', 'last_frame'],
  generateAudio: true,
  publicPricing: { fromTokens: 5, examples: [{ duration: 4, resolution: '720p', aspectRatio: '16:9', tokens: 5 }] },
}

const history = Array.from({ length: 7 }, (_, index) => ({
  id: `video-layout-${index}`,
  mode: 'text_to_video',
  status: index ? 'completed' : 'queued',
  progress: index ? 100 : 44,
  prompt: `Город будущего, вариант ${index + 1}`,
  createdAt: `2026-07-16T0${index}:00:00Z`,
  model: model.id,
  duration: 4,
  resolution: '720p',
  aspectRatio: index % 3 === 1 ? '9:16' : index % 3 === 2 ? '1:1' : '16:9',
  tokenCost: 5,
  generateAudio: true,
  videoUrl: index ? `/api/video/media/video-layout-${index}` : null,
  galleryVideoId: index ? `gallery-video-layout-${index}` : null,
}))

async function mockApi(page) {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/auth/bootstrap-v2') return route.fulfill({ json: { installation_id: 'video-layout', anonymous_id: 'video-layout' } })
    if (url.pathname === '/api/me-v2') return route.fulfill({
      json: {
        internal_user_id: 'video-layout',
        legacy_user_id: 'video-layout',
        status: 'active',
        account: { role: 'admin', plan: 'business', token_balance: 500, daily_tokens_limit: 500, daily_tokens_remaining: 500, gallery_access: true },
        session: { provider: 'web_email', platform: 'web_desktop', expires_at: '2099-01-01T00:00:00Z', refresh_expires_at: '2099-02-01T00:00:00Z' },
        identities: [],
        profile: { display_name: 'Видео QA', language_code: 'ru', providers: ['web_email'] },
      },
    })
    if (url.pathname === '/api/auth/capabilities-v2') return route.fulfill({ json: { password_login_available: true, email_otp_available: true, bot_login: {} } })
    if (url.pathname === '/api/video/config') return route.fulfill({
      json: {
        modes: { text_to_video: [model], image_to_video: [model], first_last_frame: [model], reference_to_video: [model] },
        plan: 'business',
        videoSlots: 50,
        economy: { tokenRub: 5, minMarginPercent: 40 },
        availability: {},
      },
    })
    if (url.pathname === '/api/video/history') return route.fulfill({ json: { items: history } })
    if (url.pathname === '/api/video/estimate') return route.fulfill({ json: { chargedTokens: 5 } })
    if (url.pathname === '/api/gallery/items') return route.fulfill({ json: { items: [] } })
    if (url.pathname === '/api/tariffs') return route.fulfill({ json: { tariffs: {} } })
    if (url.pathname === '/api/models') return route.fulfill({ json: { ok: true, profiles: [] } })
    return route.fulfill({ json: { ok: true, items: [] } })
  })
}

async function inspect(browser, viewport) {
  const page = await browser.newPage({ viewport, isMobile: viewport.width < 761, hasTouch: viewport.width < 761 })
  await mockApi(page)
  await page.goto(`${base}/video?layout_test=${viewport.width}`, { waitUntil: 'networkidle' })
  await page.locator('.video-studio').waitFor()
  const result = await page.evaluate(() => {
    const rect = (selector) => document.querySelector(selector)?.getBoundingClientRect()
    const stage = rect('.video-stage')
    const shelf = rect('.video-result-shelf')
    const composer = rect('.video-composer')
    const resultPanel = rect('.video-result')
    const overlay = rect('.video-stage-overlay')
    const rootStyle = getComputedStyle(document.querySelector('.video-studio'))
    return {
      stage, shelf, composer, resultPanel, overlay,
      fontSize: Number.parseFloat(rootStyle.fontSize),
      viewportHeight: window.innerHeight,
      overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth + 2,
      resultBeforeComposer: Boolean(resultPanel && composer && resultPanel.top < composer.top),
      historyButtons: document.querySelectorAll('.video-history-list button').length,
      proOpen: document.querySelector('.video-pro-body') !== null,
      modelSelectVisible: Boolean(document.querySelector('.video-pro-body select')),
    }
  })
  if (process.env.E2E_SCREENSHOT_DIR) {
    await page.screenshot({ path: `${process.env.E2E_SCREENSHOT_DIR}/video-${viewport.width}x${viewport.height}.png`, fullPage: true })
  }
  await page.close()
  return result
}

async function run() {
  const browser = await chromium.launch()
  try {
    const fullHd = await inspect(browser, { width: 1920, height: 1080 })
    assert(!fullHd.overflowX, 'Full HD has horizontal overflow')
    assert(fullHd.shelf && fullHd.shelf.bottom <= fullHd.viewportHeight + 1, 'History shelf is outside the Full HD viewport')
    assert(fullHd.stage && fullHd.stage.height > 400, 'Full HD stage is too small')
    assert(fullHd.overlay && fullHd.stage && fullHd.overlay.top >= fullHd.stage.top, 'Stage actions are not over the video')
    assert(fullHd.historyButtons === history.length, 'History items are missing')
    assert(!fullHd.proOpen && !fullHd.modelSelectVisible, 'Professional model selector is open by default')

    const fourK = await inspect(browser, { width: 3840, height: 2160 })
    assert(!fourK.overflowX, '4K has horizontal overflow')
    assert(fourK.shelf && fourK.shelf.bottom <= fourK.viewportHeight + 1, 'History shelf is outside the 4K viewport')
    assert(fourK.fontSize > fullHd.fontSize, '4K typography does not scale up')

    const mobile = await inspect(browser, { width: 390, height: 844 })
    assert(!mobile.overflowX, 'Mobile has horizontal overflow')
    assert(mobile.resultBeforeComposer, 'Mobile result must appear before Composer')
    assert(mobile.stage && mobile.stage.width <= 390, 'Mobile stage exceeds viewport width')

    console.log(JSON.stringify({ fullHd, fourK, mobile }, null, 2))
  } finally {
    await browser.close()
  }
}

run().catch((error) => {
  console.error(error)
  process.exit(1)
})
