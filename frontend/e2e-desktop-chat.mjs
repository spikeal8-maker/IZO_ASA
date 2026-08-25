import { chromium } from 'playwright'

const baseURL = process.env.E2E_BASE_URL || 'http://127.0.0.1:4178'
const json = (body, status = 200) => ({ status, contentType: 'application/json', body: JSON.stringify(body) })
const thread = { id: 'desktop-chat-thread', title: 'Проверка инструментов', chatModelId: 'local:izo-chat', imageModelId: null, videoModelId: null, contextChars: 60000, createdAt: '2026-08-26T00:00:00Z', updatedAt: '2026-08-26T00:00:00Z' }
const image = 'data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%221024%22 height=%221024%22%3E%3Crect width=%221024%22 height=%221024%22 fill=%22%23b72ad8%22/%3E%3C/svg%3E'

function assert(condition, message) { if (!condition) throw new Error(message) }

const browser = await chromium.launch({ headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  const errors = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    const method = route.request().method()
    if (url.pathname === '/api/auth/bootstrap-v2') return route.fulfill(json({ installation_id: 'desktop-chat', anonymous_id: 'desktop-chat' }))
    if (url.pathname === '/api/me-v2' || url.pathname === '/api/auth/session/refresh-v2') return route.fulfill(json({ internal_user_id: 'desktop-chat', profile: { display_name: 'Тестовый пользователь' }, account: { role: 'user', plan: 'mini', token_balance: 20, daily_tokens_limit: 25, daily_tokens_remaining: 24 } }))
    if (url.pathname === '/api/auth/capabilities-v2') return route.fulfill(json({ password_login_available: true }))
    if (url.pathname === '/api/phone/chat/threads' && method === 'GET') return route.fulfill(json({ ok: true, threads: [] }))
    if (url.pathname === '/api/phone/chat/threads' && method === 'POST') return route.fulfill(json({ ok: true, thread }))
    if (url.pathname === '/api/phone/chat/models') return route.fulfill(json({ ok: true, defaultModel: 'local:izo-chat', models: [
      { id: 'local:izo-chat', name: 'ИЗО Чат', provider: 'local', tokenCost: 0, tokenKind: 'free', description: 'Базовая модель', contextChars: 60000, available: true },
      { id: 'provider/pro', name: 'Профессиональная модель', provider: 'api', tokenCost: .2, tokenKind: 'main', description: 'Облачная модель', contextChars: 60000, available: false, unavailableReason: 'Недоступна на вашем тарифе' },
    ] }))
    if (url.pathname === '/api/phone/chat') return route.fulfill(json({ ok: true, reply: 'Нашёл свежую информацию и подготовил изображение.', modelId: 'local:izo-chat', chargedTokens: 0, tokenKind: 'free', messageId: 'assistant-1', tools: [
      { name: 'web_search', ok: true, query: 'Москва', sources: [{ title: 'Источник погоды', url: 'https://example.test/weather' }] },
      { name: 'generate_image', status: 'requested', prompt: 'Москва после дождя', aspectRatio: '1:1' },
    ] }))
    if (url.pathname === '/api/model-access') return route.fulfill(json({ modes: { text_to_image: { models: [{ id: 'server:local_flux_klein', provider: 'comfyui', modelProfile: 'local_flux_klein' }], presets: { fast: 'server:local_flux_klein' } } } }))
    if (url.pathname === '/api/generate') return route.fulfill(json({ id: 'desktop-image-job' }))
    if (url.pathname === '/api/phone/v1/jobs/desktop-image-job') return route.fulfill(json({ job: { id: 'desktop-image-job', modality: 'image', operation: 'text_to_image', status: 'completed', phase: 'terminal', progress: 100, message: '', createdAt: null, startedAt: null, completedAt: null, terminal: true, result: { id: 'image-1', type: 'image', url: image, thumbnailUrl: null, width: 1024, height: 1024, durationSeconds: null, aspectRatio: '1:1' }, billing: { chargedTokens: 1, tokenKind: 'daily', refunded: false } } }))
    if (url.pathname.includes('/tools')) return route.fulfill(json({ ok: true }))
    if (url.pathname === '/api/tariffs') return route.fulfill(json({ tariffs: {} }))
    if (url.pathname === '/api/models') return route.fulfill(json({ ok: true, profiles: [] }))
    if (url.pathname === '/api/model-access') return route.fulfill(json({ modes: {} }))
    return route.fulfill(json({ ok: true, items: [] }))
  })
  await page.goto(`${baseURL}/chat`, { waitUntil: 'networkidle' })
  await page.getByRole('heading', { name: 'Что хотите сделать?' }).waitFor()
  assert(await page.locator('.openrouter-page-nav').count() === 0, 'admin navigation leaked into chat')
  await page.getByRole('button', { name: /ИЗО Чат/ }).last().click()
  const unavailable = page.getByRole('button', { name: /Профессиональная модель/ })
  assert(await unavailable.isDisabled(), 'tariff-blocked model is selectable')
  await page.getByRole('button', { name: 'Закрыть' }).click()
  await page.getByPlaceholder('Сообщение…').fill('Найди погоду и создай изображение Москвы')
  await page.getByRole('button', { name: 'Отправить' }).click()
  await page.getByText('Нашёл свежую информацию и подготовил изображение.').waitFor()
  await page.getByText('Источник погоды').waitFor()
  await page.getByAltText('Созданное изображение').first().waitFor()
  await page.getByText('Результат').waitFor()
  assert(!(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 2)), 'desktop chat overflows horizontally')
  assert(errors.length === 0, `page errors: ${errors.join('; ')}`)
  console.log('DESKTOP_CHAT_E2E_OK persistence=true webSearch=true imageTool=true tariffGuard=true')
} finally {
  await browser.close()
}
