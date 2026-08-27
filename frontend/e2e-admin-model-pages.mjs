import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'

const baseURL = process.env.QA_ADMIN_BASE_URL || 'http://127.0.0.1:5175'
const outDir = process.env.QA_ARTIFACT_DIR || 'visual-out'
mkdirSync(outDir, { recursive: true })
const pages = [
  ['OpenRouter', '/admin/models/openrouter/text', 'Текстовые модели OpenRouter'],
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
      videoCatalog: [], videoConfig: {}, videoUsage: {},
    },
  })))
  await page.route('**/api/admin/energy**', (route) => route.fulfill(json({ detail: 'isolated navigation test' }, 503)))
  await page.route('**/api/admin/voice**', (route) => route.fulfill(json({ detail: 'isolated navigation test' }, 503)))
  await page.route('**/api/admin/assistants', (route) => route.fulfill(json({
    config: {
      voice: { localModel: 'gemma4:12b', qwenModel: '', qwenBaseUrl: '', apiModel: '', route: 'local', queueTimeoutSeconds: 1, requestTimeoutSeconds: 45, minRecordingSeconds: 1 },
      improve: { route: 'local', localModel: 'gemma4:12b', apiModel: '', localTimeoutSeconds: 30, apiTimeoutSeconds: 10, systemPrompt: '', modePrompts: {} },
      chat: { enabled: true, localEnabled: true, localModel: 'gemma4:12b', localLabel: 'ИЗО Чат', localTokenCost: 0, defaultModel: 'provider/chat', enabledApiModels: ['provider/chat'], apiTokenCosts: { 'provider/chat': 0.2 }, apiTierAccess: { mini: ['provider/chat'], plus: [], pro: ['provider/chat'], business: [] }, contextChars: 60000, localNumCtx: 16384, localTimeoutSeconds: 60, apiTimeoutSeconds: 60 },
    },
    ollama: { ok: true, baseUrl: '', models: [] }, ollamaResidency: { ok: true, models: [] }, openrouterConfigured: true,
    usage: { periodDays: 30, totals: { successful: 0, failed: 0, fallbacks: 0, cost_usd: 0, cost_rub: 0, energy_wh: 0, energy_cost_rub: 0 }, recent: [] },
    openrouterModels: [{ id: 'provider/chat', name: 'Test Chat Model', inputPerMillionUsd: 1, outputPerMillionUsd: 2, contextLength: 64000 }],
    openrouterAudioModels: [],
  })))
}

async function verify(viewport) {
  const page = await browser.newPage({ viewport })
  await mockAdmin(page)
  if (viewport.width <= 980) {
    await page.addInitScript(() => window.localStorage.setItem('admin.sidebar.collapsed', '1'))
  }
  await page.goto(`${baseURL}/admin/models`, { waitUntil: 'networkidle', timeout: 40000 })
  try {
    if (viewport.width <= 980) await page.getByRole('button', { name: 'Открыть меню админки' }).click()
    await page.getByRole('navigation', { name: 'Разделы админки' }).waitFor()
  } catch (error) {
    console.error((await page.locator('body').innerText()).slice(0, 3000))
    throw error
  }
  assert(new URL(page.url()).pathname === pages[0][1], 'legacy /admin/models was not canonicalized')
  assert(await page.locator('.admin-sidebar').count() === 1, 'admin sidebar is missing')
  assert(await page.locator('.page-tabs').count() === 0, 'duplicated models tab bar is still rendered')
  assert(await page.locator('.openrouter-page-nav').count() === 0, 'duplicated OpenRouter tab bar is still rendered')
  assert(await page.locator('.openrouter-page-title').count() === 0, 'duplicated OpenRouter page title is still rendered')
  await page.getByLabel('Test Chat Model — mini').waitFor()
  assert(await page.getByLabel('Test Chat Model — mini').isChecked(), 'MINI tariff access was not restored')
  assert(!(await page.getByLabel('Test Chat Model — plus').isChecked()), 'PLUS tariff access was incorrectly enabled')
  if (viewport.width <= 980) assert(await page.getByRole('link', { name: 'OpenRouter', exact: true }).isVisible(), 'saved desktop collapse hides mobile model pages')

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
      assert((await page.locator('body').innerText()).includes('14.11.2023'), 'provider release date is not rendered')
      assert((await page.locator('body').innerText()).includes('не указана поставщиком'), 'missing release date is not explained')
      await page.screenshot({ path: `${outDir}/admin-images-${viewport.width}.png`, fullPage: true })
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
  await page.close()
}

const browser = await chromium.launch({ headless: true })
try {
  await verify({ width: 1440, height: 900 })
  await verify({ width: 390, height: 844 })
  console.log('e2e-admin-model-pages OK')
} finally {
  await browser.close()
}
