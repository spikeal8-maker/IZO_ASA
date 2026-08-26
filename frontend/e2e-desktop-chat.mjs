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
    class FakeAudioContext {
      createAnalyser() { return { fftSize: 256, frequencyBinCount: 128, getByteTimeDomainData: (data) => { data.fill(128); data[0] = 196; data[1] = 72 } } }
      createMediaStreamSource() { return { connect() {} } }
      close() { return Promise.resolve() }
    }
    Object.defineProperty(window, 'AudioContext', { configurable: true, value: FakeAudioContext })
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
  assert(await page.locator('.desktop-chat.theme-dark').count() === 1, 'dark theme is not the default')
  await page.getByRole('button', { name: 'Включить светлую тему' }).click()
  assert(await page.locator('.desktop-chat.theme-light').count() === 1, 'light theme toggle did not apply')
  await page.getByRole('button', { name: 'Включить тёмную тему' }).click()
  assert(await page.locator('.desktop-chat.theme-dark').count() === 1, 'dark theme toggle did not restore')
  const initialLayout = await page.evaluate(() => {
    const topbar = document.querySelector('.iv3 .topbar')?.getBoundingClientRect()
    const workspace = document.querySelector('.desktop-chat')?.getBoundingClientRect()
    const composer = document.querySelector('.dc-composer')?.getBoundingClientRect()
    const actions = document.querySelector('.dc-empty > div')?.getBoundingClientRect()
    const chatToolbar = document.querySelector('.dc-chat-toolbar')?.getBoundingClientRect()
    const threadRows = [...document.querySelectorAll('.thread-item')].map((node) => node.getBoundingClientRect().height)
    return { topbar, workspace, composer, actions, chatToolbar, threadRows, pageY: window.scrollY, bodyY: document.documentElement.scrollTop }
  })
  assert(initialLayout.topbar && initialLayout.topbar.top >= 0 && initialLayout.topbar.bottom <= 90, 'site header is outside viewport')
  assert(initialLayout.workspace && initialLayout.workspace.bottom <= 901 && initialLayout.workspace.height > 700, 'chat workspace does not fill the available viewport')
  assert(initialLayout.composer && initialLayout.composer.bottom <= 900, 'composer is outside viewport')
  assert(initialLayout.composer && initialLayout.composer.height <= 130, 'composer is not compact')
  assert(initialLayout.workspace && initialLayout.composer && Math.abs((initialLayout.composer.top + initialLayout.composer.height / 2) - (initialLayout.workspace.top + initialLayout.workspace.height / 2)) <= 12, 'empty composer is not centered in the chat viewport')
  assert(initialLayout.actions && initialLayout.composer && initialLayout.composer.top - initialLayout.actions.bottom >= 0 && initialLayout.composer.top - initialLayout.actions.bottom <= 90, 'empty composer is not directly below quick actions')
  assert(initialLayout.workspace && initialLayout.chatToolbar && initialLayout.chatToolbar.top >= initialLayout.workspace.top && initialLayout.chatToolbar.height >= 40, 'chat upper toolbar disappeared in empty state')
  assert(initialLayout.threadRows.every((height) => height <= 42), 'chat history rows are not compact')
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
  await page.getByPlaceholder('Сообщение…').focus()
  await page.evaluate(() => {
    const transfer = new DataTransfer()
    transfer.items.add(new File([new Uint8Array([137, 80, 78, 71])], 'clipboard.png', { type: 'image/png' }))
    document.querySelector('.dc-composer textarea')?.dispatchEvent(new ClipboardEvent('paste', { bubbles: true, cancelable: true, clipboardData: transfer }))
  })
  await page.locator('.dc-attachments img').waitFor()
  assert(await page.locator('.dc-attachments img').count() === 1, 'clipboard image was not attached')
  await page.locator('.dc-attachments button').click()
  await page.getByPlaceholder('Сообщение…').fill('Найди погоду и создай изображение Москвы')
  await page.getByRole('button', { name: 'Отправить' }).click()
  await page.getByText('Нашёл свежую информацию и подготовил изображение.').waitFor()
  await page.getByText('Источник погоды').waitFor()
  await page.getByAltText('Созданное изображение').first().waitFor()
  assert(await page.locator('.thread-item.active.kind-image').count() === 1, 'image chat is missing its image marker in history')
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
  await page.mouse.down(); await page.waitForTimeout(220)
  assert(await page.locator('.dc-live-wave').isVisible(), 'live microphone waveform is not shown while holding')
  assert(await page.locator('.dc-live-wave i').evaluateAll((bars) => bars.some((bar) => Number.parseFloat(getComputedStyle(bar).height) > 3)), 'microphone waveform does not react to audio amplitude')
  assert(await page.getByRole('button', { name: /ИЗО Чат/ }).last().count() === 0, 'model chooser remains visible during voice recording')
  await page.mouse.up(); await page.waitForTimeout(80)
  const heldMic = await page.evaluate(() => window.__chatMicTest)
  assert(heldMic.requested === 2 && heldMic.started === 1 && heldMic.stoppedTracks === 2, 'held microphone did not start and release cleanly')
  await page.getByPlaceholder('Сообщение…').fill('Создай изображение для проверки мобильного предпросмотра')
  await page.getByRole('button', { name: 'Отправить' }).click()
  await page.locator('.dc-artifact').waitFor()
  const mobileArtifactLayout = await page.evaluate(() => ({ chat: document.querySelector('.desktop-chat')?.getBoundingClientRect(), artifact: document.querySelector('.dc-artifact')?.getBoundingClientRect(), bodyHeight: document.documentElement.scrollHeight, viewport: innerHeight }))
  assert(mobileArtifactLayout.chat && mobileArtifactLayout.artifact && mobileArtifactLayout.chat.bottom <= mobileArtifactLayout.viewport + 1 && mobileArtifactLayout.artifact.bottom <= mobileArtifactLayout.viewport + 1, 'mobile artifact stretches beyond the viewport')
  assert(mobileArtifactLayout.bodyHeight <= mobileArtifactLayout.viewport + 1, 'mobile artifact makes the document scroll')

  const verifyChatAuthReturn = async (mode) => {
    const context = await browser.newContext({ viewport: { width: 1280, height: 800 } })
    const authPage = await context.newPage()
    let authenticated = false
    await authPage.route('**/api/**', async (route) => {
      const url = new URL(route.request().url())
      if (url.pathname === '/api/auth/bootstrap-v2') return route.fulfill(json({ installation_id: `desktop-chat-${mode}`, anonymous_id: `desktop-chat-${mode}` }))
      if (url.pathname === '/api/auth/capabilities-v2') return route.fulfill(json({ password_login_available: true, password_register_available: true, email_otp_available: false }))
      if (url.pathname === '/api/auth/session/refresh-v2') return route.fulfill(json(authenticated ? { ok: true } : { detail: 'unauthorized' }, authenticated ? 200 : 401))
      if (url.pathname === '/api/me-v2') return route.fulfill(json(authenticated ? { internal_user_id: `desktop-chat-${mode}`, profile: { display_name: 'Проверка входа' }, account: { role: 'user', plan: 'mini', token_balance: 20, daily_tokens_limit: 25, daily_tokens_remaining: 24 } } : { detail: 'unauthorized' }, authenticated ? 200 : 401))
      if (url.pathname === `/api/auth/password/${mode}-v2`) { authenticated = true; return route.fulfill(json({ ok: true, requires_email_verification: false })) }
      if (url.pathname === '/api/phone/chat/threads') return route.fulfill(json({ ok: true, threads: [] }))
      if (url.pathname === '/api/phone/chat/models') return route.fulfill(json({ ok: true, defaultModel: 'local:izo-chat', models: [{ id: 'local:izo-chat', name: 'ИЗО Чат', provider: 'local', tokenCost: 0, tokenKind: 'free', description: 'Базовая модель', contextChars: 60000, available: true }] }))
      return route.fulfill(json({ ok: true, items: [] }))
    })
    await authPage.goto(`${baseURL}/chat`, { waitUntil: 'networkidle' })
    await authPage.getByRole('button', { name: 'Войти для проверки' }).click()
    if (mode === 'register') await authPage.getByRole('button', { name: 'Регистрация' }).click()
    await authPage.getByLabel('Email').fill(`${mode}@example.test`)
    await authPage.getByLabel('Пароль', { exact: true }).fill('Password!123')
    if (mode === 'register') await authPage.getByLabel('Повторите пароль').fill('Password!123')
    await authPage.getByRole('button', { name: mode === 'login' ? 'Войти' : 'Создать аккаунт', exact: true }).last().click()
    await authPage.getByRole('heading', { name: 'Что хотите сделать?' }).waitFor()
    assert(new URL(authPage.url()).pathname === '/chat', `${mode} redirected away from the chat`)
    await context.close()
  }
  await verifyChatAuthReturn('login')
  await verifyChatAuthReturn('register')
  assert(errors.length === 0, `page errors: ${errors.join('; ')}`)
  console.log('DESKTOP_CHAT_E2E_OK persistence=true webSearch=true imageTool=true clipboardImage=true tariffGuard=true compactHistory=true centeredComposer=true mobileScroll=true modelSheet=true microphoneWaveform=true microphoneState=true loginReturn=true registrationReturn=true')
} finally {
  await browser.close()
}
