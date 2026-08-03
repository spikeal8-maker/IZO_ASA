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
    await page.goto(`${origin}/phone`, { waitUntil: 'load' })

    const frameElement = page.locator('iframe[title="Мобильный интерфейс ИЗО АСА"]')
    await frameElement.waitFor()
    const frame = page.frame({ url: /phone-prototype\.html$/ })
    assert(frame, `${viewport.width}: prototype iframe did not load`)
    await frame.getByRole('button', { name: 'Видео', exact: true }).waitFor()

    const layout = await page.evaluate(() => ({
      width: window.innerWidth,
      documentWidth: document.documentElement.scrollWidth,
      bodyWidth: document.body.scrollWidth,
      frame: (() => {
        const element = document.querySelector('iframe')
        if (!(element instanceof HTMLIFrameElement)) return null
        const rect = element.getBoundingClientRect()
        return { width: rect.width, height: rect.height }
      })(),
    }))
    assert(layout.documentWidth <= layout.width, `${viewport.width}: document overflows horizontally`)
    assert(layout.bodyWidth <= layout.width, `${viewport.width}: body overflows horizontally`)
    assert(layout.frame?.width === viewport.width, `${viewport.width}: iframe does not fill width`)
    assert(layout.frame?.height === viewport.height, `${viewport.width}: iframe does not fill height`)

    await frame.getByRole('button', { name: 'Видео', exact: true }).click()
    await frame.getByRole('button', { name: 'Сделать видео ♦ 12 кр.', exact: true }).waitFor()
    await frame.getByRole('button', { name: 'Открыть профиль и балансы', exact: true }).click()
    await page.waitForTimeout(350)

    const panels = await frame.evaluate(() => {
      const menu = document.querySelector('#shMenu')
      const profile = document.querySelector('#shYou')
      if (!(menu instanceof HTMLElement) || !(profile instanceof HTMLElement)) return null
      return {
        viewportHeight: document.documentElement.clientHeight,
        menuTop: menu.getBoundingClientRect().top,
        profileBottom: profile.getBoundingClientRect().bottom,
        profileOpen: profile.classList.contains('on'),
      }
    })
    assert(panels?.profileOpen, `${viewport.width}: profile panel did not open`)
    assert(panels.profileBottom <= panels.viewportHeight + 1, `${viewport.width}: profile panel exceeds viewport ${JSON.stringify(panels)}`)
    assert(panels.menuTop >= panels.viewportHeight, `${viewport.width}: hidden menu panel is visible ${JSON.stringify(panels)}`)
    await context.close()
  }
  console.log('Phone prototype e2e passed at 390x844 and 430x932.')
} finally {
  await browser.close()
}
