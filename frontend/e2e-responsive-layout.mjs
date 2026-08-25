import { mkdirSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { chromium } from 'playwright'

const previewOrigin = (process.env.IZO_E2E_BASE_URL || 'http://127.0.0.1:5173').replace(/\/$/, '')
const screenshotDir = resolve(process.env.IZO_E2E_SCREENSHOT_DIR || '.')
const fullPageScreenshots = process.env.IZO_E2E_SCREENSHOT_MODE !== 'viewport'
const base = `${previewOrigin}/?platform=web&userId=layout_${Date.now()}`

mkdirSync(screenshotDir, { recursive: true })

const viewports = [
  { name: 'desktop-2048', width: 2048, height: 1152 },
  { name: 'desktop-1440', width: 1440, height: 900 },
  { name: 'laptop-1280', width: 1280, height: 720 },
  { name: 'tablet-768', width: 768, height: 1024, isMobile: true },
  { name: 'phone-430', width: 430, height: 932, isMobile: true },
  { name: 'phone-390', width: 390, height: 844, isMobile: true },
]

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

async function installIsolatedBackend(context) {
  await context.route('**/api/**', async (route) => {
    await route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'isolated layout e2e guest' }),
    })
  })
  await context.route('**/media/**', async (route) => {
    await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'not found' }) })
  })
}

async function assertNoBrokenLayout(page, label) {
  const report = await page.evaluate(() => {
    const selectors = [
      '.app-shell',
      '.rail',
      '.topbar',
      '.layout',
      '.control-panel',
      '.preview-panel',
      '.prompt-dock',
      '.profile-page',
      '.gallery-view',
    ]
    const visibleBoxes = selectors.flatMap((selector) => {
      return Array.from(document.querySelectorAll(selector)).map((node) => {
        const rect = node.getBoundingClientRect()
        const style = getComputedStyle(node)
        return {
          selector,
          display: style.display,
          width: rect.width,
          height: rect.height,
          left: rect.left,
          right: rect.right,
          top: rect.top,
          bottom: rect.bottom,
        }
      }).filter((box) => box.display !== 'none' && box.width > 0 && box.height > 0)
    })
    const overflowing = visibleBoxes.filter((box) => box.left < -3 || box.right > window.innerWidth + 3)
    const tinyText = Array.from(document.querySelectorAll('button, label, input, select, textarea, h2, span'))
      .filter((node) => node instanceof HTMLElement && node.offsetParent !== null)
      .map((node) => {
        const rect = node.getBoundingClientRect()
        return { text: node.textContent?.trim().slice(0, 80), width: rect.width, height: rect.height }
      })
      .filter((box) => box.width <= 0 || box.height <= 0)
    return {
      viewport: { width: window.innerWidth, height: window.innerHeight },
      documentWidth: document.documentElement.scrollWidth,
      bodyWidth: document.body.scrollWidth,
      overflowing,
      tinyText,
      hasProjectName: /ИЗО[_ ]АСА/.test(document.body.textContent || '') || /ИЗО[_ ]АСА/.test(document.title),
      hasProductShell: document.querySelector('.app-shell') instanceof HTMLElement,
      englishLeaks: Array.from(document.body.querySelectorAll('button, label, h2, span, summary'))
        .map((node) => node.textContent?.trim() || '')
        .filter(Boolean)
        .filter((text) => /\b(Generated image will appear here|Expand prompt|Help|Settings|Language|Target image)\b/.test(text)),
    }
  })

  assert(report.bodyWidth <= report.viewport.width + 6, `${label}: horizontal body overflow ${report.bodyWidth} > ${report.viewport.width}`)
  assert(report.documentWidth <= report.viewport.width + 6, `${label}: horizontal document overflow ${report.documentWidth} > ${report.viewport.width}`)
  assert(report.overflowing.length === 0, `${label}: visible elements overflow viewport ${JSON.stringify(report.overflowing)}`)
  assert(report.tinyText.length === 0, `${label}: invisible text controls ${JSON.stringify(report.tinyText)}`)
  assert(report.hasProjectName, `${label}: project name is missing`)
  assert(report.hasProductShell, `${label}: product shell is missing`)
  assert(report.englishLeaks.length === 0, `${label}: untranslated visible strings ${JSON.stringify(report.englishLeaks)}`)
}

async function runViewport(browser, viewport) {
  const context = await browser.newContext({
    viewport: { width: viewport.width, height: viewport.height },
    isMobile: Boolean(viewport.isMobile),
    hasTouch: Boolean(viewport.isMobile),
  })
  await installIsolatedBackend(context)
  const page = await context.newPage()
  page.setDefaultTimeout(15000)
  await page.goto(`${base}_${viewport.name}`, { waitUntil: 'networkidle' })
  await page.getByRole('button', { name: 'Создание и редактирование изображений' }).waitFor()
  await page.getByRole('tab', { name: /^По тексту/ }).waitFor()
  await page.locator('.preview-panel').waitFor()

  await assertNoBrokenLayout(page, `${viewport.name}: studio`)
  if (viewport.isMobile) {
    const navState = await page.evaluate(() => ({
      visibleTopbars: Array.from(document.querySelectorAll('.topbar')).filter((node) => node instanceof HTMLElement && node.offsetParent !== null).length,
      visibleModeTabs: Array.from(document.querySelectorAll('.mode-tabs')).filter((node) => node instanceof HTMLElement && node.offsetParent !== null).length,
      imageModeTabs: Array.from(document.querySelectorAll('.image-mode-tabs button')).filter((node) => node instanceof HTMLElement && node.offsetParent !== null).length,
      visibleTopActions: Array.from(document.querySelectorAll('.top-actions button')).filter((button) => button instanceof HTMLElement && button.offsetParent !== null).length,
      visibleLegacyBottomNavs: Array.from(document.querySelectorAll('.bottom-nav')).filter((node) => node instanceof HTMLElement && node.offsetParent !== null).length,
    }))
    assert(navState.visibleTopbars === 1, `${viewport.name}: expected one visible product topbar`)
    assert(navState.visibleModeTabs === 1, `${viewport.name}: generator mode navigation is missing or duplicated`)
    assert(navState.imageModeTabs === 4, `${viewport.name}: image mode navigation must expose four modes`)
    assert(navState.visibleTopActions > 0, `${viewport.name}: product actions are missing from the mobile topbar`)
    assert(navState.visibleLegacyBottomNavs === 0, `${viewport.name}: legacy bottom navigation must not overlap the product topbar`)
  }

  for (const name of ['По фото', 'Сборка', 'Редактор']) {
    await page.getByRole('tab', { name: new RegExp(`^${name}`) }).click()
    await page.locator('.preview-panel').waitFor()
    await assertNoBrokenLayout(page, `${viewport.name}: ${name}`)
    if (name === 'Редактор') {
      await page.locator('.paint-workbench').waitFor()
      const canvas = page.locator('.paint-stage canvas').first()
      await canvas.waitFor()
      const before = await canvas.evaluate((node) => node.toDataURL())
      const box = await canvas.boundingBox()
      assert(Boolean(box), `${viewport.name}: paint canvas has no box`)
      if (viewport.isMobile) {
        const touch = (x, y) => ({ identifier: 1, clientX: x, clientY: y })
        await canvas.dispatchEvent('touchstart', {
          touches: [touch(box.x + 60, box.y + 60)],
          targetTouches: [touch(box.x + 60, box.y + 60)],
          changedTouches: [touch(box.x + 60, box.y + 60)],
        })
        await canvas.dispatchEvent('touchmove', {
          touches: [touch(box.x + 160, box.y + 140)],
          targetTouches: [touch(box.x + 160, box.y + 140)],
          changedTouches: [touch(box.x + 160, box.y + 140)],
        })
        await canvas.dispatchEvent('touchend', {
          touches: [],
          targetTouches: [],
          changedTouches: [touch(box.x + 160, box.y + 140)],
        })
      } else {
        await page.mouse.move(box.x + 60, box.y + 60)
        await page.mouse.down()
        await page.mouse.move(box.x + 160, box.y + 140)
        await page.mouse.up()
      }
      await page.waitForTimeout(200)
      const after = await canvas.evaluate((node) => node.toDataURL())
      assert(before !== after, `${viewport.name}: paint canvas did not change after drawing`)
    }
  }

  await page.getByRole('button', { name: 'Войти' }).first().click()
  await page.locator('.auth-modal').waitFor()
  await assertNoBrokenLayout(page, `${viewport.name}: auth`)
  await page.getByRole('button', { name: 'Закрыть' }).click()
  await page.locator('.layout').waitFor()
  await assertNoBrokenLayout(page, `${viewport.name}: auth-back`)

  await page.screenshot({ path: join(screenshotDir, `layout-${viewport.name}.png`), fullPage: fullPageScreenshots })
  await context.close()
}

async function run() {
  const browser = await chromium.launch()
  try {
    for (const viewport of viewports) {
      await runViewport(browser, viewport)
      console.log(`Responsive layout passed: ${viewport.name}`)
    }
  } finally {
    await browser.close()
  }
}

run().catch((error) => {
  console.error(error)
  process.exit(1)
})



