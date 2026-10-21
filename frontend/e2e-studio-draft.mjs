import { spawn } from 'node:child_process'
import { mkdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

const origin = process.env.STUDIO207_URL || 'http://127.0.0.1:5227'
const evidence = 'C:/Users/spike/studio207-evidence'
const pixel = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2n0kAAAAASUVORK5CYII='
let preview

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

async function waitForPreview() {
  const deadline = Date.now() + 25_000
  while (Date.now() < deadline) {
    try { if ((await fetch(origin)).ok) return }
    catch { /* preview not ready */ }
    await new Promise((resolve) => setTimeout(resolve, 250))
  }
  throw new Error('Preview failed to start on isolated port 5227')
}

async function mockStudio(context, state) {
  await context.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    const json = (data, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) })
    if (path === '/api/auth/bootstrap-v2') return json({ installation_id: 'test-install-studio207', anonymous_id: 'test-anon-studio207' })
    if (path === '/api/me-v2') {
      if (!state.accountId) return json({ detail: 'not authenticated' }, 401)
      return json({
        internal_user_id: state.accountId, status: 'active',
        profile: { display_name: state.accountId, gender: 'female' },
        account: { role: 'user', plan: 'plus', token_balance: 50, daily_tokens_limit: 50, daily_tokens_remaining: 50 },
        session: { provider: 'web_email', platform: 'web_desktop' },
      })
    }
    if (path === '/api/auth/refresh-v2' || path === '/api/auth/bot-login/status') return json({ detail: 'not authenticated' }, 401)
    if (path === '/api/auth/capabilities-v2') return json({ capabilities_loaded: true, password_login_available: true })
    if (path === '/api/models') return json({ loras: [] })
    if (path === '/api/tariffs') return json({ ok: false })
    if (path === '/api/model-access') return json({ ok: false })
    if (path === '/api/gallery/items' || path === '/api/gallery/secondary') return json({ items: [] })
    if (path === '/api/feed') return json({ items: [] })
    if (path === '/api/generate') {
      state.posts += 1
      if (state.failGenerate) return json({ detail: 'temporary outage' }, 503)
      return json({ id: 'studio207-job', status: 'queued', progress: 0 })
    }
    if (path.startsWith('/api/jobs/')) return json({ id: 'studio207-job', status: 'completed', progress: 100, resultUrl: pixel })
    if (path === '/api/auth/session/logout-v2') { state.accountId = null; return json({ ok: true }) }
    return json({ ok: true, items: [] })
  })
}

async function awaitPrompt(page, expected) {
  const input = page.locator('.prompt-section textarea').first()
  await input.waitFor({ state: 'visible', timeout: 20_000 })
  await page.waitForFunction((value) => document.querySelector('.prompt-section textarea')?.value === value, expected, { timeout: 10_000 })
  return input
}

async function visit(page) {
  await page.goto(origin + '/#text-to-image', { waitUntil: 'domcontentloaded' })
  await awaitPrompt(page, '')
}

async function reloadExpect(page, expected) {
  await page.reload({ waitUntil: 'domcontentloaded' })
  await awaitPrompt(page, expected)
}

async function guestCase(browser, name, viewport) {
  const context = await browser.newContext({ viewport })
  const state = { accountId: null, posts: 0, failGenerate: false }
  await mockStudio(context, state)
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', (e) => errors.push(String(e)))
  try {
    await visit(page)
    const value = ('Studio черновик ' + name + ' — ').padEnd(54, 'x')
    assert(value.length === 54, 'fixture length')
    await page.locator('.prompt-section textarea').fill(value)
    await reloadExpect(page, value)
    const row = await page.evaluate(() => sessionStorage.getItem('izo:studio-draft-v2:guest'))
    assert(row?.includes(value), name + ': scoped storage missing prompt')
    assert(!await page.evaluate(() => sessionStorage.getItem('izo:studio-draft-v1')), name + ': unexpected legacy write')
    assert(state.posts === 0, name + ': draft hydration initiated generation POST')
    if (name === 'desktop') {
      // Each mode owns a separate text buffer; changing tabs preserves both.
      const tabs = page.locator('.image-mode-tabs [role="tab"]')
      await tabs.nth(1).click()
      await awaitPrompt(page, '')
      const photoText = 'Изменить стиль фотографии без изменения объекта'
      await page.locator('.prompt-section textarea').fill(photoText)
      await tabs.nth(0).click()
      await awaitPrompt(page, value)
      await reloadExpect(page, value)
      await tabs.nth(1).click()
      await awaitPrompt(page, photoText)
      await page.locator('.prompt-section textarea').fill('')
      await reloadExpect(page, value)
      await tabs.nth(1).click()
      await awaitPrompt(page, '')
      await tabs.nth(0).click()
      await awaitPrompt(page, value)
      console.log('PASS mode-switch: text/i2i isolated, empty edit cleared after F5')
    }
    await page.screenshot({ path: evidence + '/guest-' + name + '.png', fullPage: true })
    assert(errors.length === 0, name + ': JS errors ' + errors.join('; '))
    console.log('PASS guest-' + name + ': 54 characters survive immediate F5; no POST')
  } finally { await context.close() }
}

async function accountsCase(browser, name, viewport) {
  const context = await browser.newContext({ viewport })
  const state = { accountId: 'WEB-000001', posts: 0, failGenerate: false }
  await mockStudio(context, state)
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', (e) => errors.push(String(e)))
  try {
    await visit(page)
    const a = 'Секретный рабочий запрос пользователя А'
    await page.locator('.prompt-section textarea').fill(a)
    await reloadExpect(page, a)
    state.accountId = 'WEB-000002'
    await reloadExpect(page, '')
    const b = 'Другой рабочий запрос пользователя Б'
    await page.locator('.prompt-section textarea').fill(b)
    await reloadExpect(page, b)
    state.accountId = 'WEB-000001'
    await reloadExpect(page, a)
    state.accountId = null
    await reloadExpect(page, '')
    assert(state.posts === 0, 'Account transitions caused a generation POST')
    const keys = await page.evaluate(() => Object.keys(sessionStorage).filter((k) => k.startsWith('izo:studio-draft')))
    assert(keys.includes('izo:studio-draft-v2:user:WEB-000001'), 'Missing account A storage')
    assert(keys.includes('izo:studio-draft-v2:user:WEB-000002'), 'Missing account B storage')
    await page.screenshot({ path: evidence + '/account-isolation-' + name + '.png', fullPage: true })
    assert(errors.length === 0, 'Accounts: JS errors ' + errors.join('; '))
    console.log('PASS account-isolation-' + name + ': guest, A and B are independent; no POST')
  } finally { await context.close() }
}

async function logoutCase(browser) {
  const context = await browser.newContext({ viewport: { width: 1366, height: 900 } })
  const state = { accountId: 'WEB-000004', posts: 0, failGenerate: false }
  await mockStudio(context, state)
  const page = await context.newPage()
  try {
    await visit(page)
    const secret = 'Этот текст должен исчезнуть после выхода'
    await page.locator('.prompt-section textarea').fill(secret)
    await reloadExpect(page, secret)
    await page.locator('.top-token-summary').click()
    await page.locator('.account-logout').click()
    await page.waitForFunction(() => !sessionStorage.getItem('izo:studio-draft-v2:user:WEB-000004'))
    for (let i = 0; i < 30 && state.accountId !== null; i += 1) await page.waitForTimeout(100)
    assert(state.accountId === null, 'Logout mock endpoint was not called')
    await page.goto(origin + '/#text-to-image', { waitUntil: 'domcontentloaded' })
    await awaitPrompt(page, '')
    assert(state.posts === 0, 'Logout caused generation request')
    console.log('PASS logout: current account draft purged; guest stays empty')
  } finally { await context.close() }
}

async function sendCase(browser) {
  const context = await browser.newContext({ viewport: { width: 1366, height: 900 } })
  const state = { accountId: 'WEB-000003', posts: 0, failGenerate: true }
  await mockStudio(context, state)
  const page = await context.newPage()
  try {
    await visit(page)
    const value = 'Нарисуй мирный город после дождя'
    await page.locator('.prompt-section textarea').fill(value)
    await page.getByRole('button', { name: /Создать|Генерировать|Сгенерировать/i }).last().click()
    await page.waitForTimeout(500)
    assert(state.posts === 1, 'Failure case did not submit exactly once')
    assert((await page.locator('.prompt-section textarea').inputValue()) === value, 'Failed submit cleared draft')
    await reloadExpect(page, value)
    assert(state.posts === 1, 'Reload repeated failed POST')
    state.failGenerate = false
    await page.getByRole('button', { name: /Создать|Генерировать|Сгенерировать/i }).last().click()
    await awaitPrompt(page, '')
    assert(state.posts === 2, 'Successful submit did not submit exactly once')
    await reloadExpect(page, '')
    assert(state.posts === 2, 'Reload repeated successful POST')
    await page.screenshot({ path: evidence + '/after-submit.png', fullPage: true })
    console.log('PASS submit: failure retains draft; acknowledgement clears; reload never re-POSTs')
  } finally { await context.close() }
}

async function blockedStorageCase(browser) {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } })
  await context.addInitScript(() => {
    // Deny only the draft feature's keys: unrelated browser identity bootstrap
    // is outside this package and must remain independently functional.
    const read = Storage.prototype.getItem
    const write = Storage.prototype.setItem
    const remove = Storage.prototype.removeItem
    Storage.prototype.getItem = function (key) {
      if (String(key).startsWith('izo:studio-draft-v2:')) throw new Error('SecurityError')
      return read.call(this, key)
    }
    Storage.prototype.setItem = function (key, value) {
      if (String(key).startsWith('izo:studio-draft-v2:')) throw new Error('QuotaExceededError')
      return write.call(this, key, value)
    }
    Storage.prototype.removeItem = function (key) {
      if (String(key).startsWith('izo:studio-draft-v2:')) throw new Error('SecurityError')
      return remove.call(this, key)
    }
  })
  const state = { accountId: null, posts: 0, failGenerate: false }
  await mockStudio(context, state)
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', (err) => errors.push(String(err)))
  try {
    await visit(page)
    await page.locator('.prompt-section textarea').fill('Браузер отключил sessionStorage')
    assert((await page.locator('.prompt-section textarea').inputValue()).startsWith('Браузер'), 'Storage-denied composer failed')
    assert(errors.length === 0, 'Storage-denied app crash ' + errors.join('; '))
    console.log('PASS blocked-storage: editing works without storage and without JS errors')
  } finally { await context.close() }
}

if (!process.env.STUDIO207_URL) {
  const vite = fileURLToPath(new URL('./node_modules/vite/bin/vite.js', import.meta.url))
  preview = spawn(process.execPath, [vite, 'preview', '--host', '127.0.0.1', '--port', '5227', '--strictPort'], {
    cwd: fileURLToPath(new URL('.', import.meta.url)), stdio: ['ignore', 'pipe', 'pipe'],
  })
  await waitForPreview()
}
await mkdir(evidence, { recursive: true })
const browser = await chromium.launch({ headless: true })
try {
  await guestCase(browser, 'desktop', { width: 1366, height: 900 })
  await guestCase(browser, 'mobile', { width: 390, height: 844, isMobile: true, hasTouch: true })
  await accountsCase(browser, 'desktop', { width: 1366, height: 900 })
  await accountsCase(browser, 'mobile', { width: 390, height: 844, isMobile: true, hasTouch: true })
  await logoutCase(browser)
  await sendCase(browser)
  await blockedStorageCase(browser)
  console.log('STUDIO207_E2E_PASS')
} finally {
  await browser.close()
  if (preview) preview.kill()
}
