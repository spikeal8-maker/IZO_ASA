import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { chromium } from 'playwright'

const origin = process.env.IZO_E2E_BASE_URL || 'http://127.0.0.1:4178'
const target = new URL(origin)
assert.ok(target.origin === origin && target.protocol === 'http:' && target.hostname === '127.0.0.1'
  && Number(target.port) > 1024, 'PHONE_MENU_LOOPBACK_REQUIRED')
const output = process.env.IZO_E2E_OUTPUT_DIR
if (output) await mkdir(output, { recursive: true, mode: 0o700 })
const workspace = (id, label, enabled = true) => ({ id, label, shortLabel: label,
  route: `/phone/${id}`, enabled, stage: enabled ? 'ready' : 'planned', navigation: 'primary', operations: [] })
const platform = { ok: true, apiVersion: 'v1', defaultRoute: '/phone/image',
  shell: { nativeReact: true, resumeJobs: true, offlineDrafts: true, notificationHost: true },
  contracts: { capabilities: 'v1', jobs: 'v1', media: 'v1', billing: 'v1' },
  workspaces: [workspace('image', 'Фото'), workspace('video', 'Видео'), workspace('chat', 'Чат'),
    workspace('audio', 'Звук'), workspace('3d', '3D-модель', false)] }
const responses = new Map([
  ['/api/phone/v1/platform', platform], ['/api/phone/v1/jobs', { ok: true, items: [] }],
  ['/api/me-v2', { profile: { display_name: 'Проверка меню' }, account: { token_balance: 0 } }],
  ['/api/model-access', { plan: 'free', modes: {} }], ['/api/models', { loras: [] }],
  ['/api/gallery/items', { items: [] }],
])
const report = { status: 'FAIL', evidenceClass: 'mocked-api-real-phone-ui', providerExecution: false,
  installedAcceptance: 'NOT_VERIFIED', cases: [], cleanup: 'NOT_RUN' }
const browser = await chromium.launch({ headless: true })
const watchdog = setTimeout(() => { void browser.close() }, 90000)
try {
  for (const width of [390, 430, 1360]) {
    const context = await browser.newContext({ viewport: { width, height: 932 }, hasTouch: true,
      isMobile: width < 600, reducedMotion: 'reduce', serviceWorkers: 'block' })
    const violations = [], errors = []
    await context.route('**/*', async (route) => {
      const request = route.request(), url = new URL(request.url())
      if (url.origin !== origin) { violations.push('EXTERNAL_REQUEST'); return route.abort('blockedbyclient') }
      if (!url.pathname.startsWith('/api/')) return route.continue()
      if (request.method() !== 'GET' || !responses.has(url.pathname)) {
        violations.push('UNEXPECTED_API'); return route.fulfill({ status: 409, json: { detail: 'Unexpected test request' } })
      }
      return route.fulfill({ status: 200, json: responses.get(url.pathname) })
    })
    const page = await context.newPage()
    page.setDefaultTimeout(4000)
    page.on('pageerror', () => errors.push('PAGE_ERROR'))
    const menu = page.getByRole('dialog', { name: 'Разделы ИЗО АСА', exact: true })
    const open = async () => {
      await page.getByRole('button', { name: 'Меню', exact: true }).click()
      await menu.waitFor({ state: 'visible' })
    }
    const passed = (name) => report.cases.push({ name: `${name}-${width}`, status: 'PASS' })
    try {
      await page.goto(`${origin}/phone/unknown`, { waitUntil: 'domcontentloaded' })
      await page.getByRole('heading', { name: 'Такого раздела нет', exact: true }).waitFor()
      await open()
      await menu.getByRole('button', { name: 'Закрыть меню', exact: true }).click()
      await menu.waitFor({ state: 'hidden' }); passed('mouse-close')
      await open()
      await menu.getByRole('button', { name: 'Закрыть меню', exact: true }).tap()
      await menu.waitFor({ state: 'hidden' }); passed('touch-close')
      await open()
      const disabled = menu.getByRole('button', { name: /3D-модель/ })
      assert.equal(await disabled.isDisabled(), true)
      const disabledBox = await disabled.boundingBox()
      await page.mouse.click(disabledBox.x + disabledBox.width / 2, disabledBox.y + disabledBox.height / 2)
      assert.equal(await menu.isVisible(), true)
      assert.equal(new URL(page.url()).pathname, '/phone/unknown'); passed('disabled-workspace')
      await menu.getByRole('button', { name: /Фото/ }).click()
      await menu.waitFor({ state: 'hidden' })
      assert.equal(new URL(page.url()).pathname, '/phone/image'); passed('mouse-workspace')
      await page.goto(`${origin}/phone/unknown`, { waitUntil: 'domcontentloaded' })
      await open()
      await menu.getByRole('button', { name: /Фото/ }).tap()
      await menu.waitFor({ state: 'hidden' })
      assert.equal(new URL(page.url()).pathname, '/phone/image'); passed('touch-workspace')
      await open(); await page.keyboard.press('Escape'); await menu.waitFor({ state: 'hidden' }); passed('escape')
      await open()
      const backdrop = await page.locator('.phone-sheet-backdrop').boundingBox()
      await page.mouse.click(backdrop.x + 10, backdrop.y + 10)
      await menu.waitFor({ state: 'hidden' }); passed('backdrop')
      await open()
      const header = await menu.locator('header h2').boundingBox()
      const start = { x: header.x + header.width / 2, y: header.y + header.height / 2 }
      await page.mouse.move(start.x, start.y); await page.mouse.down()
      await page.mouse.move(start.x, start.y + 30, { steps: 3 }); await page.mouse.up()
      assert.equal(await menu.isVisible(), true)
      assert.equal(await menu.evaluate((node) => node.style.transform), 'translateY(0px)'); passed('short-drag-reset')
      const cdp = await context.newCDPSession(page)
      try {
        await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ ...start, id: 7 }] })
        await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: start.x, y: start.y + 40, id: 7 }] })
        await cdp.send('Input.dispatchTouchEvent', { type: 'touchCancel', touchPoints: [] })
        assert.equal(await menu.isVisible(), true)
        assert.equal(await menu.evaluate((node) => node.style.transform), 'translateY(0px)'); passed('touch-cancel-reset')
        await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ ...start, id: 8 }] })
        for (const offset of [25, 50, 80, 110]) {
          await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: start.x, y: start.y + offset, id: 8 }] })
        }
        await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] })
        await menu.waitFor({ state: 'hidden' }); passed('touch-swipe-close')
      } finally { await cdp.detach() }
      await open()
      const sheet = await menu.boundingBox()
      await page.mouse.move(sheet.x + sheet.width / 2, sheet.y + 8); await page.mouse.down()
      await page.mouse.move(sheet.x + sheet.width / 2, sheet.y + 140, { steps: 5 }); await page.mouse.up()
      await menu.waitFor({ state: 'hidden' }); passed('mouse-swipe-close')
      await open()
      if (output) await page.screenshot({ path: path.join(output, `phone-menu-${width}.png`), animations: 'disabled' })
      await menu.getByRole('button', { name: 'Закрыть меню', exact: true }).click()
      await menu.waitFor({ state: 'hidden' })
      assert.deepEqual(errors, []); assert.deepEqual(violations, []); passed('no-errors-or-external-effects')
    } catch (error) {
      report.failedViewport = width
      report.errorCode = error?.name === 'TimeoutError' ? 'PHONE_MENU_INTERACTION_TIMEOUT' : 'PHONE_MENU_INTERACTION_FAILED'
      if (output) await page.screenshot({ path: path.join(output, `phone-menu-failure-${width}.png`), animations: 'disabled' }).catch(() => {})
      throw error
    } finally { await context.close() }
  }
  report.status = 'PASS'
} finally {
  clearTimeout(watchdog)
  await browser.close()
  report.cleanup = 'PASS'
  if (output) await writeFile(path.join(output, 'phone-menu-interactions.json'), JSON.stringify(report, null, 2) + '\n', { mode: 0o600 })
  console.log(JSON.stringify(report))
}
