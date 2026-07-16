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
  await page.locator('.video-history-list button').nth(3).click()
  await page.locator('.video-prompt textarea').fill('Плавное приближение камеры к городской сцене, естественное движение людей и транспорта, мягкий дневной свет.')
  const activeMode = page.locator('.video-mode-tabs button.active')
  const activeModeNormal = await activeMode.evaluate((element) => {
    const style = getComputedStyle(element)
    return { backgroundColor: style.backgroundColor, color: style.color }
  })
  await activeMode.hover()
  const activeModeHover = await activeMode.evaluate((element) => {
    const style = getComputedStyle(element)
    return { backgroundColor: style.backgroundColor, color: style.color }
  })
  const result = await page.evaluate(() => {
    const rect = (selector) => document.querySelector(selector)?.getBoundingClientRect()
    const stage = rect('.video-stage')
    const shelf = rect('.video-result-shelf')
    const composer = rect('.video-composer')
    const resultPanel = rect('.video-result')
    const overlay = rect('.video-stage-overlay')
    const contextActions = rect('.video-context-actions')
    const durationSelect = rect('.video-options-row.single select')
    const generateButton = rect('.video-generate')
    const modeTabs = rect('.video-mode-tabs')
    const videoTopTab = document.querySelector('.mode-tabs .tab[aria-label="Генерация видео"]')
    const modeTabsStyle = document.querySelector('.video-mode-tabs') ? getComputedStyle(document.querySelector('.video-mode-tabs')) : null
    const prompt = document.querySelector('.video-prompt textarea')
    const promptStyle = prompt ? getComputedStyle(prompt) : null
    const rootStyle = getComputedStyle(document.querySelector('.video-studio'))
    return {
      stage, shelf, composer, resultPanel, overlay, contextActions, durationSelect, generateButton, modeTabs,
      fontSize: Number.parseFloat(rootStyle.fontSize),
      promptFontSize: promptStyle ? Number.parseFloat(promptStyle.fontSize) : 0,
      promptFontWeight: promptStyle ? Number.parseInt(promptStyle.fontWeight, 10) : 0,
      viewportHeight: window.innerHeight,
      overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth + 2,
      resultBeforeComposer: Boolean(resultPanel && composer && resultPanel.top < composer.top),
      historyButtons: document.querySelectorAll('.video-history-list button').length,
      historyMeta: document.querySelectorAll('.video-history-meta').length,
      historyHeading: document.querySelector('.video-history h2') !== null,
      stageCaption: document.querySelector('.video-stage-caption') !== null,
      proOpen: document.querySelector('.video-pro-body') !== null,
      modelSelectVisible: Boolean(document.querySelector('.video-pro-body select')),
      modeTabsBorderWidth: modeTabsStyle ? Number.parseFloat(modeTabsStyle.borderTopWidth) : 0,
      videoTopTabDisabled: videoTopTab?.getAttribute('aria-disabled') === 'true' || videoTopTab?.classList.contains('disabled'),
      composerWidth: composer?.width || 0,
    }
  })
  result.activeModeNormal = activeModeNormal
  result.activeModeHover = activeModeHover
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
    assert(fullHd.historyMeta === history.length, 'History duration and model metadata are missing')
    assert(!fullHd.historyHeading, 'Redundant history heading is still visible')
    assert(!fullHd.stageCaption, 'Redundant preview caption is still visible')
    assert(fullHd.promptFontWeight <= 500, 'Prompt text is still too bold')
    assert(fullHd.durationSelect && fullHd.durationSelect.height <= 44, 'Duration control is too tall')
    assert(fullHd.generateButton && fullHd.composer && fullHd.generateButton.bottom <= fullHd.composer.bottom + 1, 'Create video button is outside Composer')
    assert(fullHd.generateButton && fullHd.generateButton.height >= 50, 'Create video button is too small')
    assert(fullHd.modeTabsBorderWidth >= 1, 'Video mode tabs have no visible divider')
    assert(fullHd.activeModeHover.backgroundColor === fullHd.activeModeNormal.backgroundColor, 'Active video mode becomes dark on hover')
    assert(fullHd.activeModeHover.color === fullHd.activeModeNormal.color, 'Active video mode text changes color on hover')
    assert(fullHd.composerWidth >= 490 && fullHd.composerWidth <= 510, 'Full HD Composer does not match the fluid studio width')
    assert(fullHd.fontSize >= 16, 'Full HD base typography is too small')
    assert(!fullHd.videoTopTabDisabled, 'Video topbar tab is still tariff-gated')
    assert(!fullHd.proOpen && !fullHd.modelSelectVisible, 'Professional model selector is open by default')

    const browserFullHd = await inspect(browser, { width: 1920, height: 900 })
    assert(!browserFullHd.overflowX, 'Browser Full HD has horizontal overflow')
    assert(browserFullHd.shelf && browserFullHd.shelf.bottom <= browserFullHd.viewportHeight + 1, 'History shelf is outside the browser Full HD viewport')
    assert(browserFullHd.contextActions && browserFullHd.shelf && browserFullHd.contextActions.bottom <= browserFullHd.shelf.bottom + 1, 'Context actions are clipped in browser Full HD')

    const fourK = await inspect(browser, { width: 3840, height: 2160 })
    assert(!fourK.overflowX, '4K has horizontal overflow')
    assert(fourK.shelf && fourK.shelf.bottom <= fourK.viewportHeight + 1, 'History shelf is outside the 4K viewport')
    assert(fourK.fontSize > fullHd.fontSize, '4K typography does not scale up')
    assert(fourK.promptFontSize > fullHd.promptFontSize, '4K prompt typography does not scale up')
    assert(fourK.composerWidth >= 540 && fourK.composerWidth <= 560, '4K Composer is outside the design-system range')

    const mobile = await inspect(browser, { width: 390, height: 844 })
    assert(!mobile.overflowX, 'Mobile has horizontal overflow')
    assert(mobile.resultBeforeComposer, 'Mobile result must appear before Composer')
    assert(mobile.stage && mobile.stage.width <= 390, 'Mobile stage exceeds viewport width')
    assert(mobile.stage && mobile.stage.height <= mobile.stage.width, 'Mobile landscape video stage is too tall')

    console.log(JSON.stringify({ fullHd, browserFullHd, fourK, mobile }, null, 2))
  } finally {
    await browser.close()
  }
}

run().catch((error) => {
  console.error(error)
  process.exit(1)
})
