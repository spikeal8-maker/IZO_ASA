// Real Chromium UI acceptance. Credentials arrive only through stdin, never argv/files.
import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'

const require = createRequire(new URL('../frontend/package.json', import.meta.url))
const { chromium } = require('playwright')
const chunks = []
for await (const chunk of process.stdin) chunks.push(chunk)
const input = JSON.parse(Buffer.concat(chunks).toString('utf8'))
const target = new URL(input.origin)
if (target.protocol !== 'http:' || target.hostname !== '127.0.0.1' ||
    Number(target.port) < 20000 || !/^[0-9a-f]{40}$/.test(input.sourceSha)) {
  throw new Error('BROWSER_TARGET_INVALID')
}
const output = path.resolve(input.output)
await mkdir(output, { recursive: true })
const result = { status: 'FAIL', sourceSha: input.sourceSha, checks: {}, screenshots: [] }
const ensure = (value, code) => { if (!value) throw new Error(code) }
let browser, desktop, mobile, guest, page

async function localContext(options) {
  const context = await browser.newContext(options)
  await context.route('**/*', async (route) => {
    const url = new URL(route.request().url())
    if (url.origin === target.origin || ['data:', 'blob:'].includes(url.protocol)) {
      await route.continue()
    } else {
      await route.abort('blockedbyclient')
    }
  })
  return context
}

async function screenshot(current, name) {
  await current.screenshot({ path: path.join(output, name), fullPage: false })
  result.screenshots.push(name)
}

async function pollJob(context, id) {
  const deadline = Date.now() + 60000
  while (Date.now() < deadline) {
    const response = await context.request.get(`${target.origin}/api/jobs/${id}`)
    ensure(response.status() === 200, 'BROWSER_JOB_READ_FAILED')
    const job = await response.json()
    if (job.status === 'completed') return job
    ensure(['queued', 'running', 'uploading', 'sent_to_comfyui'].includes(job.status),
      'BROWSER_JOB_TERMINAL_FAILURE')
    await new Promise((resolve) => setTimeout(resolve, 200))
  }
  throw new Error('BROWSER_JOB_TIMEOUT')
}

try {
  browser = await chromium.launch({ headless: true })
  result.browserVersion = browser.version()
  desktop = await localContext({ viewport: { width: 1440, height: 1000 } })
  page = await desktop.newPage()
  page.setDefaultTimeout(25000)
  await page.goto(`${target.origin}/profile`, { waitUntil: 'domcontentloaded' })
  const dialog = page.getByRole('dialog')
  await dialog.waitFor({ state: 'visible' })
  await screenshot(page, 'desktop-login.png')
  await dialog.locator('input[type="email"]').fill(input.email)
  await dialog.locator('input[type="password"]').fill(input.password)
  const [login] = await Promise.all([
    page.waitForResponse((response) => new URL(response.url()).pathname === '/api/auth/password/login-v2'),
    dialog.getByRole('button', { name: 'Войти', exact: true }).click(),
  ])
  ensure(login.status() === 200 && (await login.json()).ok === true, 'BROWSER_LOGIN_FAILED')
  input.password = ''
  input.email = ''
  await dialog.waitFor({ state: 'hidden' })
  await page.goto(target.origin, { waitUntil: 'domcontentloaded' })
  await page.locator('.prompt-section textarea').waitFor({ state: 'visible' })
  const me = await desktop.request.get(`${target.origin}/api/me-v2`)
  ensure(me.status() === 200, 'BROWSER_SESSION_MISSING')
  result.checks.login = 'PASS'
  const source = await page.locator('meta[name="izo-release"]').getAttribute('content')
  ensure(source === input.sourceSha, 'BROWSER_SOURCE_MISMATCH')
  await page.locator('.quality-button').filter({ hasText: 'Стандарт' }).first().click()
  await page.locator('.prompt-section textarea').fill('A blue ceramic cup, isolated CPU acceptance fixture')
  await screenshot(page, 'desktop-studio-before.png')
  const [started] = await Promise.all([
    page.waitForResponse((response) => new URL(response.url()).pathname === '/api/generate' &&
      response.request().method() === 'POST'),
    page.locator('button.generate-button').click(),
  ])
  ensure(started.request().postDataJSON().provider === 'comfyui', 'BROWSER_PROVIDER_MISMATCH')
  ensure(started.status() === 200, 'BROWSER_GENERATE_FAILED')
  const queued = await started.json()
  ensure(queued.status === 'queued' && typeof queued.id === 'string' && queued.tokenCost > 0,
    'BROWSER_QUEUE_MISMATCH')
  const job = await pollJob(desktop, queued.id)
  await page.locator('img.iv3-preview-main').waitFor({ state: 'visible', timeout: 60000 })
  await page.waitForFunction(() => {
    const image = document.querySelector('img.iv3-preview-main')
    return image?.complete && image.naturalWidth > 0
  })
  const rendered = await page.locator('img.iv3-preview-main').getAttribute('src')
  ensure(new URL(rendered, target.origin).pathname === new URL(job.resultUrl, target.origin).pathname,
    'BROWSER_RENDERED_RESULT_MISMATCH')
  result.checks.generation = { status: 'PASS', jobId: queued.id, imageId: job.resultImageId,
    tokenCost: queued.tokenCost, resultUrl: job.resultUrl }
  await screenshot(page, 'desktop-generated-image.png')
  const state = await desktop.storageState()
  await page.goto(`${target.origin}/gallery`, { waitUntil: 'domcontentloaded' })
  await page.locator('img[src*="/api/media/"], img[src*="/media/"]').first().waitFor({ state: 'visible' })
  await screenshot(page, 'desktop-gallery.png')
  result.checks.galleryScreen = 'PASS'

  mobile = await localContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1,
    isMobile: true, hasTouch: true, storageState: state })
  const phone = await mobile.newPage()
  await phone.goto(target.origin, { waitUntil: 'domcontentloaded' })
  await phone.locator('.prompt-section textarea').waitFor({ state: 'visible' })
  await screenshot(phone, 'mobile-studio.png')
  await phone.goto(`${target.origin}/gallery`, { waitUntil: 'domcontentloaded' })
  await phone.locator('img[src*="/api/media/"], img[src*="/media/"]').first().waitFor({ state: 'visible' })
  await screenshot(phone, 'mobile-gallery.png')
  result.checks.mobileScreens = 'PASS'

  guest = await localContext({ viewport: { width: 1440, height: 1000 } })
  const feed = await guest.newPage()
  await feed.goto(`${target.origin}/feed`, { waitUntil: 'domcontentloaded' })
  await feed.locator('img[src*="/api/feed/media/"]').first().waitFor({ state: 'visible' })
  await screenshot(feed, 'desktop-guest-feed.png')
  const denied = await guest.request.get(new URL(job.resultUrl, target.origin).href)
  ensure([401, 403, 404].includes(denied.status()), 'BROWSER_PRIVATE_MEDIA_EXPOSED')
  result.checks.guestFeedAndPrivateDenial = 'PASS'
  result.status = 'PASS'
} catch (error) {
  result.errorCode = /^BROWSER_[A-Z_]+$/.test(error.message) ? error.message :
    error.name === 'TimeoutError' ? 'BROWSER_UI_TIMEOUT' : 'BROWSER_UI_FAILED'
  if (page) {
    try {
      await screenshot(page, 'browser-failure.png')
      result.visibleControls = await page.locator('button, h1, h2').allTextContents()
      result.visibleControls = result.visibleControls.map((text) => text.trim().slice(0, 100)).slice(0, 50)
    } catch { result.failureScreenshot = 'UNAVAILABLE' }
  }
} finally {
  input.password = ''
  input.email = ''
  if (desktop) {
    try {
      await desktop.request.post(`${target.origin}/api/auth/session/logout-v2`, { data: {},
        headers: { Origin: target.origin } })
      const after = await desktop.request.get(`${target.origin}/api/me-v2`)
      ensure(after.status() === 401, 'BROWSER_LOGOUT_FAILED')
      result.checks.logout = 'PASS'
    } catch {
      result.checks.logout = 'FAIL'
      result.status = 'FAIL'
    }
  }
  for (const context of [guest, mobile, desktop]) if (context) await context.close()
  if (browser) await browser.close()
  await writeFile(path.join(output, 'browser.json'), JSON.stringify(result, null, 2) + '\n')
}
console.log(JSON.stringify({ status: result.status, errorCode: result.errorCode,
  screenshots: result.screenshots, checks: result.checks }))
process.exitCode = result.status === 'PASS' ? 0 : 1
