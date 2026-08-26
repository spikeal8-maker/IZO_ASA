import { chromium } from 'playwright'

const baseURL = process.env.E2E_BASE_URL || 'http://127.0.0.1:4178'
const json = (body, status = 200) => ({ status, contentType: 'application/json', body: JSON.stringify(body) })
const thread = { id: 'desktop-chat-thread', title: 'Проверка инструментов', chatModelId: 'local:izo-chat', imageModelId: null, videoModelId: null, contextChars: 60000, createdAt: '2026-08-26T00:00:00Z', updatedAt: '2026-08-26T00:00:00Z' }
const longThread = { ...thread, id: 'desktop-chat-long', title: 'Очень длинный диалог для проверки прокрутки', updatedAt: '2026-08-25T23:00:00Z' }
const savedThreads = [thread, longThread, ...Array.from({ length: 18 }, (_, index) => ({ ...thread, id: `desktop-chat-${index}`, title: `Сохранённый диалог ${index + 1}`, updatedAt: `2026-08-25T${String(22 - index).padStart(2, '0')}:00:00Z` }))]
const longMessages = Array.from({ length: 36 }, (_, index) => ({ id: `long-${index}`, role: index % 2 ? 'assistant' : 'user', content: `Сообщение ${index + 1}. ${'Длинный текст для проверки устойчивой прокрутки чата. '.repeat(4)}`, provider: 'local', model: 'local:izo-chat', tools: [], chargedTokens: 0, tokenKind: 'free', createdAt: new Date().toISOString(), status: 'done' }))
const image = 'data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%221024%22 height=%221024%22%3E%3Crect width=%221024%22 height=%221024%22 fill=%22%23b72ad8%22/%3E%3C/svg%3E'

function assert(condition, message) { if (!condition) throw new Error(message) }

const browser = await chromium.launch({ headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  await page.addInitScript(() => {
    window.__chatMicTest = { requested: 0, started: 0, stoppedTracks: 0 }
    const stream = () => ({ getTracks: () => [{ stop: () => { window.__chatMicTest.stoppedTracks += 1 } }] })
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia: () => {
      window.__chatMicTest.requested += 1
      return new Promise((resolve) => setTimeout(() => resolve(stream()), 80))
    } } })
    class FakeMediaRecorder extends EventTarget {
      static isTypeSupported() { return true }
      constructor(mediaStream, options = {}) { super(); this.stream = mediaStream; this.mimeType = options.mimeType || 'audio/webm'; this.state = 'inactive' }
      start() { this.state = 'recording'; window.__chatMicTest.started += 1 }
      stop() { this.state = 'inactive'; queueMicrotask(() => this.dispatchEvent(new Event('stop'))) }
    }
    Object.defineProperty(window, 'MediaRecorder', { configurable: true, value: FakeMediaRecorder })
  })
  const errors = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    const method = route.request().method()
    if (url.pathname === '/api/auth/bootstrap-v2') return route.fulfill(json({ installation_id: 'desktop-chat', anonymous_id: 'desktop-chat' }))
    if (url.pathname === '/api/me-v2' || url.pathname === '/api/auth/session/refresh-v2') return route.fulfill(json({ internal_user_id: 'desktop-chat', profile: { display_name: 'Тестовый пользователь' }, account: { role: 'user', plan: 'mini', token_balance: 20, daily_tokens_limit: 25, daily_tokens_remaining: 24 } }))
    if (url.pathname === '/api/auth/capabilities-v2') return route.fulfill(json({ password_login_available: true }))
    if (url.pathname === '/api/phone/chat/threads' && method === 'GET') return route.fulfill(json({ ok: true, threads: savedThreads }))
    if (url.pathname === '/api/phone/chat/threads' && method === 'POST') return route.fulfill(json({ ok: true, thread }))
    if (url.pathname === `/api/phone/chat/threads/${longThread.id}/messages`) return route.fulfill(json({ ok: true, thread: longThread, messages: longMessages }))
    if (/\/api\/phone\/chat\/threads\/[^/]+\/messages$/.test(url.pathname)) return route.fulfill(json({ ok: true, thread, messages: [] }))
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
  const initialLayout = await page.evaluate(() => {
    const topbar = document.querySelector('.iv3 .topbar')?.getBoundingClientRect()
    const workspace = document.querySelector('.desktop-chat')?.getBoundingClientRect()
    const composer = document.querySelector('.dc-composer')?.getBoundingClientRect()
    return { topbar, workspace, composer, pageY: window.scrollY, bodyY: document.documentElement.scrollTop }
  })
  assert(initialLayout.topbar && initialLayout.topbar.top >= 0 && initialLayout.topbar.bottom <= 90, 'site header is outside viewport')
  assert(initialLayout.workspace && initialLayout.workspace.bottom <= 901 && initialLayout.workspace.height > 700, 'chat workspace does not fill the available viewport')
  assert(initialLayout.composer && initialLayout.composer.bottom <= 900, 'composer is outside viewport')
  assert(initialLayout.pageY === 0 && initialLayout.bodyY === 0, 'document scrolled during chat initialization')
  await page.getByRole('button', { name: longThread.title }).click()
  await page.getByText('Сообщение 36.', { exact: false }).waitFor()
  const longLayout = await page.evaluate(() => {
    const topbar = document.querySelector('.iv3 .topbar')?.getBoundingClientRect()
    const messages = document.querySelector('.dc-messages')
    const composer = document.querySelector('.dc-composer')?.getBoundingClientRect()
    const threadList = document.querySelector('.dc-thread-list')
    return { topbar, composer, pageY: window.scrollY, bodyY: document.documentElement.scrollTop, messages: messages ? { scrollTop: messages.scrollTop, scrollHeight: messages.scrollHeight, clientHeight: messages.clientHeight } : null, threadList: threadList ? { scrollHeight: threadList.scrollHeight, clientHeight: threadList.clientHeight } : null }
  })
  assert(longLayout.topbar && longLayout.topbar.top >= 0, 'site header moved after opening a long chat')
  assert(longLayout.composer && longLayout.composer.bottom <= 900, 'composer moved after opening a long chat')
  assert(longLayout.pageY === 0 && longLayout.bodyY === 0, 'opening a long chat scrolled the page shell')
  assert(longLayout.messages && longLayout.messages.scrollHeight > longLayout.messages.clientHeight && longLayout.messages.scrollTop > 0, 'messages do not use an independent scroll area')
  assert(longLayout.threadList && longLayout.threadList.scrollHeight > longLayout.threadList.clientHeight, 'thread list does not use an independent scroll area')
  await page.getByRole('button', { name: thread.title }).click()
  await page.getByRole('heading', { name: 'Что хотите сделать?' }).waitFor()
  assert(await page.locator('.openrouter-page-nav').count() === 0, 'admin navigation leaked into chat')
  await page.getByRole('button', { name: /ИЗО Чат/ }).last().click()
  const unavailable = page.getByRole('button', { name: /Профессиональная модель/ })
  assert(await unavailable.isDisabled(), 'tariff-blocked model is selectable')
  await page.getByRole('button', { name: 'Закрыть', exact: true }).click()
  await page.getByPlaceholder('Сообщение…').fill('Найди погоду и создай изображение Москвы')
  await page.getByRole('button', { name: 'Отправить' }).click()
  await page.getByText('Нашёл свежую информацию и подготовил изображение.').waitFor()
  await page.getByText('Источник погоды').waitFor()
  await page.getByAltText('Созданное изображение').first().waitFor()
  await page.getByText('Результат').waitFor()
  const previewBefore = await page.locator('.dc-artifact').evaluate((node) => node.getBoundingClientRect().width)
  const divider = page.getByRole('separator', { name: 'Изменить ширину предпросмотра' })
  const dividerBox = await divider.boundingBox()
  assert(dividerBox, 'preview divider is missing')
  await page.mouse.move(dividerBox.x + 2, dividerBox.y + dividerBox.height / 2)
  await page.mouse.down()
  await page.mouse.move(dividerBox.x - 100, dividerBox.y + dividerBox.height / 2, { steps: 5 })
  await page.mouse.up()
  const previewAfter = await page.locator('.dc-artifact').evaluate((node) => node.getBoundingClientRect().width)
  assert(previewAfter > previewBefore + 24, 'preview divider did not resize the artifact panel')
  await page.getByRole('button', { name: 'Закрыть предпросмотр' }).click()
  assert(await page.locator('.dc-artifact').count() === 0, 'preview did not close')
  await page.setViewportSize({ width: 1024, height: 720 })
  await page.locator('.dc-image-result').click()
  await page.locator('.dc-artifact').waitFor()
  const compactLayout = await page.evaluate(() => ({
    topbar: document.querySelector('.iv3 .topbar')?.getBoundingClientRect(),
    artifact: document.querySelector('.dc-artifact')?.getBoundingClientRect(),
    horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 2,
    pageY: window.scrollY,
  }))
  assert(compactLayout.topbar && compactLayout.topbar.top >= 0, 'compact layout moved the site header')
  assert(compactLayout.artifact && compactLayout.artifact.left >= 0 && compactLayout.artifact.right <= 1024, 'compact preview is clipped')
  assert(!compactLayout.horizontalOverflow && compactLayout.pageY === 0, 'compact chat overflows or scrolls the page shell')
  await page.getByRole('button', { name: 'Закрыть предпросмотр' }).click()
  assert(!(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 2)), 'desktop chat overflows horizontally')

  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload({ waitUntil: 'networkidle' })
  await page.getByRole('heading', { name: 'Что хотите сделать?' }).waitFor()
  const mobileLayout = await page.evaluate(() => ({
    bodyOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    pageY: window.scrollY,
    sidebarTransform: getComputedStyle(document.querySelector('.dc-sidebar')).transform,
    composer: document.querySelector('.dc-composer')?.getBoundingClientRect(),
    messages: document.querySelector('.dc-messages')?.getBoundingClientRect(),
  }))
  assert(!mobileLayout.bodyOverflow && mobileLayout.pageY === 0, 'mobile page shell scrolls or overflows horizontally')
  assert(mobileLayout.sidebarTransform !== 'none' && mobileLayout.sidebarTransform.includes('-'), 'mobile history is not initially hidden')
  assert(mobileLayout.composer && mobileLayout.messages && mobileLayout.composer.bottom <= 844 && mobileLayout.messages.bottom <= mobileLayout.composer.top, 'mobile composer overlaps the message scroll area')
  await page.getByRole('button', { name: 'Показать историю' }).click()
  assert(await page.locator('.dc-sidebar-backdrop').isVisible(), 'mobile history backdrop is missing')
  await page.mouse.click(375, 420)
  await page.getByRole('button', { name: /ИЗО Чат/ }).last().click()
  const modelSheet = page.getByRole('dialog', { name: 'Выбор модели' })
  await modelSheet.waitFor()
  const sheetBox = await modelSheet.boundingBox()
  assert(sheetBox && sheetBox.x >= 0 && sheetBox.x + sheetBox.width <= 390 && sheetBox.y + sheetBox.height <= 844, 'mobile model sheet is clipped')
  for (const label of ['Чат', 'Изображение', 'Видео', 'Звук', '3D']) assert(await modelSheet.getByRole('button', { name: label, exact: true }).count() === 1, `model category is missing: ${label}`)
  const modelSheetLayout = await page.evaluate(() => ({ nav: document.querySelector('.dc-model-popover > nav')?.getBoundingClientRect(), list: document.querySelector('.dc-model-list')?.getBoundingClientRect() }))
  assert(modelSheetLayout.nav && modelSheetLayout.list && modelSheetLayout.nav.height >= 32 && modelSheetLayout.list.top >= modelSheetLayout.nav.bottom - 1, 'model categories are collapsed or covered by the model list')
  await page.getByRole('button', { name: 'Закрыть', exact: true }).click()

  const mic = page.getByRole('button', { name: 'Удерживайте, чтобы говорить' })
  const micBox = await mic.boundingBox()
  assert(micBox, 'microphone button is missing')
  await page.mouse.move(micBox.x + micBox.width / 2, micBox.y + micBox.height / 2)
  await page.mouse.down(); await page.waitForTimeout(20); await page.mouse.up(); await page.waitForTimeout(140)
  const quickMic = await page.evaluate(() => window.__chatMicTest)
  assert(quickMic.requested === 1 && quickMic.started === 0 && quickMic.stoppedTracks === 1, 'quick microphone release left a recorder or stream active')
  await page.mouse.down(); await page.waitForTimeout(120); await page.mouse.up(); await page.waitForTimeout(80)
  const heldMic = await page.evaluate(() => window.__chatMicTest)
  assert(heldMic.requested === 2 && heldMic.started === 1 && heldMic.stoppedTracks === 2, 'held microphone did not start and release cleanly')
  await page.getByPlaceholder('Сообщение…').fill('Создай изображение для проверки мобильного предпросмотра')
  await page.getByRole('button', { name: 'Отправить' }).click()
  await page.locator('.dc-artifact').waitFor()
  const mobileArtifactLayout = await page.evaluate(() => ({ chat: document.querySelector('.desktop-chat')?.getBoundingClientRect(), artifact: document.querySelector('.dc-artifact')?.getBoundingClientRect(), bodyHeight: document.documentElement.scrollHeight, viewport: innerHeight }))
  assert(mobileArtifactLayout.chat && mobileArtifactLayout.artifact && mobileArtifactLayout.chat.bottom <= mobileArtifactLayout.viewport + 1 && mobileArtifactLayout.artifact.bottom <= mobileArtifactLayout.viewport + 1, 'mobile artifact stretches beyond the viewport')
  assert(mobileArtifactLayout.bodyHeight <= mobileArtifactLayout.viewport + 1, 'mobile artifact makes the document scroll')
  assert(errors.length === 0, `page errors: ${errors.join('; ')}`)
  console.log('DESKTOP_CHAT_E2E_OK persistence=true webSearch=true imageTool=true tariffGuard=true mobileScroll=true modelSheet=true microphoneState=true')
} finally {
  await browser.close()
}
