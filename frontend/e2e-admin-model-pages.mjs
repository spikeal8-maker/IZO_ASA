import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'

const baseURL = process.env.QA_ADMIN_BASE_URL || 'http://127.0.0.1:5175'
const outDir = process.env.QA_ARTIFACT_DIR || 'visual-out'
mkdirSync(outDir, { recursive: true })
const pages = [
  ['OpenRouter', '/admin/models/openrouter/text', 'Текстовые модели OpenRouter'],
  ['Ollama', '/admin/models/ollama', 'Локальные текстовые модели Ollama'],
  ['Config UI', '/admin/models/config-ui', 'Локальные модели Config UI'],
  ['Энергопотребление', '/admin/models/energy', 'Энергопотребление'],
  ['Голосовой ввод', '/admin/models/voice-input', 'Голосовой ввод'],
  ['Улучшение промпта', '/admin/models/prompt-improvement', 'Улучшение промпта'],
]
const openrouterPages = [
  ['Текст', '/admin/models/openrouter/text', 'Текстовые модели OpenRouter'],
  ['Изображения', '/admin/models/openrouter/images', 'Модели изображений OpenRouter'],
  ['Видео', '/admin/models/openrouter/video', 'Видеомодели OpenRouter'],
  ['Звук', '/admin/models/openrouter/audio', 'Звуковые модели OpenRouter'],
  ['3D', '/admin/models/openrouter/3d', '3D-модели OpenRouter'],
  ['Настройки', '/admin/models/openrouter/settings', 'Настройки OpenRouter'],
]

const json = (body, status = 200) => ({ status, contentType: 'application/json', body: JSON.stringify(body) })
const me = {
  internal_user_id: 'admin-model-pages',
  profile: { display_name: 'Администратор', public_user_code: 'WEB-ADMIN' },
  account: { role: 'admin', plan: 'admin', token_balance: 100 },
}

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

async function mockAdmin(page) {
  await page.route('**/api/auth/bootstrap-v2', (route) => route.fulfill(json({ installation_id: 'qa-install', anonymous_id: 'qa-anon' })))
  await page.route('**/api/me-v2', (route) => route.fulfill(json(me)))
  await page.route('**/api/admin/models-page**', (route) => route.fulfill(json({
    economy: { activeModels: 0, routesAssigned: '', expensiveRoutes: 0, priceConflicts: 0 }, routes: [], matrix: [], catalog: [], loras: [],
    userChoice: { simple: [], pro: [] }, comfyuiAvailable: false, comfyFiles: {}, profiles: [],
    openrouter: {
      keyConfigured: true,
      usage: {},
      config: {
        published: ['provider/test-image'],
        enabled: { text_to_image: ['provider/test-image'] },
        defaults: { text_to_image: 'provider/test-image' },
        access: { text_to_image: { pro: ['provider/test-image'] } },
        qualityDefaults: {},
      },
      exchange: { rate: 90 },
      economy: { minMarginPercent: 40, tokenRub: 5 },
      backendPricing: [
        { id: 'provider/test-image', name: 'Test Image', provider: 'Provider', pricing_type: 'image', usd: 0.02, min_tokens: 1, source: 'test', formats: [] },
        { id: 'provider/hidden-image', name: 'Hidden Image', provider: 'Provider', pricing_type: 'image', usd: 0.02, min_tokens: 1, source: 'test', formats: [] },
      ],
      capabilityCatalog: [
        { id: 'provider/test-image', name: 'Provider: Test Image', description: '', created: 1700000000, inputModalities: ['text'], outputModalities: ['image'], parameters: [], maxInputReferences: 0, supportsStreaming: false, modes: ['text_to_image'], features: {} },
        { id: 'provider/hidden-image', name: 'Provider: Hidden Image', description: '', created: 0, inputModalities: ['text'], outputModalities: ['image'], parameters: [], maxInputReferences: 0, supportsStreaming: false, modes: ['text_to_image'], features: {} },
      ],
      videoCatalog: [{
        id: 'provider/test-video', name: 'Test Video', description: '', created: 1700000000,
        modes: ['text_to_video'], supportedAspectRatios: ['16:9'], supportedDurations: [5],
        supportedResolutions: ['1080p'], supportedFrameImages: [], generateAudio: false, seed: true,
        pricingSkus: { 'video.default': '0.10' },
      }],
      videoConfig: { published: ['provider/test-video'], enabled: { text_to_video: ['provider/test-video'] }, access: { text_to_video: { pro: ['provider/test-video'] } } },
      videoUsage: { modes: [], models: [], shadowEconomics: {} },
    },
  })))
  await page.route('**/api/admin/settings/assistant_models', (route) => {
    const settings = JSON.parse(route.request().postData() || '{}').settings
    return route.fulfill(json({ ok: true, settings }))
  })
  await page.route('**/api/admin/energy**', (route) => route.fulfill(json({ detail: 'isolated navigation test' }, 503)))
  await page.route('**/api/admin/voice**', (route) => route.fulfill(json({ detail: 'isolated navigation test' }, 503)))
  await page.route('**/api/admin/assistants', (route) => route.fulfill(json({
    config: {
      voice: { localModel: 'gemma4:12b', qwenModel: '', qwenBaseUrl: '', apiModel: '', route: 'local', queueTimeoutSeconds: 1, requestTimeoutSeconds: 45, minRecordingSeconds: 1 },
      improve: { route: 'local', localModel: 'gemma4:12b', apiModel: '', localTimeoutSeconds: 30, apiTimeoutSeconds: 10, systemPrompt: '', modePrompts: {} },
      chat: { enabled: true, localEnabled: true, localModel: 'gemma4:12b', localLabel: 'ИЗО Чат', localTokenCost: 0, defaultModel: 'provider/chat', publishedApiModels: ['provider/chat'], enabledApiModels: ['provider/chat'], apiTokenCosts: { 'provider/chat': 0.2 }, apiTierAccess: { mini: ['provider/chat'], plus: [], pro: ['provider/chat'], business: [] }, contextChars: 60000, localNumCtx: 16384, localTimeoutSeconds: 60, apiTimeoutSeconds: 60 },
    },
    ollama: { ok: true, baseUrl: 'http://ollama.test:11434', models: [{ name: 'gemma4:12b', size: 8021618941, details: { parameter_size: '12B', quantization_level: 'Q4' } }, { name: 'ornith-1.5:9b', size: 6550813657, details: { parameter_size: '9B', quantization_level: 'Q4' } }] },
    ollamaResidency: { ok: true, models: [{ name: 'gemma4:12b', size_vram: 4294967296 }] }, openrouterConfigured: true,
    usage: { periodDays: 30, totals: { successful: 0, failed: 0, fallbacks: 0, cost_usd: 0, cost_rub: 0, energy_wh: 0, energy_cost_rub: 0 }, recent: [] },
    openrouterModels: [{
      id: 'provider/chat', name: 'Test Chat Model', provider: 'Provider', created: 1700000000,
      inputPerMillionUsd: 1, outputPerMillionUsd: 2, contextLength: 64000,
      economics: {
        schema: 'text-model-economics-v1', priceStatus: 'priced', priceSource: 'openrouter_text_catalog', priceObservedAt: '2026-08-28T10:00:00+00:00',
        exchangeRate: 100, fundingReservePercent: 30, minimumMarginPercent: 50, tokenRub: 5,
        inputPerMillion: { quotedCostUsd: 1, quotedCostRub: 130, reservedTokens: 52, revenueRub: 260, profitRub: 130, marginPercent: 50 },
        outputPerMillion: { quotedCostUsd: 2, quotedCostRub: 260, reservedTokens: 104, revenueRub: 520, profitRub: 260, marginPercent: 50 },
        millionRussianChars: { charsPerProviderToken: 4, assumedProviderTokens: 250000, approximate: true, input: { reservedTokens: 13 }, output: { reservedTokens: 26 } },
        sample1000Input500Output: { reservedTokens: 0.104 },
      },
    }],
    chatUsage: { priced: 1, averageCostUsd: 0.01, marginPercent: 50, perModel: { 'provider/chat': { answers: 2, priced: 1, averageCostUsd: 0.01, settledTokens: 1, revenueRub: 5, profitRub: 2.5, marginPercent: 50 } } },
    openrouterAudioModels: [],
  })))
}

async function verify(viewport) {
  const page = await browser.newPage({ viewport })
  const unexpectedOllamaRequests = []
  page.on('request', (request) => {
    if (new URL(request.url()).port === '11434') unexpectedOllamaRequests.push(request.url())
  })
  await mockAdmin(page)
  if (viewport.width <= 980) {
    await page.addInitScript(() => window.localStorage.setItem('admin.sidebar.collapsed', '1'))
  }
  await page.goto(`${baseURL}/admin/models`, { waitUntil: 'networkidle', timeout: 40000 })
  try {
    await page.getByRole('navigation', { name: 'Разделы админки' }).waitFor({ state: 'attached' })
  } catch (error) {
    console.error((await page.locator('body').innerText()).slice(0, 3000))
    throw error
  }
  assert(new URL(page.url()).pathname === pages[0][1], 'legacy /admin/models was not canonicalized')
  assert(await page.locator('.admin-sidebar').count() === 1, 'admin sidebar is missing')
  assert(await page.locator('.page-tabs').count() === 0, 'duplicated models tab bar is still rendered')
  assert(await page.locator('.openrouter-page-nav').count() === 0, 'duplicated OpenRouter tab bar is still rendered')
  assert(await page.locator('.openrouter-page-title').count() === 0, 'duplicated OpenRouter page title is still rendered')
  const textRow = page.locator('.text-model-row', { hasText: 'Test Chat Model' })
  await textRow.waitFor()
  assert(await textRow.locator('.text-model-publication input').isChecked(), 'text publication was not restored')
  assert(await textRow.locator('.tariffs label', { hasText: 'MINI' }).locator('input').isChecked(), 'MINI tariff access was not restored')
  assert(!(await textRow.locator('.tariffs label', { hasText: 'PLUS' }).locator('input').isChecked()), 'PLUS tariff access was incorrectly enabled')
  assert(await textRow.locator('.publication input[type="checkbox"]').count() === 1, 'text model has more than one publication checkbox')
  const textBody = await textRow.innerText()
  assert(textBody.includes('2023'), 'text release date is not rendered before controls')
  assert(textBody.includes('52') && textBody.includes('104'), 'canonical product-token prices per million are not rendered')
  assert(textBody.includes('1 млн русских символов'), 'Russian-character estimate is not rendered')
  const textCheckboxSize = await textRow.locator('.text-model-publication input').evaluate((element) => ({ width: element.getBoundingClientRect().width, height: element.getBoundingClientRect().height }))
  assert(textCheckboxSize.width === 16 && textCheckboxSize.height === 16, `text checkbox size is ${textCheckboxSize.width}x${textCheckboxSize.height}`)
  assert(!(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1)), `text catalog overflows at ${viewport.width}px`)
  await page.screenshot({ path: `${outDir}/admin-text-${viewport.width}.png`, fullPage: true })
  for (const [label, path, heading] of openrouterPages) {
    if (viewport.width <= 980 && !(await page.locator('.admin-sidebar').evaluate((element) => element.classList.contains('mobile-open')))) {
      await page.getByRole('button', { name: 'Открыть меню админки' }).click()
    }
    await page.getByRole('link', { name: label, exact: true }).click()
    await page.getByRole('heading', { name: heading, exact: true }).first().waitFor()
    assert(new URL(page.url()).pathname === path, `${label} OpenRouter page did not open its own URL`)
    if (label === 'Изображения') {
      await page.getByRole('button', { name: /По тексту/ }).first().click()
      const published = page.getByLabel('Опубликовать Test Image для пользователей')
      const hidden = page.getByLabel('Опубликовать Hidden Image для пользователей')
      await published.waitFor()
      assert(await published.isChecked(), 'published image model is not marked as published')
      assert(!(await hidden.isChecked()), 'hidden image model is incorrectly marked as published')
      assert(await page.getByLabel('Включить Hidden Image для По тексту').isDisabled(), 'hidden model operation can be enabled before publication')
      assert((await page.locator('body').innerText()).includes('2023'), 'provider release date is not rendered')
      assert((await page.locator('body').innerText()).includes('не указана поставщиком'), 'missing release date is not explained')
      assert(!(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1)), `image catalog overflows at ${viewport.width}px`)
      await page.screenshot({ path: `${outDir}/admin-images-${viewport.width}.png`, fullPage: true })
    }
    if (label === 'Видео') {
      await page.getByRole('button', { name: /Видео по тексту/ }).first().click()
      const videoRow = page.locator('.video-finance-table .api-model-row', { hasText: 'Test Video' })
      await videoRow.waitFor()
      assert((await videoRow.innerText()).includes('2023'), 'video release date is not rendered')
      assert(await videoRow.getByLabel('Публиковать Test Video').isChecked(), 'video publication was not restored')
      assert(!(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1)), `video catalog overflows at ${viewport.width}px`)
      await page.screenshot({ path: `${outDir}/admin-video-${viewport.width}.png`, fullPage: true })
    }
  }

  for (const [label, path, heading] of pages) {
    if (viewport.width <= 980 && !(await page.locator('.admin-sidebar').evaluate((element) => element.classList.contains('mobile-open')))) {
      await page.getByRole('button', { name: 'Открыть меню админки' }).click()
    }
    await page.getByRole('link', { name: label, exact: true }).click()
    await page.getByRole('heading', { name: heading, exact: true }).first().waitFor()
    assert(new URL(page.url()).pathname === path, `${label} did not open its own URL`)
    if (viewport.width > 980) assert(await page.getByRole('link', { name: label, exact: true }).getAttribute('aria-current') === 'page', `${label} is not selected`)
    if (label === 'Ollama') {
      assert(await page.getByLabel('Основная модель Ollama').inputValue() === 'gemma4:12b', 'initial Ollama chat model differs from backend data')
      assert((await page.locator('body').innerText()).includes('4.00 ГиБ'), 'resident GPU VRAM was not displayed')
      assert((await page.locator('body').innerText()).includes('http://ollama.test:11434'), 'server URL was not displayed')
      await page.getByLabel('Основная модель Ollama').selectOption('ornith-1.5:9b')
      const request = page.waitForRequest((req) => req.url().includes('/api/admin/settings/assistant_models') && req.method() === 'POST')
      await page.getByRole('button', { name: 'Сохранить настройки Ollama' }).click()
      const saved = JSON.parse((await request).postData())
      assert(saved.settings?.chat?.localModel === 'ornith-1.5:9b', 'model selection was not submitted through existing admin settings API')
      assert(!(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1)), `Ollama overflows at ${viewport.width}px`)
      await page.screenshot({ path: `${outDir}/admin-ollama-${viewport.width}.png`, fullPage: true })
      const onlineSnapshot = await page.evaluate(async () => (await fetch('/api/admin/assistants')).json())
      const offlineHandler = (route) => route.fulfill(json({
        ...onlineSnapshot,
        ollama: { ok: false, baseUrl: 'http://127.0.0.1:1', models: [], error: 'ConnectError' },
        ollamaResidency: { ok: false, models: [] },
      }))
      await page.route('**/api/admin/assistants', offlineHandler)
      await page.getByRole('button', { name: 'Обновить состояние' }).click()
      await page.getByText('Недоступно', { exact: true }).first().waitFor()
      assert(await page.getByRole('button', { name: 'Проверить Ollama' }).isDisabled(), 'offline Ollama must not allow a test request')
      await page.unroute('**/api/admin/assistants', offlineHandler)
      await page.getByRole('button', { name: 'Обновить состояние' }).click()
      await page.getByText('Доступно', { exact: true }).first().waitFor()
    }
  }

  await page.goBack()
  await page.getByRole('heading', { name: 'Голосовой ввод', exact: true }).first().waitFor()
  assert(new URL(page.url()).pathname === '/admin/models/voice-input', 'browser Back did not restore the previous models page')
  if (viewport.width > 980) {
    await page.screenshot({ path: `${outDir}/admin-sidebar-${viewport.width}.png`, fullPage: true })
    await page.getByRole('button', { name: 'Свернуть боковую панель' }).click()
    assert(await page.locator('.admin-shell-layout').evaluate((element) => element.classList.contains('nav-collapsed')), 'desktop sidebar did not collapse')
    await page.screenshot({ path: `${outDir}/admin-sidebar-${viewport.width}-collapsed.png`, fullPage: true })
  } else {
    await page.getByRole('button', { name: 'Открыть меню админки' }).click()
    await page.locator('.admin-sidebar.mobile-open').waitFor()
    await page.waitForTimeout(250)
    await page.screenshot({ path: `${outDir}/admin-sidebar-${viewport.width}.png`, fullPage: true })
    await page.getByRole('button', { name: 'Закрыть меню', exact: true }).click()
  }
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1)
  assert(!overflow, `models navigation overflows at ${viewport.width}px`)
  assert(unexpectedOllamaRequests.length === 0, `Browser connected directly to Ollama: ${unexpectedOllamaRequests.join(', ')}`)
  await page.close()
}

const browser = await chromium.launch({ headless: true })
try {
  for (const viewport of [
    { width: 1920, height: 1080 },
    { width: 1440, height: 900 },
    { width: 1280, height: 720 },
    { width: 1024, height: 768 },
    { width: 768, height: 1024 },
    { width: 390, height: 844 },
  ]) await verify(viewport)
  console.log('e2e-admin-model-pages OK')
} finally {
  await browser.close()
}
