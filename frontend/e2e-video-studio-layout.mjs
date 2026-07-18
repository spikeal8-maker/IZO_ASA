import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

const localPort = 5199
const localOrigin = `http://127.0.0.1:${localPort}`
const base = process.env.E2E_BASE_URL || localOrigin

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

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

const model = {
  id: 'video/layout-test',
  name: 'Google: Veo Layout Test',
  description: 'Тестовая видеомодель для проверки адаптивного интерфейса.',
  supportedResolutions: ['720p', '1080p'],
  supportedAspectRatios: ['16:9', '9:16', '1:1', '4:3', '3:4', '21:9', '9:21'],
  supportedDurations: [4, 5, 6, 7, 8, 9, 10, 11, 12],
  supportedFrameImages: ['first_frame', 'last_frame'],
  generateAudio: true,
  publicPricing: { fromTokens: 5, examples: [{ duration: 4, resolution: '720p', aspectRatio: '16:9', tokens: 5 }] },
}

const history = Array.from({ length: 7 }, (_, index) => ({
  id: `video-layout-${index}`,
  mode: 'text_to_video',
  status: 'completed',
  progress: 100,
  prompt: `Город будущего, вариант ${index + 1}`,
  createdAt: `2026-07-16T0${index}:00:00Z`,
  model: model.id,
  duration: 4,
  resolution: '720p',
  aspectRatio: index % 3 === 1 ? '9:16' : index % 3 === 2 ? '1:1' : '16:9',
  tokenCost: 5,
  generateAudio: true,
  videoUrl: `/api/video/media/video-layout-${index}`,
  galleryVideoId: `gallery-video-layout-${index}`,
}))

async function mockApi(page) {
  const state = {
    publicationId: null,
    publicationStatus: null,
    historyReadsAfterPublish: 0,
    publishPayload: null,
    generatedJob: null,
    generationBody: null,
    meReads: 0,
  }
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/auth/bootstrap-v2') return route.fulfill({ json: { installation_id: 'video-layout', anonymous_id: 'video-layout' } })
    if (url.pathname === '/api/me-v2') {
      state.meReads += 1
      return route.fulfill({
      json: {
        internal_user_id: 'video-layout',
        legacy_user_id: 'video-layout',
        status: 'active',
        account: { role: 'admin', plan: 'business', token_balance: state.generatedJob ? 488 : 500, daily_tokens_limit: 500, daily_tokens_remaining: 500, gallery_access: true },
        session: { provider: 'web_email', platform: 'web_desktop', expires_at: '2099-01-01T00:00:00Z', refresh_expires_at: '2099-02-01T00:00:00Z' },
        identities: [],
        profile: { display_name: 'Видео QA', language_code: 'ru', providers: ['web_email'] },
      },
      })
    }
    if (url.pathname === '/api/auth/capabilities-v2') return route.fulfill({ json: { password_login_available: true, email_otp_available: true, bot_login: {} } })
    if (url.pathname === '/api/video/config') return route.fulfill({
      json: {
        modes: { text_to_video: [model], image_to_video: [model], first_last_frame: [model], reference_to_video: [model] },
        plan: 'business',
        videoSlots: 50,
        feedPublicationEnabled: true,
        economy: { tokenRub: 5, minMarginPercent: 40 },
        availability: {},
      },
    })
    if (url.pathname === '/api/video/history') {
      if (state.publicationStatus === 'preparing') {
        state.historyReadsAfterPublish += 1
        if (state.historyReadsAfterPublish >= 2) state.publicationStatus = 'published'
      }
      const completedItems = history.map((item, index) => index === 3 && state.publicationStatus ? {
        ...item,
        publicationId: state.publicationId,
        publicationStatus: state.publicationStatus,
        published: state.publicationStatus === 'published',
      } : item)
      const items = state.generatedJob ? [state.generatedJob, ...completedItems] : completedItems
      return route.fulfill({ json: { items } })
    }
    if (url.pathname === '/api/feed/publications' && route.request().method() === 'POST') {
      state.publishPayload = route.request().postDataJSON()
      state.publicationId = 'publication-layout-video'
      state.publicationStatus = 'preparing'
      state.historyReadsAfterPublish = 0
      return route.fulfill({
        status: 202,
        json: {
          ok: true,
          publication: {
            id: state.publicationId,
            video_id: state.publishPayload.videoId,
            media_type: 'video',
            status: 'preparing',
          },
        },
      })
    }
    if (url.pathname === '/api/video/estimate') {
      const body = route.request().postDataJSON()
      const resolutionFactor = body.resolution === '1080p' ? 2 : 1
      const audioFactor = body.generateAudio ? 1.5 : 1
      return route.fulfill({ json: { chargedTokens: Math.ceil(Number(body.duration || 4) * resolutionFactor * audioFactor) } })
    }
    if (url.pathname === '/api/video/generate' && route.request().method() === 'POST') {
      state.generationBody = route.request().postDataJSON()
      await new Promise((resolve) => setTimeout(resolve, 850))
      state.generatedJob = {
        id: 'video-layout-new',
        mode: state.generationBody.mode,
        status: 'queued',
        progress: 10,
        prompt: state.generationBody.prompt,
        createdAt: new Date().toISOString(),
        model: state.generationBody.model,
        duration: state.generationBody.duration,
        resolution: state.generationBody.resolution,
        aspectRatio: state.generationBody.aspectRatio,
        tokenCost: 12,
        generateAudio: state.generationBody.generateAudio,
      }
      return route.fulfill({ json: { ...state.generatedJob, tokenBalance: 488 } })
    }
    if (url.pathname === '/api/gallery/items') return route.fulfill({ json: { items: [] } })
    if (url.pathname === '/api/tariffs') return route.fulfill({ json: { tariffs: {} } })
    if (url.pathname === '/api/models') return route.fulfill({ json: { ok: true, profiles: [] } })
    return route.fulfill({ json: { ok: true, items: [] } })
  })
  return state
}

async function inspect(browser, viewport) {
  const page = await browser.newPage({ viewport, isMobile: viewport.width < 761, hasTouch: viewport.width < 761 })
  const apiState = await mockApi(page)
  await page.goto(`${base}/video?layout_test=${viewport.width}`, { waitUntil: 'networkidle' })
  await page.locator('.video-studio').waitFor()
  if (process.env.E2E_SCREENSHOT_DIR) {
    await page.screenshot({ path: `${process.env.E2E_SCREENSHOT_DIR}/video-initial-${viewport.width}x${viewport.height}.png`, fullPage: true })
  }
  await page.locator('.video-history-list button').nth(3).click()
  await page.locator('.video-prompt textarea').fill('Плавное приближение камеры к городской сцене, естественное движение людей и транспорта, мягкий дневной свет.')
  await page.locator('.video-live-price strong').filter({ hasNotText: 'Считаем' }).waitFor()
  const exampleButton = page.locator('.video-prompt-actions button', { hasText: 'Пример' })
  await exampleButton.click()
  const firstExample = await page.locator('.video-prompt textarea').inputValue()
  await exampleButton.click()
  const secondExample = await page.locator('.video-prompt textarea').inputValue()
  await page.locator('.video-prompt textarea').fill('Плавное приближение камеры к городской сцене, естественное движение людей и транспорта, мягкий дневной свет.')
  const activeMode = page.locator('.video-mode-tabs button.active')
  const activeModeNormal = viewport.width >= 821 ? await activeMode.evaluate((element) => {
    const style = getComputedStyle(element)
    return { backgroundColor: style.backgroundColor, color: style.color }
  }) : null
  if (viewport.width >= 821) await activeMode.hover()
  const activeModeHover = viewport.width >= 821 ? await activeMode.evaluate((element) => {
    const style = getComputedStyle(element)
    return { backgroundColor: style.backgroundColor, color: style.color }
  }) : null
  const generateButton = page.locator('.video-generate')
  const generateNormal = await generateButton.evaluate((element) => {
    const style = getComputedStyle(element)
    return { backgroundColor: style.backgroundColor, color: style.color }
  })
  await generateButton.hover()
  const generateHover = await generateButton.evaluate((element) => {
    const style = getComputedStyle(element)
    return { backgroundColor: style.backgroundColor, color: style.color }
  })
  const initialPrice = (await page.locator('.video-live-price strong').textContent()) || ''
  await page.locator('.video-resolution-tabs button', { hasText: '1080p' }).click()
  await page.locator('.video-live-price strong').filter({ hasText: '8 ток.' }).waitFor()
  const resolutionPrice = (await page.locator('.video-live-price strong').textContent()) || ''
  const durationBeforeAudio = await page.locator('.video-duration-control').boundingBox()
  await page.locator('.video-audio-switch').click()
  await page.locator('.video-live-price strong').filter({ hasText: '12 ток.' }).waitFor()
  const durationAfterAudio = await page.locator('.video-duration-control').boundingBox()
  const audioPrice = (await page.locator('.video-live-price strong').textContent()) || ''
  const guideButtonCount = await page.locator('.video-guide-button').count()
  await page.locator('.video-guide-button').click()
  const guideDialog = page.locator('.video-guide-dialog')
  await guideDialog.waitFor()
  const guideState = await page.evaluate(() => {
    const overlay = document.querySelector('.video-guide-overlay')
    const dialog = document.querySelector('.video-guide-dialog')
    const prompt = document.querySelector('.video-prompt textarea')
    return {
      title: dialog?.querySelector('h2')?.textContent || '',
      steps: dialog?.querySelectorAll('li').length || 0,
      overlayZ: overlay ? Number.parseInt(getComputedStyle(overlay).zIndex, 10) : 0,
      promptZ: prompt ? (Number.parseInt(getComputedStyle(prompt).zIndex || '0', 10) || 0) : 0,
    }
  })
  await guideDialog.locator('button', { hasText: 'Понятно' }).click()
  const durationTrigger = page.locator('.video-duration-trigger')
  await durationTrigger.click()
  const durationMenuState = await page.locator('.video-duration-menu').evaluate((element) => {
    const style = getComputedStyle(element)
    const option = element.querySelector('.video-duration-option')
    const optionStyle = option ? getComputedStyle(option) : null
    return {
      backgroundColor: style.backgroundColor,
      color: optionStyle?.color || '',
      labels: Array.from(element.querySelectorAll('.video-duration-option')).map((item) => item.textContent?.trim() || ''),
    }
  })
  await durationTrigger.press('Escape')
  await page.locator('.video-format-more').click()
  assert(await page.locator('.video-format-tabs button').count() === model.supportedAspectRatios.length, 'Additional formats do not expand')
  await page.locator('.video-format-more').click()
  if (viewport.width < 821) {
    await page.locator('.video-mobile-mode-trigger').click()
    await page.locator('.video-mobile-mode-menu button', { hasText: 'Изображение → видео' }).click()
    await page.locator('.video-mobile-inputs').waitFor()
    const chooserPromise = page.waitForEvent('filechooser')
    await page.locator('.video-mobile-inputs .video-source').click({ position: { x: 12, y: 12 } })
    await chooserPromise
  }
  await page.evaluate(() => {
    document.documentElement.style.scrollBehavior = 'auto'
    document.body.style.scrollBehavior = 'auto'
    document.querySelector('.video-composer-scroll')?.scrollTo({ top: 0 })
    document.documentElement.scrollTop = 0
    document.body.scrollTop = 0
    window.scrollTo(0, 0)
  })
  await page.waitForTimeout(100)
  const result = await page.evaluate(() => {
    const rect = (selector) => document.querySelector(selector)?.getBoundingClientRect()
    const stage = rect('.video-stage')
    const shelf = rect('.video-result-shelf')
    const composer = rect('.video-composer')
    const resultPanel = rect('.video-result')
    const overlay = rect('.video-stage-overlay')
    const contextActions = rect('.video-context-actions')
    const durationTrigger = rect('.video-duration-trigger')
    const generateButton = rect('.video-generate')
    const modeTabs = rect('.video-mode-tabs')
    const videoTopTab = document.querySelector('.mode-tabs .tab[aria-label="Генерация видео"]')
    const modeTabsStyle = document.querySelector('.video-mode-tabs') ? getComputedStyle(document.querySelector('.video-mode-tabs')) : null
    const prompt = document.querySelector('.video-prompt textarea')
    const promptRect = prompt?.getBoundingClientRect()
    const promptStyle = prompt ? getComputedStyle(prompt) : null
    const rootStyle = getComputedStyle(document.querySelector('.video-studio'))
    const mobileSource = rect('.video-mobile-inputs')
    const format169 = document.querySelector('.video-format-tabs button[title^="Формат 16:9"] i')?.getBoundingClientRect()
    const format11 = document.querySelector('.video-format-tabs button[title^="Формат 1:1"] i')?.getBoundingClientRect()
    const generateStyle = document.querySelector('.video-generate') ? getComputedStyle(document.querySelector('.video-generate')) : null
    const durationControl = document.querySelector('.video-duration-control')
    const promptHeading = document.querySelector('.video-prompt-heading')
    const mobileModeStyle = document.querySelector('.video-mobile-mode') ? getComputedStyle(document.querySelector('.video-mobile-mode')) : null
    const canonicalTopbar = document.querySelector('.iv3 > .app-shell > .topbar')
    const topbarStyle = canonicalTopbar ? getComputedStyle(canonicalTopbar) : null
    const formatControls = rect('.video-format-controls')
    const formatTabs = rect('.video-format-tabs')
    const formatMore = rect('.video-format-more')
    const params = rect('.video-params')
    return {
      stage, shelf, composer, resultPanel, overlay, contextActions, durationTrigger, generateButton, modeTabs,
      promptRect,
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
      proOpen: document.querySelector('.video-model-list') !== null,
      modelSelectVisible: Boolean(document.querySelector('.video-model-list')),
      guideButtonCount: document.querySelectorAll('.video-guide-button').length,
      durationInHeading: Boolean(durationControl && promptHeading?.contains(durationControl)),
      promptClear: document.querySelector('.video-prompt-clear') !== null,
      visibleFormats: document.querySelectorAll('.video-format-tabs button').length,
      formatMore: document.querySelector('.video-format-more') !== null,
      formatMoreRect: formatMore,
      formatTabsRect: formatTabs,
      formatQualityGap: formatControls && params ? params.top - formatControls.bottom : null,
      currentEstimate: document.querySelector('.video-live-price strong')?.textContent || '',
      qualityPrices: document.querySelectorAll('.video-quality-tabs em').length,
      modeTabsBorderWidth: modeTabsStyle ? Number.parseFloat(modeTabsStyle.borderTopWidth) : 0,
      videoTopTabDisabled: videoTopTab?.getAttribute('aria-disabled') === 'true' || videoTopTab?.classList.contains('disabled'),
      composerWidth: composer?.width || 0,
      mobileModeVisible: Boolean(document.querySelector('.video-mobile-mode') && getComputedStyle(document.querySelector('.video-mobile-mode')).display !== 'none'),
      desktopModeVisible: Boolean(document.querySelector('.video-mode-tabs') && getComputedStyle(document.querySelector('.video-mode-tabs')).display !== 'none'),
      mobileModeText: document.querySelector('.video-mobile-mode-trigger')?.textContent || '',
      mobileSourceBeforeStage: Boolean(mobileSource && stage && mobileSource.bottom <= stage.top + 1),
      format169Width: format169?.width || 0,
      format11Width: format11?.width || 0,
      generatePosition: generateStyle?.position || '',
      mobileModeZ: mobileModeStyle ? (Number.parseInt(mobileModeStyle.zIndex, 10) || 0) : 0,
      topbarZ: topbarStyle ? (Number.parseInt(topbarStyle.zIndex, 10) || 0) : 0,
    }
  })
  result.activeModeNormal = activeModeNormal
  result.activeModeHover = activeModeHover
  result.generateNormal = generateNormal
  result.generateHover = generateHover
  result.priceTransition = { initialPrice, resolutionPrice, audioPrice }
  result.examplesDiffer = firstExample !== secondExample
  result.durationBeforeAudio = durationBeforeAudio
  result.durationAfterAudio = durationAfterAudio
  result.guideButtonCountBeforeOpen = guideButtonCount
  result.guideState = guideState
  result.durationMenuState = durationMenuState
  if (viewport.width >= 821) {
    await page.locator('.video-more > button').click()
    await page.locator('.video-more button', { hasText: 'Очистить предпросмотр' }).click()
    result.clearPreviewKeepsHistory = await page.locator('.video-history-list button').count() === history.length && await page.locator('.video-stage-message').isVisible()
    await page.locator('.video-history-list button').nth(3).click()
  }
  if (viewport.width === 1920 && viewport.height === 1080) {
    await page.locator('.video-context-actions .feed').click()
    const dialog = page.locator('.video-publish-dialog')
    await dialog.waitFor({ state: 'visible' })
    await dialog.locator('label').filter({ hasText: 'Название публикации' }).locator('input').fill('Видео для ленты')
    await dialog.locator('label').filter({ hasText: 'Описание' }).locator('textarea').fill('Проверка асинхронной публикации')
    await dialog.locator('label').filter({ hasText: 'Теги' }).locator('input').fill('тест, видео')
    await dialog.locator('footer button.primary').click()
    await dialog.waitFor({ state: 'hidden' })
    await page.locator('.video-context-actions .feed').filter({ hasText: 'Открыть в ленте' }).waitFor({ timeout: 8_000 })
    result.publicationWorkflow = {
      payload: apiState.publishPayload,
      publicationId: apiState.publicationId,
      publicationStatus: apiState.publicationStatus,
      historyReadsAfterPublish: apiState.historyReadsAfterPublish,
    }
  }
  if (process.env.E2E_SCREENSHOT_DIR) {
    await page.screenshot({ path: `${process.env.E2E_SCREENSHOT_DIR}/video-${viewport.width}x${viewport.height}.png`, fullPage: true })
  }
  await page.close()
  return result
}

async function verifyGenerationFeedback(browser) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  const apiState = await mockApi(page)
  await page.goto(`${base}/video?generation_feedback=1`, { waitUntil: 'networkidle' })
  await page.locator('.video-studio').waitFor()
  await page.locator('.video-prompt textarea').fill('Камера плавно движется над вечерним городом.')
  await page.locator('.video-resolution-tabs button', { hasText: '1080p' }).click()
  await page.locator('.video-audio-switch').click()
  await page.locator('.video-live-price strong').filter({ hasText: '12 ток.' }).waitFor()
  const meReadsBefore = apiState.meReads

  await page.locator('.video-generate').click()
  await page.locator('.video-progress strong', { hasText: 'Отправляем задачу' }).waitFor({ timeout: 400 })
  const optimisticCount = await page.locator('.video-history-list button.generating').count()
  await page.locator('.video-history-list button').nth(1).click()
  await page.locator('.video-active-return').waitFor()
  const oldVideoVisible = await page.locator('.video-stage video').isVisible()
  await page.locator('.video-history-list button.generating').filter({ hasText: '10%' }).waitFor({ timeout: 3_000 })
  const oldVideoStillVisible = await page.locator('.video-stage video').isVisible()
  await page.locator('.video-active-return').click()
  await page.locator('.video-progress strong', { hasText: 'В очереди' }).waitFor()

  const result = {
    optimisticCount,
    oldVideoVisible,
    oldVideoStillVisible,
    generationBody: apiState.generationBody,
    balanceRefreshed: apiState.meReads > meReadsBefore,
    historyCount: await page.locator('.video-history-list button').count(),
    activeProgress: (await page.locator('.video-progress small').textContent()) || '',
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
    assert(fullHd.durationTrigger && fullHd.durationTrigger.height <= 44, 'Duration control is too tall')
    assert(fullHd.durationMenuState.backgroundColor !== 'rgb(255, 255, 255)', 'Duration menu has a white background')
    assert(fullHd.durationMenuState.color !== fullHd.durationMenuState.backgroundColor, 'Duration option text is not readable against its background')
    assert(fullHd.durationMenuState.labels.every((label) => /секунд|секунда|секунды/.test(label) && !/сек\./.test(label)), 'Duration options use abbreviated or incomplete Russian labels')
    assert(fullHd.generateButton && fullHd.composer && fullHd.generateButton.bottom <= fullHd.composer.bottom + 1, 'Create video button is outside Composer')
    assert(fullHd.generateButton && fullHd.generateButton.height >= 50, 'Create video button is too small')
    assert(fullHd.modeTabsBorderWidth >= 1, 'Video mode tabs have no visible divider')
    assert(fullHd.activeModeHover.backgroundColor === fullHd.activeModeNormal.backgroundColor, 'Active video mode becomes dark on hover')
    assert(fullHd.activeModeHover.color === fullHd.activeModeNormal.color, 'Active video mode text changes color on hover')
    assert(fullHd.generateHover.backgroundColor !== 'rgb(0, 0, 0)', 'Create video button becomes black on hover')
    assert(fullHd.generateHover.color === fullHd.generateNormal.color, 'Create video text changes color on hover')
    assert(fullHd.composerWidth >= 490 && fullHd.composerWidth <= 510, 'Full HD Composer does not match the fluid studio width')
    assert(fullHd.fontSize >= 16, 'Full HD base typography is too small')
    assert(!fullHd.videoTopTabDisabled, 'Video topbar tab is still tariff-gated')
    assert(!fullHd.proOpen && !fullHd.modelSelectVisible, 'Professional model selector is open by default')
    assert(fullHd.guideButtonCount === 1 && fullHd.guideButtonCountBeforeOpen === 1, 'Video page must contain exactly one instruction button')
    assert(fullHd.guideState.title === 'Как создать первое видео' && fullHd.guideState.steps >= 5, 'Instruction dialog is incomplete')
    assert(fullHd.guideState.overlayZ > fullHd.guideState.promptZ, 'Instruction dialog is rendered behind the page')
    assert(fullHd.durationInHeading, 'Duration selector is not placed in the prompt heading')
    assert(fullHd.promptClear, 'Prompt clear button is missing')
    assert(fullHd.visibleFormats === 4, 'More than four primary formats are visible by default')
    assert(fullHd.formatMore, 'Additional-format control is missing')
    assert(fullHd.formatMoreRect && fullHd.formatMoreRect.width <= 46, 'Additional-format control is not compact')
    assert(fullHd.formatTabsRect && fullHd.formatMoreRect && fullHd.formatMoreRect.left >= fullHd.formatTabsRect.right - 1, 'Additional-format control is not placed beside formats')
    assert(fullHd.formatQualityGap !== null && fullHd.formatQualityGap <= 20, 'Format and quality blocks are too far apart')
    assert(fullHd.qualityPrices === 3, 'Quality cards do not expose calculated prices')
    assert(/\d+\s*ток/.test(fullHd.currentEstimate), 'Current server estimate is not visible')
    assert(fullHd.priceTransition.initialPrice !== fullHd.priceTransition.resolutionPrice, 'Resolution does not update the token estimate')
    assert(fullHd.priceTransition.resolutionPrice !== fullHd.priceTransition.audioPrice, 'Audio does not update the token estimate')
    assert(fullHd.examplesDiffer, 'Example button repeats the same prompt')
    assert(fullHd.durationBeforeAudio && fullHd.durationAfterAudio && Math.abs(fullHd.durationBeforeAudio.x - fullHd.durationAfterAudio.x) < 1 && Math.abs(fullHd.durationBeforeAudio.y - fullHd.durationAfterAudio.y) < 1, 'Audio toggle shifts the duration control')
    assert(fullHd.format169Width > fullHd.format11Width * 1.35, '16:9 format icon does not look wider than 1:1')
    assert(fullHd.clearPreviewKeepsHistory, 'Clearing the preview removes history or does not clear the stage')
    assert(fullHd.publicationWorkflow?.payload?.videoId === 'gallery-video-layout-3', 'Video publication uses the wrong gallery video id')
    assert(fullHd.publicationWorkflow?.payload?.title === 'Видео для ленты', 'Video publication title is missing')
    assert(fullHd.publicationWorkflow?.payload?.allowRecreate === false, 'Video publication must disable recreation')
    assert(fullHd.publicationWorkflow?.publicationStatus === 'published', 'Video publication did not transition to published')
    assert(fullHd.publicationWorkflow?.historyReadsAfterPublish >= 2, 'Video publication did not poll history while preparing')

    const browserFullHd = await inspect(browser, { width: 1920, height: 900 })
    assert(!browserFullHd.overflowX, 'Browser Full HD has horizontal overflow')
    assert(browserFullHd.shelf && browserFullHd.shelf.bottom <= browserFullHd.viewportHeight + 1, 'History shelf is outside the browser Full HD viewport')
    assert(
      browserFullHd.contextActions && browserFullHd.shelf && browserFullHd.contextActions.bottom <= browserFullHd.shelf.bottom + 1,
      `Context actions are clipped in browser Full HD: actions=${JSON.stringify(browserFullHd.contextActions)} shelf=${JSON.stringify(browserFullHd.shelf)}`,
    )

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
    assert(mobile.mobileModeVisible && !mobile.desktopModeVisible, 'Mobile creation-mode dropdown did not replace desktop tabs')
    assert(!mobile.mobileModeText.includes('Способ создания'), 'Redundant mobile creation-mode label is still visible')
    assert(mobile.mobileSourceBeforeStage, 'Mobile source upload must appear before the preview')
    assert(mobile.generatePosition === 'fixed', 'Mobile create button is not pinned to the lower edge')
    assert(mobile.topbarZ > mobile.mobileModeZ, 'Mobile creation-mode menu can overlap the main navigation')
    assert(mobile.promptRect && mobile.stage && mobile.promptRect.top >= mobile.stage.bottom, 'Mobile prompt must appear after the video preview')
    assert(mobile.shelf && mobile.composer && mobile.shelf.top >= mobile.composer.bottom - 1, 'Mobile history must appear after generation settings')

    const generationFeedback = await verifyGenerationFeedback(browser)
    assert(generationFeedback.optimisticCount === 1, 'Generation does not appear in history immediately')
    assert(generationFeedback.oldVideoVisible && generationFeedback.oldVideoStillVisible, 'Older video cannot be previewed while generation is running')
    assert(generationFeedback.generationBody?.resolution === '1080p' && generationFeedback.generationBody?.generateAudio === true, 'Generation request lost selected parameters')
    assert(generationFeedback.balanceRefreshed, 'Token balance is not refreshed after the server confirms the charge')
    assert(generationFeedback.historyCount === history.length + 1, 'Server-confirmed generation is missing from history')
    assert(generationFeedback.activeProgress === '10%', 'Server-confirmed progress is not shown in preview')

    const report = { fullHd, browserFullHd, fourK, mobile, generationFeedback }
    console.log(JSON.stringify(process.env.E2E_VERBOSE === '1' ? report : {
      ok: true,
      viewports: ['1920x1080', '1920x900', '3840x2160', '390x844'],
      publicationStatus: fullHd.publicationWorkflow?.publicationStatus,
      publicationHistoryReads: fullHd.publicationWorkflow?.historyReadsAfterPublish,
      generationFeedback: true,
    }, null, 2))
  } finally {
    await browser.close()
    if (previewProcess && !previewProcess.killed) previewProcess.kill()
  }
}

run().catch((error) => {
  console.error(error)
  process.exit(1)
})
