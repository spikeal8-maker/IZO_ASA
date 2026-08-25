import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'

const baseURL = process.env.QA_ADMIN_BASE_URL || 'http://127.0.0.1:5174'
const outDir = process.env.QA_ARTIFACT_DIR || 'visual-out'
mkdirSync(outDir, { recursive: true })

const json = (body) => ({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
const point = (hour, value) => ({ date: new Date(Date.UTC(2026, 7, 21, hour)).toISOString(), value })
const timeline = {
  generations_24h: [point(8, 0), point(9, 3), point(10, 7), point(11, 4)],
  local_images_24h: [point(8, 0), point(9, 2), point(10, 3), point(11, 2)],
  paid_images_24h: [point(8, 0), point(9, 0), point(10, 2), point(11, 1)],
  videos_24h: [point(8, 0), point(9, 1), point(10, 2), point(11, 1)],
}
const summary = {
  users: 44,
  activeToday: 2,
  activeSessions: 2,
  generationsToday: 14,
  errors24h: 0,
  queue: [{ id: 'queued-1', status: 'queued' }],
  timeline,
}
const dashboard = {
  dashboard: {
    totals: { users: 44 },
    sessions_active: 2,
    periods: { today: { users: { active: 2 }, generations: { total: 14, failed: 1 } } },
    ranges: {
      '1h': { users: { active: 1 }, generations: { total: 3 } },
      '6h': { users: { active: 4 }, generations: { total: 9 } },
      '12h': { users: { active: 5 }, generations: { total: 11 } },
      '24h': { users: { active: 6 }, generations: { total: 14 } },
      '7d': { users: { active: 15 }, generations: { total: 40 } },
      '30d': { users: { active: 27 }, generations: { total: 80 } },
      '90d': { users: { active: 38 }, generations: { total: 120 } },
    },
  },
}
const me = {
  internal_user_id: 'admin-iuid',
  profile: { display_name: 'Администратор', public_user_code: 'WEB-000006' },
  account: { role: 'admin', plan: 'mini', token_balance: 100 },
}

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

async function mockAdmin(page) {
  await page.route('**/api/auth/bootstrap-v2', (route) => route.fulfill(json({ installation_id: 'qa-install', anonymous_id: 'qa-anon' })))
  await page.route('**/api/me-v2', (route) => route.fulfill(json(me)))
  await page.route('**/api/admin/summary', (route) => route.fulfill(json(summary)))
  await page.route('**/api/admin/dashboard-v2', (route) => route.fulfill(json(dashboard)))
}

async function verify(viewport, screenshotName) {
  const page = await browser.newPage({ viewport })
  const consoleErrors = []
  page.on('console', (message) => { if (message.type() === 'error') consoleErrors.push(message.text()) })
  await mockAdmin(page)
  await page.goto(`${baseURL}/admin/dashboard`, { waitUntil: 'networkidle', timeout: 40000 })
  try {
    await page.locator('.admin-generation-chart').first().waitFor({ timeout: 15000 })
  } catch (error) {
    console.error((await page.locator('body').innerText()).slice(0, 3000))
    console.error(consoleErrors.join(' | '))
    await page.screenshot({ path: `${outDir}/admin-dashboard-layout-failure.png`, fullPage: true })
    throw error
  }

  assert(await page.locator('.admin-content-heading > .admin-kpi-strip span').count() === 6, 'header must contain four live and two financial indicators')
  assert(await page.getByLabel('Период показателей').inputValue() === '24', 'dashboard header period must default to 24 hours')
  assert((await page.locator('.admin-kpi-strip').innerText()).includes('—\nпотрачено'), 'spent placeholder is missing')
  assert((await page.locator('.admin-kpi-strip').innerText()).includes('—\nзаработано'), 'earned placeholder is missing')
  await page.getByLabel('Период показателей').selectOption('7')
  const periodKpis = await page.locator('.admin-kpi-strip').innerText()
  assert(periodKpis.includes('15\nактивны за 7 дн.'), 'active users did not follow selected period')
  assert(periodKpis.includes('40\nгенераций за 7 дн.'), 'generation count did not follow selected period')
  assert(await page.locator('.admin-topline').count() === 0, 'legacy top line is still rendered')
  assert(await page.locator('.admin-grid-compact').count() === 0, 'duplicated KPI cards are still rendered')
  assert(await page.locator('.admin-generation-chart').count() === 4, 'dashboard must contain generation, activity, payment and energy charts')
  assert(await page.locator('.admin-generation-chart').first().locator('.series').count() === 4, 'combined generation chart must contain four series')
  assert(await page.locator('.admin-sidebar').count() === 1, 'admin sidebar is missing')
  assert(await page.locator('.admin-sidebar').evaluate((element) => getComputedStyle(element).borderRadius) === '0px', 'sidebar must not use a rounded container')
  assert(await page.locator('.admin-generation-chart').first().evaluate((element) => getComputedStyle(element).borderRadius) === '0px', 'dashboard charts must use strict square geometry')
  assert(await page.getByRole('navigation', { name: 'Разделы админки' }).getByRole('button').count() === 10, 'admin navigation tabs are incomplete')
  const legendText = await page.locator('.admin-generation-legend').first().innerText()
  for (const label of ['Всего', 'Базовая модель', 'Платные изображения', 'Видео']) {
    assert(legendText.includes(label), `combined chart legend missing ${label}`)
  }
  const pageOverflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1)
  assert(!pageOverflow, `page overflows horizontally at ${viewport.width}px`)
  if (viewport.width <= 480) {
    const plotScrolls = await page.locator('.admin-generation-plot').first().evaluate((element) => element.scrollWidth > element.clientWidth)
    assert(plotScrolls, 'mobile chart must scroll inside its own container')
  }
  assert(consoleErrors.length === 0, `browser console errors: ${consoleErrors.join(' | ')}`)
  await page.screenshot({ path: `${outDir}/${screenshotName}`, fullPage: true })
  await page.close()
}

const browser = await chromium.launch({ headless: true })
try {
  await verify({ width: 1900, height: 950 }, 'admin-dashboard-unified-desktop.png')
  await verify({ width: 390, height: 844 }, 'admin-dashboard-unified-mobile.png')
  console.log('e2e-admin-dashboard-layout OK')
} finally {
  await browser.close()
}
