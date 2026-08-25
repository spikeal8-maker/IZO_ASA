import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'

const baseURL = process.env.QA_ADMIN_BASE_URL || 'http://127.0.0.1:5175'
const outDir = process.env.QA_ARTIFACT_DIR || 'visual-out'
mkdirSync(outDir, { recursive: true })
const pages = [
  ['OpenRouter', '/admin/models/openrouter', 'Модели OpenRouter'],
  ['Config UI', '/admin/models/config-ui', 'Локальные модели Config UI'],
  ['Энергопотребление', '/admin/models/energy', 'Энергопотребление'],
  ['Голосовой ввод', '/admin/models/voice-input', 'Голосовой ввод'],
  ['Улучшение промпта', '/admin/models/prompt-improvement', 'Улучшение промпта'],
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
  await page.route('**/api/admin/models-page**', (route) => route.fulfill(json({ detail: 'isolated navigation test' }, 503)))
  await page.route('**/api/admin/energy**', (route) => route.fulfill(json({ detail: 'isolated navigation test' }, 503)))
  await page.route('**/api/admin/voice**', (route) => route.fulfill(json({ detail: 'isolated navigation test' }, 503)))
}

async function verify(viewport) {
  const page = await browser.newPage({ viewport })
  await mockAdmin(page)
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
