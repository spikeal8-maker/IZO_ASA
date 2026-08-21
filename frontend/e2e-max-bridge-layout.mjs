import { chromium } from 'playwright'

const origin = (process.env.IZO_E2E_BASE_URL || 'http://127.0.0.1:5173').replace(/\/$/, '')

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

async function run() {
  const browser = await chromium.launch()
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
  })
  const maxLoginBodies = []
  const pageErrors = []

  await context.route('https://st.max.ru/js/max-web-app.js', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/javascript',
      body: `window.WebApp = {
        initData: 'signed-max-test-data',
        platform: 'android',
        getViewportSize: () => Promise.resolve({ width: 390, height: 620 })
      };`,
    })
  })
  await context.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/auth/max-v2') {
      maxLoginBodies.push(route.request().postDataJSON())
    }
    if (url.pathname === '/api/auth/capabilities-v2') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          password_login_available: true,
          password_register_available: true,
          telegram_bot_login_available: true,
          max_bot_login_available: true,
        }),
      })
      return
    }
    await route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ detail: 'isolated MAX e2e' }) })
  })

  const page = await context.newPage()
  page.on('pageerror', (error) => pageErrors.push(String(error)))
  await page.goto(`${origin}/?platform=max&e2e=${Date.now()}`, { waitUntil: 'networkidle' })
  await page.locator('html.max-mini-app').waitFor()
  await page.waitForFunction(() => getComputedStyle(document.documentElement).getPropertyValue('--app-viewport-height').trim() === '620px')

  await page.getByRole('button', { name: 'Войти', exact: true }).first().click()
  const modal = page.locator('.auth-modal')
  await modal.waitFor()
  await page.getByRole('button', { name: 'Войти через MAX' }).waitFor()

  const report = await page.evaluate(() => {
    const modal = document.querySelector('.auth-modal')
    const overlay = document.querySelector('.auth-modal-overlay')
    if (!(modal instanceof HTMLElement) || !(overlay instanceof HTMLElement)) return null
    const modalBox = modal.getBoundingClientRect()
    const overlayBox = overlay.getBoundingClientRect()
    return {
      cssHeight: getComputedStyle(document.documentElement).getPropertyValue('--app-viewport-height').trim(),
      platform: document.documentElement.dataset.maxPlatform,
      bodyWidth: document.body.scrollWidth,
      modalBottom: modalBox.bottom,
      overlayHeight: overlayBox.height,
    }
  })

  assert(report, 'MAX auth modal was not rendered')
  assert(report.cssHeight === '620px', `official MAX viewport was not applied: ${report.cssHeight}`)
  assert(report.platform === 'android', `MAX platform marker is missing: ${report.platform}`)
  assert(report.overlayHeight === 620, `overlay does not match MAX viewport: ${report.overlayHeight}`)
  assert(report.modalBottom <= 621, `auth modal is clipped below MAX viewport: ${report.modalBottom}`)
  assert(report.bodyWidth <= 396, `horizontal overflow in MAX WebView: ${report.bodyWidth}`)
  assert(maxLoginBodies.some((body) => body?.web_app_data === 'signed-max-test-data'), 'official window.WebApp.initData was not sent to MAX auth')
  assert(pageErrors.length === 0, `page errors: ${JSON.stringify(pageErrors)}`)

  await context.close()
  await browser.close()
  console.log('MAX Bridge login and viewport layout passed')
}

run().catch((error) => {
  console.error(error)
  process.exit(1)
})
