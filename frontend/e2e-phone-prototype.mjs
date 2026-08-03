import { chromium } from 'playwright'

const origin = (process.env.IZO_E2E_BASE_URL || 'http://127.0.0.1:4178').replace(/\/$/, '')

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

const browser = await chromium.launch({ headless: true })
try {
  for (const viewport of [{ width: 390, height: 844 }, { width: 430, height: 932 }]) {
    const context = await browser.newContext({ viewport, isMobile: true, hasTouch: true })
    const page = await context.newPage()
    await page.goto(`${origin}/phone`, { waitUntil: 'domcontentloaded' })
    await page.locator('.phone-v32 .app-shell').waitFor()
    await page.locator('.phone-v32-nav').waitFor()
    await page.waitForTimeout(500)

    const layout = await page.evaluate(() => ({
      width: window.innerWidth,
      documentWidth: document.documentElement.scrollWidth,
      bodyWidth: document.body.scrollWidth,
      hasIframe: Boolean(document.querySelector('iframe')),
      navItems: document.querySelectorAll('.phone-v32-nav button').length,
      visiblePrompt: Boolean(document.querySelector('.prompt-card, .prompt-section, textarea')),
    }))
    assert(!layout.hasIframe, `${viewport.width}: phone view must not embed the static prototype`)
    assert(layout.navItems === 5, `${viewport.width}: functional phone navigation is incomplete`)
    assert(layout.visiblePrompt, `${viewport.width}: generation controls are missing`)
    assert(layout.documentWidth <= layout.width + 1, `${viewport.width}: document overflows horizontally`)
    assert(layout.bodyWidth <= layout.width + 1, `${viewport.width}: body overflows horizontally`)
    const apiResponses = await Promise.all(['/api/models', '/api/tariffs', '/api/model-access'].map(async (path) => {
      const response = await page.request.get(`${origin}${path}`)
      return { path, status: response.status() }
    }))
    assert(apiResponses.some((item) => item.status === 200), `${viewport.width}: real studio API did not respond ${JSON.stringify(apiResponses)}`)

    await page.locator('.phone-v32-nav button').filter({ hasText: 'Видео' }).click()
    await page.waitForURL(/\/phone\/video$/)
    await page.locator('.video-studio').waitFor({ timeout: 15_000 })

    await page.locator('.phone-v32-nav button').filter({ hasText: 'Картинка' }).click()
    await page.waitForURL(/\/phone$/)
    await page.locator('.iv3.mode-text').waitFor()

    await page.locator('.phone-v32-nav button').filter({ hasText: 'Профиль' }).click()
    await page.waitForTimeout(250)
    const profileOrAuth = await page.locator('.profile-page, [role="dialog"]').count()
    assert(profileOrAuth > 0, `${viewport.width}: profile/auth flow did not open`)
    await context.close()
  }
  console.log('Functional phone view passed at 390x844 and 430x932 with live studio API responses.')
} finally {
  await browser.close()
}
